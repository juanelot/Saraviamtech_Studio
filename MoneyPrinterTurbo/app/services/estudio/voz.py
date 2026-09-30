"""
Etapa VOZ: sintetiza el guion con el TTS de MoneyPrinterTurbo y lo corta en
PLANOS usando los tiempos de ESA voz (igual que el modo local/Zenn), asi el
cambio de imagen cae justo donde cambia la narracion.

Planos: se fusionan los trozos mas cortos que `plano_min_s` y se parten los mas
largos que `plano_max_s`, para que ningun recurso se quede demasiado en pantalla.
"""
import json
import math
import os

from app.config import config
from app.services import subtitle, voice
from app.services.estudio import medios, voz_clonada
from app.services.image_task import merge_short_segments, parse_segments
from app.utils import utils

DEFECTOS = {
    "voz": "es-ES-AlvaroNeural-Male",
    "velocidad": 1.0,
    "plano_min_s": 2.5,
    "plano_max_s": 6.0,
}


def partir_largos(segmentos, maximo):
    salida = []
    for inicio, fin, texto in segmentos:
        dur = fin - inicio
        n = max(1, math.ceil(dur / maximo - 1e-6))
        if n == 1:
            salida.append((inicio, fin, texto))
            continue
        palabras = texto.split()
        paso = dur / n
        for k in range(n):
            a = round(k * len(palabras) / n)
            b = round((k + 1) * len(palabras) / n)
            trozo = " ".join(palabras[a:b]) or texto
            salida.append((inicio + k * paso, inicio + (k + 1) * paso if k < n - 1 else fin, trozo))
    return salida


def ejecutar(ctx):
    p = ctx.params
    texto = (ctx.salidas["guion"] or {}).get("texto", "").strip()
    if not texto:
        raise ValueError("no hay guion")
    carpeta = ctx.dir("voz")
    audio = os.path.join(carpeta, "voz.mp3")
    srt = os.path.join(carpeta, "subtitulos.srt")
    for f in (audio, srt, os.path.join(carpeta, "palabras.json")):
        if os.path.exists(f):
            os.remove(f)

    if str(p["voz"]).startswith("clon:"):
        duracion = _voz_clonada(ctx, texto, audio, srt)
    else:
        duracion = _voz_tts(ctx, texto, audio, srt)
    crudos = parse_segments(srt)
    if not crudos:
        raise RuntimeError("no salieron tiempos de la voz (SRT vacio)")

    planos = merge_short_segments(crudos, float(p["plano_min_s"]), duracion)
    planos = partir_largos(planos, max(float(p["plano_max_s"]), float(p["plano_min_s"]) + 0.5))
    segmentos = [{"i": i, "inicio": round(a, 3), "fin": round(b, 3), "texto": t}
                 for i, (a, b, t) in enumerate(planos)]
    with open(os.path.join(carpeta, "planos.json"), "w", encoding="utf-8") as f:
        json.dump(segmentos, f, ensure_ascii=False, indent=1)
    ctx.avisar(f"voz lista: {duracion:.1f}s, {len(segmentos)} planos", 100)
    return {"audio": "voz/voz.mp3", "srt": "voz/subtitulos.srt",
            "duracion": round(duracion, 3), "planos": segmentos}


def _voz_tts(ctx, texto, audio, srt):
    """Voces de Microsoft (y demas TTS de MPT): dan el tiempo de cada palabra."""
    p = ctx.params
    ctx.avisar(f"sintetizando voz {p['voz']}", 10)
    sub_maker = voice.tts(
        text=texto,
        voice_name=voice.parse_voice_name(p["voz"]),
        voice_rate=float(p["velocidad"]),
        voice_file=audio,
        voice_volume=1.0,  # el volumen se aplica en render (no obliga a re-sintetizar)
    )
    if sub_maker is None or not os.path.exists(audio):
        raise RuntimeError("el TTS no genero audio: revisa que la voz coincida con el idioma del guion y la conexion")
    duracion = float(voice.get_audio_duration(sub_maker) or 0)
    if duracion <= 0:
        raise RuntimeError("no se pudo medir la duracion del audio")

    _guardar_palabras(sub_maker, os.path.join(ctx.dir("voz"), "palabras.json"))
    ctx.avisar("calculando tiempos de cada frase", 70)
    if config.app.get("subtitle_provider", "edge").strip().lower() == "edge":
        voice.create_subtitle(text=texto, sub_maker=sub_maker, subtitle_file=srt)
    if not os.path.exists(srt):
        subtitle.create(audio_file=audio, subtitle_file=srt)
        subtitle.correct(subtitle_file=srt, video_script=texto)
    return duracion


def _guardar_palabras(sub_maker, destino):
    """Tiempos de CADA palabra (los da edge-tts con WordBoundary): los usa la
    edicion editorial para los subtitulos palabra a palabra. Si el TTS solo da
    frases, no se guarda nada y la edicion reparte los tiempos por frase."""
    palabras = []
    try:
        if getattr(sub_maker, "cues", None):
            palabras = [[round(c.start.total_seconds(), 3), round(c.end.total_seconds(), 3), str(c.content)]
                        for c in sub_maker.cues]
        elif getattr(sub_maker, "subs", None) and len(sub_maker.subs) == len(getattr(sub_maker, "offset", [])):
            palabras = [[round(a / 1e7, 3), round(b / 1e7, 3), str(t)]
                        for t, (a, b) in zip(sub_maker.subs, sub_maker.offset)]
    except Exception:  # noqa: BLE001
        palabras = []
    if palabras and all(len(t.split()) == 1 for _a, _b, t in palabras):
        with open(destino, "w", encoding="utf-8") as f:
            json.dump(palabras, f, ensure_ascii=False)


def _voz_clonada(ctx, texto, audio, srt):
    """Servidor Clonar-voz externo: bloques cacheados + tiempos por bloque."""
    p = ctx.params
    vid = str(p["voz"])[len("clon:"):]
    idioma = str(ctx.params_de("guion").get("idioma") or "es").split("-")[0]
    wav = os.path.join(ctx.dir("voz"), "clon.wav")
    segmentos = voz_clonada.sintetizar(ctx, texto, vid, idioma, wav)

    ctx.avisar("convirtiendo la narracion", 70)
    vel = min(2.0, max(0.5, float(p["velocidad"] or 1.0)))
    args = [medios.ffmpeg(), "-hide_banner", "-loglevel", "error", "-y", "-i", wav]
    if abs(vel - 1.0) > 1e-3:
        args += ["-filter:a", f"atempo={vel}"]
    r = medios.correr(args + ["-c:a", "libmp3lame", "-q:a", "2", audio], timeout=1800)
    if r.returncode != 0 or not os.path.exists(audio):
        raise RuntimeError(f"ffmpeg no pudo convertir la voz clonada: {r.stderr[-300:]}")
    os.remove(wav)
    duracion = float(medios.sondear(audio).get("duracion") or 0)
    if duracion <= 0:
        raise RuntimeError("no se pudo medir la duracion de la voz clonada")

    lineas = [utils.text_to_srt(i, t, a / vel, min(b / vel, duracion))
              for i, (a, b, t) in enumerate(segmentos, start=1)]
    with open(srt, "w", encoding="utf-8") as f:
        f.write("\n".join(lineas) + "\n")
    return duracion
