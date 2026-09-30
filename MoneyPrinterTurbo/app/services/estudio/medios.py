"""
Utilidades de archivos multimedia: tipo, huella de contenido, sondeo con ffmpeg
y miniaturas. Solo ffmpeg (sin ffprobe: imageio-ffmpeg no lo trae) y Pillow.
"""
import hashlib
import os
import re
import subprocess

from PIL import Image

from app.utils import utils

EXT_IMAGEN = {".jpg", ".jpeg", ".png", ".bmp", ".webp"}
EXT_VIDEO = {".mp4", ".mov", ".mkv", ".webm", ".avi", ".m4v"}

SIN_VENTANA = {}
if os.name == "nt":
    SIN_VENTANA = {"creationflags": getattr(subprocess, "CREATE_NO_WINDOW", 0x08000000)}


def ffmpeg():
    return utils.get_ffmpeg_binary()


def tipo_de(ruta):
    ext = os.path.splitext(ruta)[1].lower()
    if ext in EXT_IMAGEN:
        return "imagen"
    if ext in EXT_VIDEO:
        return "video"
    return None


def huella(ruta) -> str:
    """Hash de contenido rapido: tamano + primer y ultimo MB."""
    h = hashlib.sha1()
    tam = os.path.getsize(ruta)
    h.update(str(tam).encode())
    with open(ruta, "rb") as f:
        h.update(f.read(1 << 20))
        if tam > (2 << 20):
            f.seek(-(1 << 20), os.SEEK_END)
            h.update(f.read(1 << 20))
    return h.hexdigest()[:16]


def correr(args, timeout=600, cwd=None):
    r = subprocess.run(args, capture_output=True, text=True, encoding="utf-8",
                       errors="replace", timeout=timeout, cwd=cwd, **SIN_VENTANA)
    return r


def sondear(ruta) -> dict:
    """{ancho, alto, duracion} via `ffmpeg -i` (lee la cabecera, no decodifica)."""
    if tipo_de(ruta) == "imagen":
        with Image.open(ruta) as im:
            return {"ancho": im.width, "alto": im.height, "duracion": 0.0}
    r = correr([ffmpeg(), "-hide_banner", "-i", ruta], timeout=60)
    texto = r.stderr
    info = {"ancho": 0, "alto": 0, "duracion": 0.0}
    m = re.search(r"Duration:\s*(\d+):(\d+):(\d+(?:\.\d+)?)", texto)
    if m:
        info["duracion"] = round(int(m.group(1)) * 3600 + int(m.group(2)) * 60 + float(m.group(3)), 3)
    m = re.search(r"Video:.*?(\d{2,5})x(\d{2,5})", texto)
    if m:
        info["ancho"], info["alto"] = int(m.group(1)), int(m.group(2))
    rot = re.search(r"rotate\s*:\s*(-?\d+)|rotation of (-?\d+)", texto)
    if rot and abs(int(rot.group(1) or rot.group(2))) in (90, 270):
        info["ancho"], info["alto"] = info["alto"], info["ancho"]
    return info


def tiene_audio(ruta) -> bool:
    if tipo_de(ruta) == "imagen":
        return False
    r = correr([ffmpeg(), "-hide_banner", "-i", ruta], timeout=60)
    return bool(re.search(r"Stream #.*Audio:", r.stderr))


def _fotograma(ruta, t, destino):
    correr([ffmpeg(), "-hide_banner", "-loglevel", "error", "-y", "-ss", f"{t:.2f}",
            "-i", ruta, "-frames:v", "1", "-vf", "scale=512:-2", destino], timeout=120)
    return os.path.exists(destino)


def miniatura(ruta, destino, info=None) -> bool:
    """JPG de 512 px. Videos: hoja de 3 fotogramas (inicio, medio, final)."""
    if os.path.exists(destino):
        return True
    os.makedirs(os.path.dirname(destino), exist_ok=True)
    if tipo_de(ruta) == "imagen":
        with Image.open(ruta) as im:
            im = im.convert("RGB")
            im.thumbnail((512, 512))
            im.save(destino, quality=82)
        return True

    info = info or sondear(ruta)
    dur = info.get("duracion") or 0
    tiempos = [min(0.5, dur / 4), dur * 0.5, max(0.0, dur * 0.9)] if dur > 1.5 else [0.0]
    cuadros = []
    for k, t in enumerate(tiempos):
        tmp = f"{destino}.{k}.png"
        if _fotograma(ruta, t, tmp):
            cuadros.append(tmp)
    if not cuadros:
        return False
    imgs = [Image.open(c).convert("RGB") for c in cuadros]
    alto = min(i.height for i in imgs)
    imgs = [i.resize((int(i.width * alto / i.height), alto)) for i in imgs]
    hoja = Image.new("RGB", (sum(i.width for i in imgs) + 8 * (len(imgs) - 1), alto), (20, 20, 20))
    x = 0
    for i in imgs:
        hoja.paste(i, (x, 0))
        x += i.width + 8
    hoja.thumbnail((1024, 512))
    hoja.save(destino, quality=82)
    for i, c in zip(imgs, cuadros):
        i.close()
        os.remove(c)
    return True
