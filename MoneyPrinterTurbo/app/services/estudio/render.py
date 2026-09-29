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
from app.services.estudio import acabado, medios

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


def _clip_imagen(ruta, frames, w, h, encaje, zoom, acercar, destino):
    ff = medios.ffmpeg()
    if zoom and zoom > 0:
        # Se encaja al doble de tamano y zoompan reescala: sin eso el zoom tiembla.
        z = (f"1+{zoom}*on/{frames}" if acercar else f"{1 + zoom}-{zoom}*on/{frames}")
        filtro = (f"{_encaje(encaje, w * 2, h * 2)},zoompan=z='{z}':x='iw/2-(iw/zoom/2)':"
                  f"y='ih/2-(ih/zoom/2)':d={frames}:s={w}x{h}:fps={FPS},format=yuv420p")
        args = [ff, "-hide_banner", "-loglevel", "error", "-y", "-i", ruta,
                "-filter_complex", filtro] + _salida_x264(frames, destino)
    else:
        filtro = f"{_encaje(encaje, w, h)},format=yuv420p"
        args = [ff, "-hide_banner", "-loglevel", "error", "-y", "-loop", "1", "-framerate", str(FPS),
                "-i", ruta, "-filter_complex", filtro] + _salida_x264(frames, destino)
    return args


def _clip_video(ruta, frames, w, h, encaje, offset, dur_recurso, destino):
    necesita = frames / FPS
    bucle = dur_recurso and (offset + necesita) > dur_recurso + 0.05
    args = [medios.ffmpeg(), "-hide_banner", "-loglevel", "error", "-y"]
    if bucle:
        args += ["-stream_loop", "-1"]
    if offset > 0:
        args += ["-ss", f"{offset:.3f}"]
    filtro = f"{_encaje(encaje, w, h)},fps={FPS},format=yuv420p"
    return args + ["-i", ruta, "-filter_complex", filtro] + _salida_x264(frames, destino)


def _hacer_clip(plano, recurso, frames, w, h, p, destino):
    tmp = destino + ".tmp.mp4"
    if plano["tipo"] == "imagen":
        args = _clip_imagen(recurso["ruta"], frames, w, h, p["encaje"], float(p["zoom"] or 0),
                            plano["i"] % 2 == 0, tmp)
    else:
        args = _clip_video(recurso["ruta"], frames, w, h, p["encaje"], float(plano.get("offset") or 0),
                           float(recurso.get("duracion") or 0), tmp)
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

    trabajos, clips = [], []
    for x in planos:
        frames = max(1, round(x["fin"] * FPS) - round(x["inicio"] * FPS))
        if not os.path.exists(x["ruta"]):
            raise FileNotFoundError(f"plano {x['i']}: el recurso {x['nombre']} ya no esta en disco")
        r = {"ruta": x["ruta"], "nombre": x["nombre"], "duracion": x.get("dur_recurso", 0.0)}
        clave = hashlib.sha1(repr((VERSION_CLIP, x["recurso"], x["tipo"], frames, x.get("offset"),
                                   w, h, p["encaje"], p["zoom"],
                                   x["i"] % 2 if x["tipo"] == "imagen" else 0)).encode()).hexdigest()[:16]
        destino = os.path.join(dir_clips, f"{clave}.mp4")
        clips.append(destino)
        if not os.path.exists(destino):
            trabajos.append((x, r, frames, destino))

    ctx.avisar(f"{len(planos)} planos: {len(planos) - len(trabajos)} clips reutilizados, "
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
    srt = ctx.dir(voz["srt"], crear=False) if p["subtitulos"] else ""
    rapido = p.get("acabado", "rapido") == "rapido" and acabado.tiene_libass(medios.ffmpeg())
    if p.get("acabado", "rapido") == "rapido" and not rapido:
        logger.warning("este ffmpeg no trae libass: se usa el acabado clasico (lento)")
    if rapido:
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
            "clips_nuevos": len(trabajos), "clips_reutilizados": len(planos) - len(trabajos),
            "tam_mb": round(os.path.getsize(final) / 1e6, 1)}


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
