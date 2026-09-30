"""
Voz clonada a traves de un servidor externo "Clonar-voz"
(github.com/jceronch1/Clonar-voz: Qwen3-TTS + llama.cpp, CPU o GPU).

El servidor puede estar en otra maquina (un PC con GPU, otro VPS): el Estudio
solo necesita su URL en config.toml -> `estudio_voz_clonada_url`
(admite usuario:clave@ en la URL si va detras de un proxy con auth basica).

Tiempos: la voz clonada no da el tiempo de cada palabra como Microsoft, asi que
el guion se pide por BLOQUES (unas pocas frases). La duracion de cada bloque es
exacta; dentro del bloque las frases se reparten por numero de caracteres.

Cada bloque se guarda en cache por (texto, voz, idioma): cambiar la velocidad o
los planos, o reintentar tras un fallo, no vuelve a sintetizar lo que ya existe.
"""
import hashlib
import json
import os
import re
import time
import wave

import requests

from app.config import config

CHARS_POR_BLOQUE = 240
PAUSA_S = 0.25          # silencio entre bloques
ESPERA_BLOQUE_S = 1800  # un bloque en CPU lenta puede tardar varios minutos
PATRON_VOZ = re.compile(r"^[A-Za-z0-9_-]{1,64}$")
IDIOMAS = {"es", "en", "zh", "de", "it", "pt", "ja", "ko", "fr", "ru"}


class NoConfigurado(RuntimeError):
    pass


def url_base():
    return (config.app.get("estudio_voz_clonada_url", "") or "").strip().rstrip("/")


def _url(ruta):
    base = url_base()
    if not base:
        raise NoConfigurado("no hay servidor de voz clonada (config.toml: estudio_voz_clonada_url)")
    return base + ruta


def _error(r):
    try:
        return r.json().get("detail") or r.text[:200]
    except ValueError:
        return r.text[:200]


# ------------------------------------------------------------------ biblioteca

def listar_voces():
    r = requests.get(_url("/api/voces"), timeout=10)
    r.raise_for_status()
    return [{"id": v.get("id"), "nombre": v.get("nombre") or v.get("id"),
             "duracion": v.get("duracion"), "transcripcion": v.get("transcripcion", "")}
            for v in r.json() if v.get("id")]


def crear_voz(nombre, datos, nombre_archivo, transcripcion=""):
    r = requests.post(_url("/api/voces"), timeout=120,
                      data={"nombre": nombre, "transcripcion": transcripcion},
                      files={"audio": (nombre_archivo or "voz.wav", datos)})
    if not r.ok:
        raise RuntimeError(_error(r))
    return r.json()


def audio_voz(vid):
    if not PATRON_VOZ.match(vid or ""):
        raise ValueError("voz invalida")
    r = requests.get(_url(f"/api/voces/{vid}/audio"), timeout=30)
    r.raise_for_status()
    return r.content


# ------------------------------------------------------------------ texto

def trocear(texto, maximo=CHARS_POR_BLOQUE):
    """Bloques de frases completas de hasta `maximo` caracteres."""
    texto = re.sub(r"\s+", " ", texto).strip()
    bloques, actual = [], ""
    for frase in re.split(r"(?<=[.!?…;:])\s+", texto):
        while len(frase) > maximo:
            corte = max(frase.rfind(",", 0, maximo), frase.rfind(" ", 0, maximo))
            if corte <= maximo // 2:
                corte = maximo
            if actual:
                bloques.append(actual)
                actual = ""
            bloques.append(frase[:corte + 1].strip())
            frase = frase[corte + 1:].strip()
        if actual and len(actual) + len(frase) + 1 > maximo:
            bloques.append(actual)
            actual = frase
        else:
            actual = f"{actual} {frase}".strip()
    if actual:
        bloques.append(actual)
    return [b for b in bloques if b]


def frases(bloque):
    """Trozos de subtitulo: se corta en puntuacion, sin dejar trozos minimos."""
    trozos = [t.strip() for t in re.split(r"(?<=[,.!?…;:])\s+", bloque) if t.strip()]
    salida = []
    for t in trozos:
        if salida and (len(t) < 12 or len(salida[-1]) < 12):
            salida[-1] = f"{salida[-1]} {t}"
        else:
            salida.append(t)
    return salida or [bloque]


def _peso(t):
    # Las pausas de fin de frase ocupan tiempo aunque no tengan letras.
    return len(t) + (6 if re.search(r"[.!?…]$", t) else 3 if re.search(r"[,;:]$", t) else 0)


# ------------------------------------------------------------------ sintesis

def _sintetizar_bloque(texto, voz, idioma, destino, ctx):
    r = requests.post(_url("/api/generar"), timeout=60, json={
        "texto": texto, "voz": voz, "idioma": idioma,
        "chars_por_bloque": CHARS_POR_BLOQUE * 4,  # ya va troceado: que no lo parta
    })
    if not r.ok:
        raise RuntimeError(f"servidor de voz clonada: {_error(r)}")
    tarea = r.json()
    tid, archivo = tarea["id"], tarea["archivo"]
    limite = time.time() + ESPERA_BLOQUE_S
    terminado = False
    try:
        with requests.get(_url(f"/api/tarea/{tid}/eventos"), stream=True, timeout=(10, 300)) as sse:
            for linea in sse.iter_lines(decode_unicode=True):
                if ctx.cancelado():
                    requests.post(_url(f"/api/tarea/{tid}/cancelar"), timeout=10)
                    ctx.avisar()  # lanza Cancelado
                if not linea or not linea.startswith("data:"):
                    continue
                ev = json.loads(linea[5:])
                if ev.get("tipo") == "error":
                    raise RuntimeError(f"servidor de voz clonada: {ev.get('mensaje')}")
                if ev.get("tipo") == "cancelada":
                    raise RuntimeError("el servidor de voz clonada cancelo la tarea")
                if ev.get("tipo") == "fin":
                    terminado = True
                    break
    except requests.RequestException:
        pass  # se corto el aviso en vivo: se espera al archivo
    while True:
        a = requests.get(_url(f"/api/salidas/{archivo}"), timeout=120)
        if a.ok:
            break
        if terminado or time.time() > limite:
            raise RuntimeError("el servidor de voz clonada no entrego el audio")
        ctx.avisar()
        time.sleep(5)
    tmp = destino + ".part"
    with open(tmp, "wb") as f:
        f.write(a.content)
    os.replace(tmp, destino)
    try:
        requests.delete(_url(f"/api/salidas/{archivo}"), timeout=10)
    except requests.RequestException:
        pass


def _duracion(ruta):
    with wave.open(ruta, "rb") as w:
        return w.getnframes() / float(w.getframerate())


def _unir(partes, destino):
    """Une WAV del mismo formato con un silencio corto entre medias."""
    with wave.open(partes[0], "rb") as w:
        formato = w.getparams()
    silencio = b"\x00" * int(formato.framerate * PAUSA_S) * formato.sampwidth * formato.nchannels
    with wave.open(destino, "wb") as out:
        out.setparams(formato)
        for k, p in enumerate(partes):
            with wave.open(p, "rb") as w:
                if (w.getframerate(), w.getsampwidth(), w.getnchannels()) != (
                        formato.framerate, formato.sampwidth, formato.nchannels):
                    raise RuntimeError("los bloques de voz clonada no tienen el mismo formato")
                out.writeframes(w.readframes(w.getnframes()))
            if k < len(partes) - 1:
                out.writeframes(silencio)


def sintetizar(ctx, texto, voz, idioma, destino_wav):
    """Genera la narracion completa en `destino_wav` y devuelve los segmentos
    [(inicio, fin, texto)] a velocidad 1.0."""
    if not PATRON_VOZ.match(voz or ""):
        raise ValueError("voz clonada invalida")
    idioma = idioma if idioma in IDIOMAS else "es"
    cache = ctx.dir("voz", "clon")
    bloques = trocear(texto)
    if not bloques:
        raise ValueError("no hay texto que sintetizar")

    rutas, usadas = [], set()
    for i, b in enumerate(bloques, start=1):
        clave = hashlib.sha256(f"{voz}|{idioma}|{b}".encode("utf-8")).hexdigest()[:20]
        ruta = os.path.join(cache, f"{clave}.wav")
        usadas.add(os.path.basename(ruta))
        if os.path.exists(ruta):
            ctx.avisar(f"voz clonada: bloque {i}/{len(bloques)} (ya estaba)", 5 + 60 * i / len(bloques))
        else:
            ctx.avisar(f"voz clonada: sintetizando bloque {i}/{len(bloques)}", 5 + 60 * (i - 1) / len(bloques))
            _sintetizar_bloque(b, voz, idioma, ruta, ctx)
        rutas.append(ruta)

    for f in os.listdir(cache):  # bloques de versiones anteriores del guion
        if f not in usadas:
            try:
                os.remove(os.path.join(cache, f))
            except OSError:
                pass

    _unir(rutas, destino_wav)

    segmentos, t = [], 0.0
    for b, ruta in zip(bloques, rutas):
        dur = _duracion(ruta)
        trozos = frases(b)
        total = sum(_peso(x) for x in trozos) or 1
        cursor = t
        for x in trozos:
            d = dur * _peso(x) / total
            segmentos.append((cursor, cursor + d, x))
            cursor += d
        t += dur + PAUSA_S
    return segmentos
