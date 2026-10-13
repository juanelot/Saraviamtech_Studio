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
import json
import os
from concurrent.futures import ThreadPoolExecutor, as_completed

from loguru import logger

from app.models.schema import VideoAspect, VideoParams
from app.services import video as mpt_video
from app.services.estudio import acabado, edicion, medios
from app.services.estudio import voz as voz_mod
from app.utils import utils

DEFECTOS = {
    "aspecto": "16:9",
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
VERSION_CLIP = "4"   # v2: Ken Burns suave; v3: mas lento; v4: una sola direccion por plano (tambien en pausas)
PARALELO = 3
# Ken Burns: `zoom` es el TOPE por plano; ademas nunca mas rapido que ZOOM_VEL por
# segundo (4 s -> 3.2 %). Todas las piezas de un plano siguen el MISMO movimiento.
ZOOM_VEL = 0.008


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


def _clip_imagen(ruta, frames, w, h, encaje, zoom, acercar, destino, encuadre=1.0, extra="",
                 total=None, desde=0):
    """`total`/`desde`: frames del plano entero y donde empieza esta pieza, para
    que las piezas de un plano continuen el movimiento en vez de reiniciarlo."""
    ff = medios.ffmpeg()
    z = _z_lento(zoom, acercar, total or frames, desde, encuadre)
    if z:
        # Se encaja al doble de tamano y zoompan reescala: sin eso el zoom tiembla.
        filtro = (f"{_encaje(encaje, w * 2, h * 2)},zoompan=z='{z}':x='iw/2-(iw/zoom/2)':"
                  f"y='ih/2-(ih/zoom/2)':d={frames}:s={w}x{h}:fps={FPS}{extra},format=yuv420p")
        args = [ff, "-hide_banner", "-loglevel", "error", "-y", "-i", ruta,
                "-filter_complex", filtro] + _salida_x264(frames, destino)
    else:
        filtro = f"{_encaje(encaje, w, h)}{_cerrar(encuadre, w, h)}{extra},format=yuv420p"
        args = [ff, "-hide_banner", "-loglevel", "error", "-y", "-loop", "1", "-framerate", str(FPS),
                "-i", ruta, "-filter_complex", filtro] + _salida_x264(frames, destino)
    return args


def _z_lento(zoom, acercar, total, desde, encuadre=1.0):
    """Expresion de zoompan del Ken Burns del plano en el frame `desde`+on (None sin
    zoom). Encuadre > 1: subcorte de la edicion, mismo movimiento mas cerca."""
    zoom = min(zoom, ZOOM_VEL * total / FPS) if zoom else 0
    if zoom <= 0:
        return None
    z = (f"1+{zoom:.4f}*(on+{desde})/{total}" if acercar
         else f"{1 + zoom:.4f}-{zoom:.4f}*(on+{desde})/{total}")
    return f"{encuadre}*({z})" if encuadre != 1.0 else z


def _cerrar(encuadre, w, h):
    """Encuadre mas cerrado (recorta al centro y vuelve al tamano)."""
    if encuadre == 1.0:
        return ""
    return f",crop=trunc(iw/{encuadre}/2)*2:trunc(ih/{encuadre}/2)*2,scale={w}:{h},setsar=1"


def _clip_congelado(ruta, frames, w, h, encaje, offset, destino, encuadre=1.0, extra="", z=None):
    """Pausa dramatica: UN fotograma (del video en `offset`, o la imagen). En una
    imagen `z` sigue el MISMO movimiento lento del plano (sin reiniciarlo ni cambiar
    de sentido); un video se queda quieto."""
    z = z or f"{encuadre}"
    filtro = (f"trim=end_frame=1,{_encaje(encaje, w * 2, h * 2)},zoompan=z='{z}':x='iw/2-(iw/zoom/2)':"
              f"y='ih/2-(ih/zoom/2)':d={frames}:s={w}x{h}:fps={FPS}{extra},format=yuv420p")
    args = [medios.ffmpeg(), "-hide_banner", "-loglevel", "error", "-y"]
    if offset > 0:
        args += ["-ss", f"{offset:.3f}"]
    return args + ["-i", ruta, "-filter_complex", filtro] + _salida_x264(frames, destino)


def _clip_video(ruta, frames, w, h, encaje, offset, dur_recurso, destino, encuadre=1.0, extra="", sin_bucle=False):
    """Si el clip no alcanza se repite en bucle; con `sin_bucle` (escenas de un prompt
    maestro) se congela su ultimo fotograma en vez de volver a empezar."""
    necesita = frames / FPS
    bucle = dur_recurso and (offset + necesita) > dur_recurso + 0.05
    args = [medios.ffmpeg(), "-hide_banner", "-loglevel", "error", "-y"]
    if bucle and sin_bucle:
        extra += f",tpad=stop_mode=clone:stop_duration={necesita - max(0.0, dur_recurso - offset) + 0.5:.3f}"
    elif bucle:
        args += ["-stream_loop", "-1"]
    if offset > 0:
        args += ["-ss", f"{offset:.3f}"]
    filtro = f"{_encaje(encaje, w, h)}{_cerrar(encuadre, w, h)}{extra},fps={FPS},format=yuv420p"
    return args + ["-i", ruta, "-filter_complex", filtro] + _salida_x264(frames, destino)


def _acercar(pieza):
    """Direccion del zoom lento: la que fijo la edicion para todo el plano, o alterna."""
    return pieza["acercar"] if pieza.get("acercar") is not None else pieza["i"] % 2 == 0


def _en_plano(pieza):
    """(frames del plano entero, frame del plano donde empieza la pieza)."""
    a = float(pieza["inicio"]) - float(pieza.get("desde") or 0)
    b = float(pieza.get("fin_plano") or pieza["fin"])
    return max(1, round(b * FPS) - round(a * FPS)), round(float(pieza["inicio"]) * FPS) - round(a * FPS)


def _hacer_clip(plano, recurso, frames, w, h, p, destino):
    tmp = destino + ".tmp.mp4"
    encuadre = float(plano.get("encuadre") or 1.0)
    extra = ""
    if plano.get("pasado"):
        extra += "," + edicion.FILTRO_PASADO
    offset = float(plano.get("offset") or 0) + float(plano.get("desde") or 0)
    if plano.get("efecto") == "pausa":
        extra += "," + edicion.FILTRO_PAUSA
        z = _z_lento(float(p["zoom"] or 0), _acercar(plano), *_en_plano(plano), encuadre)             if plano["tipo"] == "imagen" else None
        args = _clip_congelado(recurso["ruta"], frames, w, h, p["encaje"],
                               offset if plano["tipo"] == "video" else 0, tmp, encuadre, extra, z)
    elif plano["tipo"] == "imagen":
        total, desde = _en_plano(plano)
        args = _clip_imagen(recurso["ruta"], frames, w, h, p["encaje"], float(p["zoom"] or 0),
                            _acercar(plano), tmp, encuadre, extra, total, desde)
    else:
        args = _clip_video(recurso["ruta"], frames, w, h, p["encaje"], offset,
                           float(recurso.get("duracion") or 0), tmp, encuadre, extra, bool(plano.get("sin_bucle")))
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
    # El video unido empieza en 0: si el primer plano arranca con la voz (p. ej. 0,9 s)
    # todo quedaria adelantado respecto a voz, subtitulos y flashes. Se ancla en 0.
    planos = [dict(x) for x in planos]
    planos[0]["inicio"] = 0.0
    w, h = VideoAspect(p["aspecto"]).to_resolution()
    dir_clips = ctx.dir("render", "clips")
    rapido = p.get("acabado", "rapido") == "rapido" and acabado.tiene_libass(medios.ffmpeg())
    sin_voz = bool(voz.get("sin_voz"))
    audio_clips = None
    if sin_voz:
        # La "voz" es la que traen los clips (p. ej. Flow): Whisper la transcribe, se
        # recortan los silencios de cada clip y la edicion trabaja sobre ese texto.
        ctx.avisar("sin voz: escuchando el audio de los clips", 1)
        planos, audio_clips, voz_clips = _voz_de_clips(ctx, planos, ctx.dir("render"))
        if voz_clips:
            voz = {**voz, **voz_clips}
    elif ctx.params_de("escenas").get("fijas") and ctx.params_de("asignacion").get("modo") == "escenas":
        # Prompt maestro con narracion: cada escena dura lo que su clip y la voz se acomoda.
        ctx.avisar("ajustando la voz a la duracion de cada clip", 1)
        planos, voz = _voz_a_clips(ctx, planos, voz, ctx.dir("render"))
    editorial = rapido and edicion.activa(p) and (not sin_voz or bool(voz.get("palabras")))

    # Editorial: Claude marca antes de los clips (las revelaciones deciden los
    # subcortes) y los planos se parten en piezas. Si no, una pieza por plano.
    piezas = [{**x, "encuadre": 1.0, "desde": 0.0, "pieza": 0, "efecto": None, "pasado": False} for x in planos]
    if editorial:
        ctx.avisar(f"{edicion.nombre(p)}: marcas de Claude", 1)
        lineas, marcas_ = edicion.lineas_y_marcas(ctx, voz, p)
        piezas = edicion.subcortes(planos, lineas, marcas_, edicion.opciones(p))
        if sin_voz:  # congelar la imagen desfasaria la voz del propio clip
            piezas = [{**x, "efecto": None} if x["efecto"] == "pausa" else x for x in piezas]

    trabajos, clips = [], []
    for x in piezas:
        frames = max(1, round(x["fin"] * FPS) - round(x["inicio"] * FPS))
        if not os.path.exists(x["ruta"]):
            raise FileNotFoundError(f"plano {x['i']}: el recurso {x['nombre']} ya no esta en disco")
        r = {"ruta": x["ruta"], "nombre": x["nombre"], "duracion": x.get("dur_recurso", 0.0)}
        base = (VERSION_CLIP, x["recurso"], x["tipo"], frames, x.get("offset"), w, h, p["encaje"], p["zoom"],
                (_acercar(x),) + _en_plano(x) if x["tipo"] == "imagen" else 0)
        if x.get("sin_bucle"):
            base += ("sin_bucle",)
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
    srt = ctx.dir(voz["srt"], crear=False) if p["subtitulos"] and (not sin_voz or voz.get("palabras")) else ""
    if sin_voz:
        audio = audio_clips
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


def _voz_de_clips(ctx, planos, carpeta):
    """Sin narracion propia: transcribe el sonido de los clips con Whisper para los
    subtitulos y la edicion. Los clips se usan ENTEROS (la accion sigue despues de
    hablar: no se recorta nada), pero nunca mas alla de su final (eso seria repetirlo
    en bucle). Devuelve (planos, audio, voz para la edicion); la voz es None si los
    clips no tienen habla (ASMR, musica): se unen tal cual."""
    audio = _audio_de_clips(planos, carpeta)
    idioma = str(ctx.params_de("guion").get("idioma") or "").split("-")[0] or None
    try:
        segmentos, _info = voz_mod._modelo_whisper().transcribe(
            audio, word_timestamps=True, vad_filter=True, beam_size=1, language=idioma)
        oidas = []
        for s in segmentos:
            for w in s.words or []:
                trozos = w.word.split()
                paso = (float(w.end) - float(w.start)) / max(1, len(trozos))
                oidas += [(float(w.start) + k * paso, float(w.start) + (k + 1) * paso, t)
                          for k, t in enumerate(trozos)]
    except Exception as e:  # noqa: BLE001 -- sin transcripcion el video sale igual, sin edicion
        logger.warning(f"sin voz: Whisper fallo ({e}); se unen los clips tal cual")
        return planos, audio, None
    if not oidas:
        ctx.avisar("sin voz: los clips no tienen habla, se unen tal cual", 2)
        return planos, audio, None

    nuevos, palabras, cursor = [], [], 0.0
    for x in planos:
        a, b = float(x["inicio"]), float(x["fin"])
        suyas = [w for w in oidas if a <= (w[0] + w[1]) / 2 < b]
        dur_rec = float(x.get("dur_recurso") or 0)
        if x["tipo"] == "video" and dur_rec:  # nunca mas alla del clip (lo que siga seria su bucle)
            b = min(b, a + max(0.5, dur_rec - float(x.get("offset") or 0)))
            suyas = [w for w in suyas if w[1] <= b + 0.1]
        na, nb = a, b
        corrimiento = cursor - na
        palabras += [[round(max(cursor, s + corrimiento), 3), round(min(cursor + nb - na, e + corrimiento), 3), t]
                     for s, e, t in suyas]
        nuevos.append({**x, "inicio": round(cursor, 3), "fin": round(cursor + nb - na, 3),
                       "offset": round(float(x.get("offset") or 0) + (na - a), 3)})
        cursor += nb - na
    recortado = round(float(planos[-1]["fin"]) - cursor, 1)
    if recortado > 0.05:
        audio = _audio_de_clips(nuevos, carpeta)

    srt = os.path.join(carpeta, "voz_clips.srt")
    ruta_palabras = os.path.join(carpeta, "palabras_clips.json")
    with open(ruta_palabras, "w", encoding="utf-8") as f:
        json.dump(palabras, f, ensure_ascii=False)
    if not voz_mod.srt_de_palabras(" ".join(t for _a, _b, t in palabras), palabras, srt):
        logger.warning("sin voz: no se pudo armar el SRT de la transcripcion")
        return nuevos, audio, None
    ctx.avisar(f"sin voz: {len(palabras)} palabras oidas, clips enteros"
               + (f" ({recortado:g}s que pasaban del final de los clips)" if recortado > 0.05 else ""), 3)
    return nuevos, audio, {"srt": "render/voz_clips.srt", "palabras": "render/palabras_clips.json",
                           "duracion": round(cursor, 3), "sin_voz": True}


VELOCIDAD_MAX = 1.15  # cuanto se puede acelerar la voz de una escena para caber en su clip
ENTRADA_S = 0.15      # la voz entra un instante despues del corte
COLA_S = 0.25         # y deja un respiro antes del siguiente


def _voz_a_clips(ctx, planos, voz, carpeta):
    """Escenas de un prompt maestro CON narracion: la voz se genero de corrido y las
    escenas se repartieron por sus palabras, asi que una escena podia durar mas que
    su clip (y el clip volvia a empezar) o menos (y se cortaba). Aqui cada escena dura
    lo que su clip y su trozo de voz se coloca al principio; si no cabe se acelera un
    poco (hasta VELOCIDAD_MAX) y, si aun asi no cabe, la escena se alarga congelando el
    ultimo fotograma (nunca se repite el clip). Devuelve (planos, voz) con el audio,
    el SRT y las palabras nuevos en render/."""
    origen = ctx.dir(voz["audio"], crear=False)
    ruta_pal = ctx.dir(voz.get("palabras") or "voz/palabras.json", crear=False)
    palabras = []
    if os.path.isfile(ruta_pal):
        with open(ruta_pal, encoding="utf-8") as f:
            palabras = [tuple(x) for x in json.load(f)]
    lineas = acabado.lineas_srt(ctx.dir(voz["srt"], crear=False)) if voz.get("srt") else []

    trozos_dir = os.path.join(carpeta, "voz_escenas")
    os.makedirs(trozos_dir, exist_ok=True)
    ff = medios.ffmpeg()
    nuevos, tramos, trozos, cursor, congelados = [], [], [], 0.0, 0
    for x in planos:
        a, b = float(x["inicio"]), float(x["fin"])
        suyas = [w for w in palabras if a <= (w[0] + w[1]) / 2 < b]
        s0 = max(a, suyas[0][0] - 0.05) if suyas else a
        s1 = min(b, suyas[-1][1] + 0.1) if suyas else b
        habla = max(0.05, s1 - s0)
        dur_rec = float(x.get("dur_recurso") or 0)
        if x["tipo"] == "video" and dur_rec:
            caben = max(0.5, dur_rec - float(x.get("offset") or 0))
        else:
            caben = b - a
        hace_falta = ENTRADA_S + habla + COLA_S
        vel = 1.0 if hace_falta <= caben else min(VELOCIDAD_MAX, habla / max(0.1, caben - ENTRADA_S - COLA_S))
        dur = max(caben, ENTRADA_S + habla / vel + COLA_S)
        congelados += x["tipo"] == "video" and dur > caben + 0.05
        frames = max(1, round(dur * FPS))
        dur = frames / FPS
        destino = os.path.join(trozos_dir, f"{x['i']:04d}.wav")
        filtro = (f"atempo={vel:.4f}," if vel > 1.001 else "") + f"adelay={int(ENTRADA_S * 1000)}:all=1,apad"
        r = medios.correr([ff, "-hide_banner", "-loglevel", "error", "-y", "-ss", f"{s0:.3f}", "-t", f"{habla:.3f}",
                           "-i", origen, "-af", filtro, "-t", f"{dur:.3f}", "-ar", "44100", "-ac", "2",
                           "-c:a", "pcm_s16le", destino], timeout=300)
        if r.returncode != 0:
            raise RuntimeError(f"no se pudo colocar la voz de la escena {x['i'] + 1}: {r.stderr[-300:]}")
        trozos.append(destino)
        tramos.append((a, b, s0, vel, cursor))
        nuevos.append({**x, "inicio": round(cursor, 3), "fin": round(cursor + dur, 3), "sin_bucle": True})
        cursor += dur

    def mover(t):
        """Tiempo de la voz original -> tiempo en el video ajustado."""
        for a, b, s0, vel, ini in tramos:
            if t < b or (a, b) == tramos[-1][:2]:
                return round(ini + ENTRADA_S + max(0.0, t - s0) / vel, 3)
        return round(t, 3)

    audio = os.path.join(carpeta, "voz_escenas.wav")
    lista = audio + ".txt"
    with open(lista, "w", encoding="utf-8") as f:
        for t in trozos:
            f.write("file '" + t.replace("\\", "/") + "'\n")
    r = medios.correr([ff, "-hide_banner", "-loglevel", "error", "-y", "-f", "concat", "-safe", "0",
                       "-i", lista, "-c", "copy", audio], timeout=600)
    os.remove(lista)
    for t in trozos:
        os.remove(t)
    if r.returncode != 0:
        raise RuntimeError(f"no se pudo unir la voz de las escenas: {r.stderr[-300:]}")

    with open(os.path.join(carpeta, "palabras_escenas.json"), "w", encoding="utf-8") as f:
        json.dump([[mover(s), max(mover(s), mover(e)), t] for s, e, t in palabras], f, ensure_ascii=False)
    with open(os.path.join(carpeta, "voz_escenas.srt"), "w", encoding="utf-8") as f:
        f.write("\n".join(utils.text_to_srt(n, t, mover(s), max(mover(s) + 0.2, mover(e)))
                          for n, (s, e, t) in enumerate(lineas, start=1)) + "\n")
    ctx.avisar(f"voz ajustada a {len(nuevos)} clips ({cursor:.1f}s)"
               + (f"; {congelados} escenas alargadas congelando el ultimo fotograma" if congelados else ""), 3)
    return nuevos, {**voz, "audio": "render/voz_escenas.wav", "srt": "render/voz_escenas.srt",
                    "palabras": "render/palabras_escenas.json", "duracion": round(cursor, 3)}


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
