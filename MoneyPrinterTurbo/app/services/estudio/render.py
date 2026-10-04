"""
Etapa RENDER: un clip por plano con ffmpeg, concatenado, y el acabado (voz +
musica + subtitulos + codec) con video.generate_video de MoneyPrinterTurbo.

Clips cacheados por plano: la clave del clip es (recurso, duracion en frames,
offset, formato, encaje, zoom). Cambiar un plano rehace ESE clip; cambiar solo
los subtitulos o la musica no rehace ninguno.

Imagenes: efecto Ken Burns (zoom lento, alterna acercar/alejar) con zoompan.
Videos:   trozo desde `offset`; si el video es mas corto que el plano, bucle.
Encaje:   recortar (llena la pantalla) | desenfoque (entero sobre fondo
          desenfocado) | negro (entero con bandas).
"""
import hashlib
import os
from concurrent.futures import ThreadPoolExecutor, as_completed

from loguru import logger

from app.models.schema import VideoAspect, VideoParams
from app.services import video as mpt_video
from app.services.estudio import acabado, edicion, medios

DEFECTOS = {
    "aspecto": "9:16",
    "encaje": "desenfoque",
    "zoom": 0.08,
    "subtitulos": True,
    "sub_posicion": "bottom",
    "sub_posicion_pct": 70.0,
    "fuente": "STHeitiMedium.ttc",
    "tam_fuente": 60,
    "color_texto": "#FFFFFF",
    "color_contorno": "#000000",
    "grosor_contorno": 1.5,
    "sub_fondo": True,
    "sub_fondo_redondeado": False,
    "musica": "random",
    "musica_volumen": 0.2,
    "volumen_voz": 1.0,
    "codec": "",
    "acabado": "rapido",
}

FPS = 30
VERSION_CLIP = "1"
PARALELO = 3


def _encaje(modo, w, h):
    if modo == "recortar":
        return f"scale={w}:{h}:force_original_aspect_ratio=increase,crop={w}:{h},setsar=1"
    if modo == "negro":
        return (f"scale={w}:{h}:force_original_aspect_ratio=decrease,"
                f"pad={w}:{h}:(ow-iw)/2:(oh-ih)/2:black,setsar=1")
    return (f"split[a][b];[a]scale={w}:{h}:force_original_aspect_ratio=increase,crop={w}:{h},"
            f"boxblur=24:2[fondo];[b]scale={w}:{h}:force_original_aspect_ratio=decrease[frente];"
            f"[fondo][frente]overlay=(W-w)/2:(H-h)/2,setsar=1")


def _salida_x264(frames, destino):
    return ["-frames:v", str(frames), "-r", str(FPS), "-an", "-c:v", "libx264",
            "-preset", "veryfast", "-crf", "20", "-pix_fmt", "yuv420p", destino]


def _clip_imagen(ruta, frames, w, h, encaje, zoom, acercar, destino, encuadre=1.0, extra=""):
    ff = medios.ffmpeg()
    if zoom and zoom > 0:
        # Se encaja al doble de tamano y zoompan reescala: sin eso el zoom tiembla.
        z = (f"1+{zoom}*on/{frames}" if acercar else f"{1 + zoom}-{zoom}*on/{frames}")
        if encuadre != 1.0:  # subcorte de la edicion editorial: mismo movimiento, mas cerca
            z = f"{encuadre}*({z})"
        filtro = (f"{_encaje(encaje, w * 2, h * 2)},zoompan=z='{z}':x='iw/2-(iw/zoom/2)':"
                  f"y='ih/2-(ih/zoom/2)':d={frames}:s={w}x{h}:fps={FPS}{extra},format=yuv420p")
        args = [ff, "-hide_banner", "-loglevel", "error", "-y", "-i", ruta,
                "-filter_complex", filtro] + _salida_x264(frames, destino)
    else:
        filtro = f"{_encaje(encaje, w, h)}{_cerrar(encuadre, w, h)}{extra},format=yuv420p"
        args = [ff, "-hide_banner", "-loglevel", "error", "-y", "-loop", "1", "-framerate", str(FPS),
                "-i", ruta, "-filter_complex", filtro] + _salida_x264(frames, destino)
    return args


def _cerrar(encuadre, w, h):
    """Encuadre mas cerrado (recorta al centro y vuelve al tamano)."""
    if encuadre == 1.0:
        return ""
    return f",crop=trunc(iw/{encuadre}/2)*2:trunc(ih/{encuadre}/2)*2,scale={w}:{h},setsar=1"


def _clip_congelado(ruta, frames, w, h, encaje, offset, destino, encuadre=1.0, extra=""):
    """Pausa dramatica: UN fotograma (del video en `offset`, o la imagen) que se
    acerca despacio durante toda la pieza."""
    z = f"{encuadre}*(1+0.06*on/{frames})"
    filtro = (f"trim=end_frame=1,{_encaje(encaje, w * 2, h * 2)},zoompan=z='{z}':x='iw/2-(iw/zoom/2)':"
              f"y='ih/2-(ih/zoom/2)':d={frames}:s={w}x{h}:fps={FPS}{extra},format=yuv420p")
    args = [medios.ffmpeg(), "-hide_banner", "-loglevel", "error", "-y"]
    if offset > 0:
        args += ["-ss", f"{offset:.3f}"]
    return args + ["-i", ruta, "-filter_complex", filtro] + _salida_x264(frames, destino)


def _clip_video(ruta, frames, w, h, encaje, offset, dur_recurso, destino, encuadre=1.0, extra=""):
    necesita = frames / FPS
    bucle = dur_recurso and (offset + necesita) > dur_recurso + 0.05
    args = [medios.ffmpeg(), "-hide_banner", "-loglevel", "error", "-y"]
    if bucle:
        args += ["-stream_loop", "-1"]
    if offset > 0:
        args += ["-ss", f"{offset:.3f}"]
    filtro = f"{_encaje(encaje, w, h)}{_cerrar(encuadre, w, h)}{extra},fps={FPS},format=yuv420p"
    return args + ["-i", ruta, "-filter_complex", filtro] + _salida_x264(frames, destino)


def _hacer_clip(plano, recurso, frames, w, h, p, destino):
    tmp = destino + ".tmp.mp4"
    encuadre = float(plano.get("encuadre") or 1.0)
    extra = ""
    if plano.get("pasado"):
        extra += "," + edicion.FILTRO_PASADO
    offset = float(plano.get("offset") or 0) + float(plano.get("desde") or 0)
    if plano.get("efecto") == "pausa":
        extra += "," + edicion.FILTRO_PAUSA
        args = _clip_congelado(recurso["ruta"], frames, w, h, p["encaje"],
                               offset if plano["tipo"] == "video" else 0, tmp, encuadre, extra)
    elif plano["tipo"] == "imagen":
        args = _clip_imagen(recurso["ruta"], frames, w, h, p["encaje"], float(p["zoom"] or 0),
                            (plano["i"] + plano.get("pieza", 0)) % 2 == 0, tmp, encuadre, extra)
    else:
        args = _clip_video(recurso["ruta"], frames, w, h, p["encaje"], offset,
                           float(recurso.get("duracion") or 0), tmp, encuadre, extra)
    r = medios.correr(args, timeout=900)
    if r.returncode != 0 or not os.path.exists(tmp):
        raise RuntimeError(f"ffmpeg fallo en el plano {plano['i']} ({recurso['nombre']}): {r.stderr[-400:]}")
    os.replace(tmp, destino)


def _concatenar(clips, destino):
    lista = destino + ".txt"
    with open(lista, "w", encoding="utf-8") as f:
        for c in clips:
            f.write("file '" + c.replace("\\", "/").replace("'", "'\\''") + "'\n")
    r = medios.correr([medios.ffmpeg(), "-hide_banner", "-loglevel", "error", "-y", "-f", "concat",
                       "-safe", "0", "-i", lista, "-c", "copy", destino], timeout=1800)
    os.remove(lista)
    if r.returncode != 0:
        raise RuntimeError(f"no se pudieron unir los clips: {r.stderr[-400:]}")


def _video_params(p, titulo):
    musica = (p.get("musica") or "").strip()
    return VideoParams(
        video_subject=titulo or "estudio",
        video_aspect=p["aspecto"],
        voice_volume=float(p["volumen_voz"]),
        bgm_type="random" if musica else "",
        bgm_file="" if musica in ("", "random") else musica,
        bgm_volume=float(p["musica_volumen"]),
        subtitle_enabled=bool(p["subtitulos"]),
        subtitle_position=p["sub_posicion"],
        custom_position=float(p["sub_posicion_pct"]),
        font_name=p["fuente"],
        font_size=int(p["tam_fuente"]),
        text_fore_color=p["color_texto"],
        stroke_color=p["color_contorno"],
        stroke_width=float(p["grosor_contorno"]),
        text_background_color=bool(p["sub_fondo"]),
        rounded_subtitle_background=bool(p["sub_fondo_redondeado"]),
        video_codec=p.get("codec") or None,
        n_threads=2,
    )


def ejecutar(ctx):
    p = ctx.params
    planos = (ctx.salidas["asignacion"] or {}).get("planos") or []
    voz = ctx.salidas["voz"] or {}
    if not planos:
        raise ValueError("no hay planos asignados")
    w, h = VideoAspect(p["aspecto"]).to_resolution()
    dir_clips = ctx.dir("render", "clips")
    rapido = p.get("acabado", "rapido") == "rapido" and acabado.tiene_libass(medios.ffmpeg())
    sin_voz = bool(voz.get("sin_voz"))
    editorial = rapido and edicion.activa(p) and not sin_voz

    # Editorial: Claude marca antes de los clips (las revelaciones deciden los
    # subcortes) y los planos se parten en piezas. Si no, una pieza por plano.
    piezas = [{**x, "encuadre": 1.0, "desde": 0.0, "pieza": 0, "efecto": None, "pasado": False} for x in planos]
    if editorial:
        ctx.avisar(f"{edicion.nombre(p)}: marcas de Claude", 1)
        lineas, marcas_ = edicion.lineas_y_marcas(ctx, voz, p)
        piezas = edicion.subcortes(planos, lineas, marcas_, edicion.opciones(p))

    trabajos, clips = [], []
    for x in piezas:
        frames = max(1, round(x["fin"] * FPS) - round(x["inicio"] * FPS))
        if not os.path.exists(x["ruta"]):
            raise FileNotFoundError(f"plano {x['i']}: el recurso {x['nombre']} ya no esta en disco")
        r = {"ruta": x["ruta"], "nombre": x["nombre"], "duracion": x.get("dur_recurso", 0.0)}
        base = (VERSION_CLIP, x["recurso"], x["tipo"], frames, x.get("offset"), w, h, p["encaje"], p["zoom"],
                (x["i"] + x["pieza"]) % 2 if x["tipo"] == "imagen" else 0)
        if x["encuadre"] != 1.0 or x["desde"]:  # sin subcortes la clave es la de siempre: cache intacta
            base += (x["encuadre"], x["desde"] if x["tipo"] == "video" else 0)
        if x["efecto"] or x["pasado"]:
            base += (x["efecto"], x["pasado"], x["desde"] if x["efecto"] == "pausa" else 0)
        clave = hashlib.sha1(repr(base).encode()).hexdigest()[:16]
        destino = os.path.join(dir_clips, f"{clave}.mp4")
        clips.append(destino)
        # Piezas identicas comparten clip: se hace UNA vez (en paralelo chocarian en el mismo archivo).
        if not os.path.exists(destino) and destino not in {t[3] for t in trabajos}:
            trabajos.append((x, r, frames, destino))

    ctx.avisar(f"{len(piezas)} clips: {len(piezas) - len(trabajos)} reutilizados, "
               f"{len(trabajos)} por hacer", 2)
    hechos = 0
    with ThreadPoolExecutor(max_workers=PARALELO) as ex:
        futuros = [ex.submit(_hacer_clip, x, r, fr, w, h, p, d) for x, r, fr, d in trabajos]
        for fut in as_completed(futuros):
            fut.result()
            hechos += 1
            ctx.avisar(f"clips {hechos}/{len(trabajos)}", 2 + 68 * hechos / max(1, len(trabajos)))

    carpeta = ctx.dir("render")
    combinado = os.path.join(carpeta, "combinado.mp4")
    ctx.avisar("uniendo clips", 72)
    _concatenar(clips, combinado)

    final = os.path.join(carpeta, "final.mp4")
    tmp_final = os.path.join(carpeta, "final.tmp.mp4")
    audio = ctx.dir(voz["audio"], crear=False)
    srt = ctx.dir(voz["srt"], crear=False) if p["subtitulos"] and not sin_voz else ""
    if sin_voz:
        ctx.avisar("sin voz: sonido de los clips", 73)
        audio = _audio_de_clips(planos, carpeta)
    if p.get("acabado", "rapido") == "rapido" and not rapido:
        logger.warning("este ffmpeg no trae libass: se usa el acabado clasico (lento)")
    resumen_edicion = None
    if edicion.activa(p) and not rapido:
        logger.warning(f"la {edicion.nombre(p)} necesita el acabado rapido (ffmpeg con libass): se ignora")
    if editorial:
        ctx.avisar(f"{edicion.nombre(p)}: preparando subtitulos, rotulos y sonido", 73)
        ed = edicion.preparar(ctx, voz, planos, p, w, h, float(voz["duracion"]))
        resumen_edicion = ed["resumen"]
        ctx.avisar(ed["resumen"], 76)
        ctx.avisar("acabado rapido (ffmpeg): voz, musica, subtitulos y efectos", 78)
        acabado.acabar(combinado, audio, None, p, w, h, float(voz["duracion"]), tmp_final,
                       ass=ed["ass"], sfx=ed["sfx"], ducking=ed["ducking"], color=ed["color"])
    elif rapido:
        ctx.avisar("acabado rapido (ffmpeg): voz, musica y subtitulos", 75)
        acabado.acabar(combinado, audio, srt or None, p, w, h, float(voz["duracion"]), tmp_final)
    else:
        ctx.avisar("acabado clasico de MPT (MoviePy): voz, musica y subtitulos -- tarda", 75)
        mpt_video.generate_video(
            video_path=combinado,
            audio_path=audio,
            subtitle_path=srt,
            output_file=tmp_final,
            params=_video_params(p, ctx.proyecto.get("titulo")),
        )
    if not os.path.exists(tmp_final):
        raise RuntimeError("el acabado no produjo el video final")
    os.replace(tmp_final, final)
    _limpiar_clips(dir_clips, set(clips))
    info = medios.sondear(final)
    ctx.avisar(f"video listo: {info['duracion']:.1f}s", 100)
    return {"mp4": "render/final.mp4", "duracion": info["duracion"], "ancho": w, "alto": h,
            "clips_nuevos": len(trabajos), "clips_reutilizados": len(piezas) - len(trabajos),
            "edicion": resumen_edicion,
            "tam_mb": round(os.path.getsize(final) / 1e6, 1)}


def _audio_de_clips(planos, carpeta):
    """Pista con el sonido de cada clip en su tramo (silencio en imagenes o
    videos mudos). Se usa como "voz" cuando el video no lleva narracion."""
    trozos_dir = os.path.join(carpeta, "audio_clips")
    os.makedirs(trozos_dir, exist_ok=True)
    ff = medios.ffmpeg()
    trozos = []
    for x in planos:
        frames = max(1, round(x["fin"] * FPS) - round(x["inicio"] * FPS))
        dur = frames / FPS
        destino = os.path.join(trozos_dir, f"{x['i']:04d}.wav")
        base = [ff, "-hide_banner", "-loglevel", "error", "-y"]
        if x["tipo"] == "video" and medios.tiene_audio(x["ruta"]):
            offset = float(x.get("offset") or 0)
            dur_rec = float(x.get("dur_recurso") or 0)
            if dur_rec and offset + dur > dur_rec + 0.05:
                base += ["-stream_loop", "-1"]
            if offset > 0:
                base += ["-ss", f"{offset:.3f}"]
            args = base + ["-i", x["ruta"], "-vn", "-af", "apad", "-t", f"{dur:.3f}"]
        else:
            args = base + ["-f", "lavfi", "-i", "anullsrc=r=44100:cl=stereo", "-t", f"{dur:.3f}"]
        r = medios.correr(args + ["-ar", "44100", "-ac", "2", "-c:a", "pcm_s16le", destino], timeout=300)
        if r.returncode != 0:
            raise RuntimeError(f"no se pudo sacar el audio del plano {x['i']}: {r.stderr[-300:]}")
        trozos.append(destino)
    salida = os.path.join(carpeta, "audio_clips.wav")
    lista = salida + ".txt"
    with open(lista, "w", encoding="utf-8") as f:
        for t in trozos:
            f.write("file '" + t.replace("\\", "/") + "'\n")
    r = medios.correr([ff, "-hide_banner", "-loglevel", "error", "-y", "-f", "concat", "-safe", "0",
                       "-i", lista, "-c", "copy", salida], timeout=600)
    os.remove(lista)
    for t in trozos:
        os.remove(t)
    if r.returncode != 0:
        raise RuntimeError(f"no se pudo unir el audio de los clips: {r.stderr[-300:]}")
    return salida


def _limpiar_clips(carpeta, vivos, conservar=400):
    """Borra clips viejos que ya no usa el render actual, dejando un margen."""
    viejos = [os.path.join(carpeta, n) for n in os.listdir(carpeta)
              if os.path.join(carpeta, n) not in vivos]
    viejos.sort(key=os.path.getmtime)
    for ruta in viejos[:max(0, len(viejos) - conservar)]:
        try:
            os.remove(ruta)
        except OSError:
            logger.warning(f"no se pudo borrar {ruta}")
