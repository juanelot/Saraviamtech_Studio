"""
Datos para el editor de la linea de tiempo (paso Ajuste): las palabras de la voz
con sus tiempos (para cortar entre palabras y para los subtitulos de la vista
previa) y la forma de onda ya reducida, para no decodificar el audio entero en
el navegador. La forma de onda se cachea junto a la voz con la huella del audio.
"""
import json
import os
import subprocess

import numpy as np

from app.services.estudio import acabado, almacen, grafo, medios

PICOS_POR_S = 50


def _picos(audio, destino):
    """Un valor 0-255 por cada 1/PICOS_POR_S s: el pico de ese tramo."""
    huella = f"{os.path.getsize(audio)}:{int(os.path.getmtime(audio))}"
    cache = almacen.leer_json(destino, {}) or {}
    if cache.get("huella") == huella:
        return cache["picos"]
    tasa = 4000
    r = subprocess.run([medios.ffmpeg(), "-hide_banner", "-loglevel", "error", "-i", audio, "-ac", "1",
                        "-ar", str(tasa), "-f", "s16le", "-"], capture_output=True, timeout=300, **medios.SIN_VENTANA)
    muestras = np.abs(np.frombuffer(r.stdout or b"", dtype=np.int16).astype(np.int32))
    paso = tasa // PICOS_POR_S
    n = len(muestras) // paso
    if not n:
        return []
    picos = muestras[:n * paso].reshape(n, paso).max(axis=1)
    tope = max(1, int(np.percentile(picos, 99)))
    picos = np.clip(picos * 255 // tope, 0, 255).astype(int).tolist()
    almacen.escribir_json(destino, {"huella": huella, "picos": picos})
    return picos


def datos(pid):
    _, _, etapas = grafo.evaluar(pid)
    voz = etapas["voz"]["salida"] or {}
    base = almacen.dir_proyecto(pid)
    palabras = []
    ruta = os.path.join(base, voz.get("palabras") or "voz/palabras.json")
    if os.path.isfile(ruta):
        with open(ruta, encoding="utf-8") as f:
            palabras = [[round(float(a), 3), round(float(b), 3), str(t)] for a, b, t in json.load(f)]
    srt = os.path.join(base, voz["srt"]) if voz.get("srt") else ""
    lineas = [[round(a, 3), round(b, 3), t] for a, b, t in acabado.lineas_srt(srt)] if srt and os.path.isfile(srt) else []
    audio = os.path.join(base, voz["audio"]) if voz.get("audio") else ""
    picos = _picos(audio, os.path.join(base, "voz", "picos.json")) if audio and os.path.isfile(audio) else []
    return {"audio": voz.get("audio") if picos else None, "duracion": float(voz.get("duracion") or 0),
            "sin_voz": bool(voz.get("sin_voz")), "palabras": palabras, "lineas": lineas,
            "picos": picos, "picos_por_s": PICOS_POR_S}
