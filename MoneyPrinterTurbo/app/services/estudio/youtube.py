"""
Descargas con yt-dlp (YouTube, TikTok...) y las cookies opcionales de YouTube.

Sin cuenta funciona casi siempre en el PC. En un servidor (VPS) YouTube a veces
bloquea la IP con "Sign in to confirm you're not a bot": ahi se sube en
Configuracion un cookies.txt (formato Netscape) de una cuenta de YouTube y todas
las descargas lo usan. Si no hay archivo, todo sigue igual que antes.
"""
import os
import time

from app.services.estudio import almacen

VIDEO_PRUEBA = "https://www.youtube.com/watch?v=jNQXAC9IVRw"   # "Me at the zoo": publico y corto
BLOQUEO = ("sign in to confirm", "not a bot", "confirm you", "http error 429", "too many requests")


class Bloqueado(RuntimeError):
    pass


def ruta():
    return almacen.raiz("youtube_cookies.txt")


def estado():
    r = ruta()
    if not os.path.isfile(r):
        return {"cookies": False, "fecha": None}
    return {"cookies": True, "fecha": time.strftime("%Y-%m-%d %H:%M", time.localtime(os.path.getmtime(r)))}


def guardar(contenido: bytes):
    texto = contenido.decode("utf-8", errors="ignore")
    lineas = [ln for ln in texto.splitlines() if ln.strip() and not ln.startswith("#")]
    if not lineas or not all(len(ln.split("\t")) >= 7 for ln in lineas[:20]):
        raise ValueError("no parece un cookies.txt: tiene que ser formato Netscape (lo da la extension 'Get cookies.txt LOCALLY')")
    if not any("youtube.com" in ln.split("\t")[0] for ln in lineas):
        raise ValueError("el archivo no trae cookies de youtube.com: exportalas estando en youtube.com con la sesion iniciada")
    with open(ruta(), "w", encoding="utf-8", newline="\n") as f:
        f.write(texto if texto.endswith("\n") else texto + "\n")
    return estado()


def borrar():
    if os.path.isfile(ruta()):
        os.remove(ruta())
    return estado()


def opciones(base: dict) -> dict:
    """Las opciones de yt-dlp + el cookies.txt si se subio."""
    o = dict(base)
    if os.path.isfile(ruta()):
        o["cookiefile"] = ruta()
    return o


def extraer(base: dict, url: str, download: bool):
    """extract_info con cookies (si hay) y un error claro cuando YouTube bloquea."""
    import yt_dlp
    try:
        with yt_dlp.YoutubeDL(opciones(base)) as y:
            return y.extract_info(url, download=download)
    except yt_dlp.utils.DownloadError as e:
        if any(b in str(e).lower() for b in BLOQUEO):
            hay = os.path.isfile(ruta())
            raise Bloqueado("YouTube bloqueo la descarga desde este equipo (pide confirmar que no eres un bot). "
                            + ("Las cookies subidas ya no sirven: vuelve a exportarlas en Configuracion > YouTube."
                               if hay else "Sube un cookies.txt en Configuracion > YouTube.")) from e
        raise


def probar():
    """Lee (sin bajar) un video publico para saber si YouTube deja descargar desde aqui."""
    try:
        info = extraer({"quiet": True, "no_warnings": True, "skip_download": True, "socket_timeout": 20},
                       VIDEO_PRUEBA, False)
        return {**estado(), "ok": True, "mensaje": f"YouTube responde bien ({(info or {}).get('title') or 'video de prueba'})"}
    except Exception as e:  # noqa: BLE001
        return {**estado(), "ok": False, "mensaje": str(e)[-400:]}
