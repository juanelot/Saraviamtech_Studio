"""
Acabado RAPIDO: voz + musica + subtitulos quemados con UNA pasada de ffmpeg.

El acabado clasico de MoneyPrinterTurbo (video.generate_video) compone cada
fotograma en Python con MoviePy: medido en el Estudio, 468 s para un video de
27 s. Aqui los subtitulos van como ASS (libass) y el audio con amix: segundos.

Requiere un ffmpeg con libass (el de apt/Docker y los builds de gyan.dev lo
traen). Si no lo tiene, render.py cae al acabado clasico.

Mapeo de estilos (los mismos controles que la web de MPT):
  sub_fondo      -> BorderStyle=3 (caja; en ASS la caja usa OutlineColour)
  sin fondo      -> BorderStyle=1 con contorno color_contorno / grosor_contorno
  sub_posicion   -> bottom | top | center | custom (+ sub_posicion_pct desde arriba)
  sub_fondo_redondeado -> no existe en ASS: se ignora (caja recta)
"""
import os
from functools import lru_cache

from loguru import logger
from PIL import ImageFont

from app.services import subtitle
from app.services import video as mpt_video
from app.services.estudio import medios
from app.utils import utils


@lru_cache(maxsize=4)
def tiene_libass(ffmpeg_bin: str) -> bool:
    r = medios.correr([ffmpeg_bin, "-hide_banner", "-filters"], timeout=20)
    return " subtitles " in r.stdout


@lru_cache(maxsize=32)
def familia_fuente(archivo: str) -> str:
    try:
        return ImageFont.truetype(os.path.join(utils.font_dir(), archivo), 20).getname()[0]
    except Exception:  # noqa: BLE001
        return "Arial"


def _color_ass(hexa: str, alfa: int = 0) -> str:
    h = (hexa or "#FFFFFF").lstrip("#")
    if len(h) != 6:
        h = "FFFFFF"
    r, g, b = h[0:2], h[2:4], h[4:6]
    return f"&H{alfa:02X}{b}{g}{r}".upper()


def _t_ass(seg: float) -> str:
    cs = int(round(seg * 100))
    h, cs = divmod(cs, 360000)
    m, cs = divmod(cs, 6000)
    s, cs = divmod(cs, 100)
    return f"{h}:{m:02d}:{s:02d}.{cs:02d}"


def _srt_t(ts: str) -> float:
    ts = ts.strip().replace(",", ".")
    h, m, s = ts.split(":")
    return int(h) * 3600 + int(m) * 60 + float(s)


def srt_a_ass(srt: str, ass: str, p: dict, w: int, h: int):
    tam = int(p["tam_fuente"])
    posicion = p["sub_posicion"]
    alineacion, margen_v, prefijo = 2, int(h * 0.12), ""
    if posicion == "top":
        alineacion, margen_v = 8, int(h * 0.08)
    elif posicion == "center":
        alineacion, margen_v = 5, 0
    elif posicion == "custom":
        y = int(h * float(p["sub_posicion_pct"]) / 100)
        prefijo = f"{{\\an5\\pos({w // 2},{y})}}"
    if p["sub_fondo"]:
        borde, contorno, sombra = 3, max(6, tam // 6), 0
        color_contorno = _color_ass("#000000", 0x50)
    else:
        borde, contorno, sombra = 1, max(1.0, float(p["grosor_contorno"]) * 1.6), 0
        color_contorno = _color_ass(p["color_contorno"])
    margen_h = int(w * 0.08)
    cabecera = f"""[Script Info]
ScriptType: v4.00+
PlayResX: {w}
PlayResY: {h}
WrapStyle: 0
ScaledBorderAndShadow: yes

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Default,{familia_fuente(p['fuente'])},{tam},{_color_ass(p['color_texto'])},&H000000FF,{color_contorno},&H80000000,0,0,0,0,100,100,0,0,{borde},{contorno},{sombra},{alineacion},{margen_h},{margen_h},{margen_v},1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""
    lineas = []
    for _i, tiempos, texto in subtitle.file_to_subtitles(srt):
        if "-->" not in tiempos:
            continue
        a, b = tiempos.split("-->")
        texto = " ".join(texto.split()).replace("{", "(").replace("}", ")")
        lineas.append(f"Dialogue: 0,{_t_ass(_srt_t(a))},{_t_ass(_srt_t(b))},Default,,0,0,0,,{prefijo}{texto}")
    with open(ass, "w", encoding="utf-8") as f:
        f.write(cabecera + "\n".join(lineas) + "\n")


def _ruta_filtro(ruta: str, cwd: str) -> str:
    """Ruta segura para el filtro subtitles: relativa (sin 'C:'), o escapada."""
    try:
        rel = os.path.relpath(ruta, cwd).replace("\\", "/")
        if ":" not in rel and "'" not in rel:
            return rel
    except ValueError:
        pass
    return "'" + ruta.replace("\\", "/").replace(":", "\\:").replace("'", "\\'") + "'"


def acabar(combinado: str, audio: str, srt: str | None, p: dict, w: int, h: int,
           duracion: float, destino: str):
    ff = medios.ffmpeg()
    carpeta = os.path.dirname(destino)
    musica = mpt_video.get_bgm_file(bgm_type="random" if p.get("musica") else "",
                                    bgm_file="" if p.get("musica") in ("", "random", None) else p["musica"])
    args = [ff, "-hide_banner", "-loglevel", "error", "-y", "-i", combinado, "-i", audio]
    if musica:
        args += ["-stream_loop", "-1", "-i", musica]

    filtros = []
    if srt:
        ass = os.path.join(carpeta, "subtitulos.ass")
        srt_a_ass(srt, ass, p, w, h)
        filtros.append(f"[0:v]subtitles={_ruta_filtro(ass, carpeta)}:"
                       f"fontsdir={_ruta_filtro(utils.font_dir(), carpeta)}[v]")
    vv = float(p["volumen_voz"])
    if musica:
        mv = float(p["musica_volumen"])
        fin = max(0.0, duracion - 2)
        filtros.append(f"[1:a]volume={vv}[voz];[2:a]volume={mv},afade=t=out:st={fin:.2f}:d=2[mus];"
                       f"[voz][mus]amix=inputs=2:duration=first:dropout_transition=0:normalize=0[a]")
    else:
        filtros.append(f"[1:a]volume={vv}[a]")
    args += ["-filter_complex", ";".join(filtros),
             "-map", "[v]" if srt else "0:v", "-map", "[a]"]

    if srt:
        codec = mpt_video._get_effective_video_codec(p.get("codec") or None)
        args += ["-c:v", codec]
        if codec in ("libx264", "libx265"):
            args += ["-preset", "fast", "-crf", "20"]
        args += ["-pix_fmt", "yuv420p"]
    else:
        args += ["-c:v", "copy"]
    args += ["-c:a", "aac", "-b:a", "192k", "-t", f"{duracion:.3f}", "-movflags", "+faststart", destino]

    logger.info(f"acabado rapido: subtitulos={'si' if srt else 'no'}, musica={os.path.basename(musica) if musica else 'no'}")
    r = medios.correr(args, timeout=3600, cwd=carpeta)
    if r.returncode != 0 or not os.path.exists(destino):
        raise RuntimeError(f"ffmpeg fallo en el acabado: {r.stderr[-600:]}")
