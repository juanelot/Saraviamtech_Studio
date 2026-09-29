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
from app.services.image_task import merge_short_segments, parse_segments

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
    for f in (audio, srt):
        if os.path.exists(f):
            os.remove(f)

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

    ctx.avisar("calculando tiempos de cada frase", 70)
    if config.app.get("subtitle_provider", "edge").strip().lower() == "edge":
        voice.create_subtitle(text=texto, sub_maker=sub_maker, subtitle_file=srt)
    if not os.path.exists(srt):
        subtitle.create(audio_file=audio, subtitle_file=srt)
        subtitle.correct(subtitle_file=srt, video_script=texto)
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
