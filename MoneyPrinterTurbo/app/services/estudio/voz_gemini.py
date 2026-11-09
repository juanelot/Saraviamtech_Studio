"""
Voz de Gemini (Google AI Studio) para la Fabrica: mas natural que la de Microsoft.

- Va por la API REST de Gemini con la clave de AI Studio (Configuracion > Voz de Gemini). La clave gratis tiene
  un cupo diario de peticiones: cada trozo de texto es una peticion.
- Gemini no da el tiempo de cada palabra: la Fabrica lo saca despues con Whisper (como con una grabacion).
- Las voces hablan cualquier idioma (lo detectan del texto). La velocidad se ajusta con ffmpeg (atempo).

Voz en las opciones: "gemini:<Nombre>" (p. ej. "gemini:Kore").
"""
import base64
import os
import re
import tempfile
import wave

import requests

from app.config import config
from app.services.estudio import almacen, medios

PREFIJO = "gemini:"
MODELO_DEFECTO = "gemini-2.5-flash-preview-tts"
URL = "https://generativelanguage.googleapis.com/v1beta/models/{modelo}:generateContent"
TROZO_MAX = 1500          # letras por peticion (frases enteras)
TASA = 24000              # Gemini devuelve PCM de 16 bits, mono, 24 kHz

# Las 30 voces de Gemini TTS: (nombre, genero, como suena)
VOCES = [
    ("Zephyr", "Female", "brillante"), ("Puck", "Male", "animada"), ("Charon", "Male", "informativa"),
    ("Kore", "Female", "firme"), ("Fenrir", "Male", "entusiasta"), ("Leda", "Female", "juvenil"),
    ("Orus", "Male", "firme"), ("Aoede", "Female", "ligera"), ("Callirrhoe", "Female", "tranquila"),
    ("Autonoe", "Female", "brillante"), ("Enceladus", "Male", "susurrante"), ("Iapetus", "Male", "clara"),
    ("Umbriel", "Male", "tranquila"), ("Algieba", "Male", "suave"), ("Despina", "Female", "suave"),
    ("Erinome", "Female", "clara"), ("Algenib", "Male", "grave"), ("Rasalgethi", "Male", "informativa"),
    ("Laomedeia", "Female", "animada"), ("Achernar", "Female", "suave"), ("Alnilam", "Male", "firme"),
    ("Schedar", "Male", "pareja"), ("Gacrux", "Female", "madura"), ("Pulcherrima", "Female", "decidida"),
    ("Achird", "Male", "cercana"), ("Zubenelgenubi", "Male", "casual"), ("Vindemiatrix", "Female", "amable"),
    ("Sadachbia", "Male", "viva"), ("Sadaltager", "Male", "experta"), ("Sulafat", "Female", "calida"),
]
NOMBRES = {n for n, _, _ in VOCES}


class ErrorGemini(RuntimeError):
    pass


def clave():
    return str(config.app.get("gemini_api_key") or "").strip()


def disponible():
    return bool(clave())


def es_gemini(voz):
    return str(voz or "").startswith(PREFIJO)


def nombre(voz):
    """"gemini:Kore" (o el formato viejo "gemini:Kore-Female") -> "Kore"."""
    n = str(voz or "")[len(PREFIJO):].split("-")[0]
    return n if n in NOMBRES else "Kore"


def listar():
    return [{"value": PREFIJO + n, "label": f"{n} ({'mujer' if g == 'Female' else 'hombre'}, {d})", "gender": g}
            for n, g, d in VOCES]


MUESTRAS = {
    "espanol": "Hola, soy {n}. Asi sonaria la narracion de tu proximo video: clara, cercana y con ritmo.",
    "ingles": "Hi, I'm {n}. This is how the narration of your next video would sound: clear, warm and with rhythm.",
    "portugues": "Ola, eu sou {n}. Assim soaria a narracao do seu proximo video: clara, proxima e com ritmo.",
}


def muestra(voz, idioma="espanol"):
    """Unos segundos de esa voz para elegirla. Se hace una vez por voz e idioma y queda guardada (no gasta cupo otra vez)."""
    n = nombre(voz)
    idioma = idioma if idioma in MUESTRAS else "espanol"
    ruta = almacen.raiz("voces_gemini", f"{n}_{idioma}.mp3")
    if not os.path.isfile(ruta):
        os.makedirs(os.path.dirname(ruta), exist_ok=True)
        sintetizar(MUESTRAS[idioma].format(n=n), PREFIJO + n, ruta)
    return ruta


def _trozos(texto):
    """Frases enteras juntas hasta TROZO_MAX letras (una peticion cada trozo)."""
    frases = re.split(r"(?<=[.?!…])\s+", str(texto or "").strip())
    trozos, actual = [], ""
    for f in frases:
        if actual and len(actual) + len(f) + 1 > TROZO_MAX:
            trozos.append(actual)
            actual = f
        else:
            actual = f"{actual} {f}".strip()
    if actual:
        trozos.append(actual)
    return trozos


def _pedir(texto, voz):
    modelo = str(config.app.get("gemini_tts_model") or MODELO_DEFECTO)
    cuerpo = {"contents": [{"parts": [{"text": texto}]}],
              "generationConfig": {"responseModalities": ["AUDIO"],
                                   "speechConfig": {"voiceConfig": {"prebuiltVoiceConfig": {"voiceName": voz}}}}}
    try:
        r = requests.post(URL.format(modelo=modelo), json=cuerpo, timeout=180,
                          headers={"x-goog-api-key": clave(), "Content-Type": "application/json"})
    except requests.RequestException as e:
        raise ErrorGemini(f"no se pudo hablar con Gemini: {e}") from e
    if r.status_code == 429:
        raise ErrorGemini("Gemini: se acabo el cupo gratis de voz por hoy (o vas muy rapido). Prueba mas tarde o usa la voz de Microsoft")
    if r.status_code in (400, 401, 403):
        detalle = ""
        try:
            detalle = r.json().get("error", {}).get("message", "")
        except ValueError:
            pass
        if "API key" in detalle or r.status_code in (401, 403):
            raise ErrorGemini("Gemini no acepta la clave: revisala en Configuracion > Voz de Gemini")
        raise ErrorGemini(f"Gemini rechazo el texto: {detalle[:200]}")
    if r.status_code != 200:
        raise ErrorGemini(f"Gemini respondio {r.status_code}: {r.text[:200]}")
    try:
        partes = r.json()["candidates"][0]["content"]["parts"]
        datos = next(p["inlineData"]["data"] for p in partes if p.get("inlineData"))
    except (KeyError, IndexError, StopIteration, ValueError) as e:
        raise ErrorGemini("Gemini no devolvio audio (prueba otra voz o vuelve a intentarlo)") from e
    return base64.b64decode(datos)


def sintetizar(texto, voz, salida, velocidad=1.0, avisar=lambda n, total: None):
    """Narra `texto` con la voz de Gemini y lo deja en `salida` (mp3)."""
    if not disponible():
        raise ErrorGemini("falta la clave de Gemini: ponla en Configuracion > Voz de Gemini")
    trozos = _trozos(texto)
    pcm = b""
    for n, t in enumerate(trozos):
        avisar(n, len(trozos))
        pcm += _pedir(t, nombre(voz))
        pcm += b"\x00\x00" * int(TASA * 0.25)   # un respiro entre trozos
    with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as tmp:
        ruta_wav = tmp.name
    try:
        with wave.open(ruta_wav, "wb") as w:
            w.setnchannels(1)
            w.setsampwidth(2)
            w.setframerate(TASA)
            w.writeframes(pcm)
        filtro = ["-af", f"atempo={min(2.0, max(0.5, float(velocidad))):.3f}"] if abs(float(velocidad) - 1.0) > 0.01 else []
        r = medios.correr([medios.ffmpeg(), "-hide_banner", "-loglevel", "error", "-y", "-i", ruta_wav, *filtro,
                           "-c:a", "libmp3lame", "-q:a", "2", salida], timeout=600)
        if r.returncode != 0 or not os.path.isfile(salida):
            raise ErrorGemini(f"ffmpeg no pudo guardar la voz: {r.stderr[-300:]}")
    finally:
        try:
            os.remove(ruta_wav)
        except OSError:
            pass
    return salida
