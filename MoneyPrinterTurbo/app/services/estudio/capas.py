"""
Capas del editor (render.capas): lo que se pone ENCIMA de la pista principal.

  video  una imagen o un clip del proyecto en un tramo: a pantalla completa
         (tapa la pista principal) o en ventana (x, y = centro en 0-1, escala =
         ancho en 0-1). `volumen` > 0 deja oir el sonido del clip. Un grafico
         animado (graficos.py) es una capa de video con `archivo` =
         graficos/<huella>.webm (transparente) en vez de `recurso`.
  texto  un texto propio (titulo, rotulo): tam (px a la altura del video),
         color, fondo (caja), y (centro en 0-1).
  audio  un audio del proyecto (audios/...) o una cancion de la biblioteca
         ("cancion:<archivo>"): desde `offset`, con su volumen.

Cada capa: {id, tipo, carril, inicio, fin, ...}. Un carril mas alto va encima.
Las capas se anaden despues de unir los clips (video), al mezclar el audio y
como un segundo ASS en el acabado.

Ademas, las tres pistas que antes iban juntas se colocan por separado (ver
`colocacion`): la principal (`principal_desde`), la voz (`voz_tramos`) y los
subtitulos (`subs_tramos`); un tramo {desde, hasta, en} pone el trozo
[desde, hasta) de la voz en el segundo `en` del video.
"""
import os
import re

from loguru import logger

from app.services.estudio import acabado, almacen, medios
from app.utils import utils

TIPOS = ("video", "texto", "audio")
MAX_CAPAS = 200
FPS = 30


def _num(v, defecto, lo=None, hi=None):
    try:
        x = float(v)
    except (TypeError, ValueError):
        x = defecto
    if lo is not None:
        x = max(lo, x)
    if hi is not None:
        x = min(hi, x)
    return x


def validas(capas, duracion):
    """Solo capas bien formadas y dentro del video, ordenadas por carril e inicio."""
    salida = []
    for c in (capas or [])[:MAX_CAPAS]:
        if not isinstance(c, dict) or c.get("tipo") not in TIPOS:
            continue
        a = _num(c.get("inicio"), 0, 0, duracion)
        b = _num(c.get("fin"), a, 0, duracion)
        if b - a < 0.05:
            continue
        salida.append({**c, "inicio": a, "fin": b, "carril": int(_num(c.get("carril"), 1, 1, 20))})
    return sorted(salida, key=lambda c: (c["carril"], c["inicio"]))


def recursos_del_proyecto(pid):
    estado = almacen.cargar_estado(pid)
    return {r["id"]: r for r in ((estado["etapas"].get("recursos") or {}).get("salida") or {}).get("recursos") or []}


def ruta_audio(pid, archivo):
    """audios/<x> del proyecto o cancion:<x> de la biblioteca (nunca otra ruta)."""
    archivo = str(archivo or "")
    try:
        if archivo.startswith("cancion:"):
            return almacen.dentro_de(utils.song_dir(), archivo.split(":", 1)[1])
        if archivo.startswith("audios/"):
            return almacen.dentro_de(almacen.dir_proyecto(pid, "audios"), archivo.split("/", 1)[1])
    except ValueError:
        pass
    return ""


def superponer(combinado, capas, recursos, w, h, encaje_fn, destino, pid=None):
    """Pone las capas de video sobre el video unido. Devuelve la ruta del video nuevo
    (o `combinado` si no hay capas validas)."""
    from app.services.estudio import graficos
    usar = []
    for c in capas:
        if c["tipo"] != "video":
            continue
        if c.get("archivo"):  # grafico animado: WebM con transparencia, ya del tamano del video
            ruta = graficos.ruta(pid, c["archivo"]) if pid else None
            if not ruta:
                logger.warning(f"capa {c.get('id')}: el grafico no esta renderizado; se omite")
                continue
            usar.append((c, {"tipo": "grafico", "ruta": ruta}))
            continue
        r = recursos.get(c.get("recurso"))
        if not r or not os.path.isfile(r["ruta"]):
            logger.warning(f"capa {c.get('id')}: el recurso ya no esta; se omite")
            continue
        usar.append((c, r))
    if not usar:
        return combinado
    ff = medios.ffmpeg()
    args = [ff, "-hide_banner", "-loglevel", "error", "-y", "-i", combinado]
    filtros, previo = [], "0:v"
    for k, (c, r) in enumerate(usar, start=1):
        dur = c["fin"] - c["inicio"]
        if r["tipo"] == "imagen":
            args += ["-loop", "1", "-framerate", str(FPS), "-t", f"{dur:.3f}", "-i", r["ruta"]]
            cola = ""
        elif r["tipo"] == "grafico":
            # libvpx decodifica el canal alfa del WebM (el decodificador nativo lo pierde);
            # al acabar el grafico la capa deja ver lo de debajo.
            args += ["-c:v", "libvpx-vp9", "-t", f"{dur:.3f}", "-i", r["ruta"]]
            cola = ""
        else:
            off = _num(c.get("offset"), 0, 0)
            args += ["-ss", f"{off:.3f}", "-t", f"{dur:.3f}", "-i", r["ruta"]]
            # Clip mas corto que la capa: se queda en su ultimo fotograma.
            cola = f",tpad=stop_mode=clone:stop_duration={dur:.3f}"
        if c.get("modo") == "ventana":
            esc = _num(c.get("escala"), 0.4, 0.05, 1)
            ancho = max(2, int(w * esc) // 2 * 2)
            forma = f"scale={ancho}:-2,setsar=1"
            x = f"{_num(c.get('x'), 0.5, 0, 1) * w:.0f}-w/2"
            y = f"{_num(c.get('y'), 0.5, 0, 1) * h:.0f}-h/2"
        elif r["tipo"] == "grafico":
            forma, x, y = f"scale={w}:{h},setsar=1", "0", "0"
        else:
            forma, x, y = encaje_fn(c.get("encaje") or "recortar", w, h), "0", "0"
        filtros.append(f"[{k}:v]{forma}{cola},fps={FPS},trim=duration={dur:.3f},"
                       f"setpts=PTS-STARTPTS+{c['inicio']:.3f}/TB,format=yuva420p[c{k}]")
        filtros.append(f"[{previo}][c{k}]overlay=x={x}:y={y}:eof_action=pass:"
                       f"enable='between(t,{c['inicio']:.3f},{c['fin']:.3f})'[v{k}]")
        previo = f"v{k}"
    args += ["-filter_complex", ";".join(filtros), "-map", f"[{previo}]", "-an", "-r", str(FPS),
             "-c:v", "libx264", "-preset", "veryfast", "-crf", "20", "-pix_fmt", "yuv420p", destino]
    res = medios.correr(args, timeout=3600)
    if res.returncode != 0 or not os.path.isfile(destino):
        raise RuntimeError(f"no se pudieron poner las capas de video: {res.stderr[-500:]}")
    return destino


def mezclar_audio(pid, voz_audio, capas, recursos, destino):
    """Voz + audios de las capas (y el sonido de las capas de video con volumen)."""
    pistas = []
    for c in capas:
        vol = _num(c.get("volumen"), 1.0 if c["tipo"] == "audio" else 0.0, 0, 3)
        if vol <= 0:
            continue
        if c["tipo"] == "audio":
            ruta = ruta_audio(pid, c.get("archivo"))
        elif c["tipo"] == "video":
            r = recursos.get(c.get("recurso"))
            ruta = r["ruta"] if r and r["tipo"] == "video" and medios.tiene_audio(r["ruta"]) else ""
        else:
            continue
        if ruta and os.path.isfile(ruta):
            pistas.append((c, ruta, vol))
    if not pistas:
        return voz_audio
    ff = medios.ffmpeg()
    args = [ff, "-hide_banner", "-loglevel", "error", "-y", "-i", voz_audio]
    mono = re.search(r"Audio:.*\bmono\b", medios.correr([ff, "-hide_banner", "-i", voz_audio]).stderr)
    filtros = ["[0:a]aresample=44100," + ("pan=stereo|c0=c0|c1=c0" if mono else "aformat=channel_layouts=stereo") + "[voz]"]
    nombres = ["[voz]"]
    for k, (c, ruta, vol) in enumerate(pistas, start=1):
        dur = c["fin"] - c["inicio"]
        args += ["-ss", f"{_num(c.get('offset'), 0, 0):.3f}", "-t", f"{dur:.3f}", "-i", ruta]
        fundido = min(0.3, dur / 4)
        filtros.append(f"[{k}:a]aresample=44100,aformat=channel_layouts=stereo,volume={vol:.3f},"
                       f"afade=t=in:d={fundido:.2f},afade=t=out:st={max(0, dur - fundido):.2f}:d={fundido:.2f},"
                       f"adelay={int(c['inicio'] * 1000)}:all=1[a{k}]")
        nombres.append(f"[a{k}]")
    filtros.append("".join(nombres) + f"amix=inputs={len(nombres)}:duration=first:dropout_transition=0:normalize=0[a]")
    args += ["-filter_complex", ";".join(filtros), "-map", "[a]", "-ar", "44100", "-ac", "2", "-c:a", "pcm_s16le", destino]
    res = medios.correr(args, timeout=1800)
    if res.returncode != 0 or not os.path.isfile(destino):
        raise RuntimeError(f"no se pudieron mezclar los audios de las capas: {res.stderr[-500:]}")
    return destino


def textos_ass(capas, p, w, h, destino):
    """Los textos propios como un ASS aparte (van encima de los subtitulos)."""
    textos = [c for c in capas if c["tipo"] == "texto" and str(c.get("texto") or "").strip()]
    if not textos:
        return None
    fuente = acabado.familia_fuente(p.get("fuente") or "STHeitiMedium.ttc")
    estilos = [
        f"Style: Caja,{fuente},60,&H00FFFFFF,&H000000FF,&H50000000,&H80000000,-1,0,0,0,100,100,0,0,3,14,0,5,40,40,40,1",
        f"Style: Limpio,{fuente},60,&H00FFFFFF,&H000000FF,&H00000000,&H80000000,-1,0,0,0,100,100,0,0,1,4,2,5,40,40,40,1",
    ]
    lineas = []
    for c in textos:
        tam = int(_num(c.get("tam"), 90, 16, 400))
        x = int(_num(c.get("x"), 0.5, 0, 1) * w)
        y = int(_num(c.get("y"), 0.5, 0, 1) * h)
        color = acabado._color_ass(c.get("color") or "#FFFFFF")
        estilo = "Caja" if c.get("fondo", True) else "Limpio"
        texto = acabado.limpio(str(c["texto"]).strip()).replace("\n", "\\N")
        lineas.append(f"Dialogue: {c['carril']},{acabado._t_ass(c['inicio'])},{acabado._t_ass(c['fin'])},{estilo},,0,0,0,,"
                      f"{{\\an5\\pos({x},{y})\\fs{tam}\\c{color}\\fad(150,150)}}{texto}")
    with open(destino, "w", encoding="utf-8") as f:
        f.write(acabado.cabecera(w, h, estilos) + "\n".join(lineas) + "\n")
    return destino


def _tramos(lista, dur, en_defecto):
    """Tramos (desde, hasta, en) de la voz o de los subtitulos: el trozo [desde, hasta)
    de la voz suena (o se lee) desde el segundo `en` del video. Sin lista: entera en `en_defecto`."""
    if not isinstance(lista, list):
        return [(0.0, round(dur, 3), round(en_defecto, 3))]
    out = []
    for x in lista[:MAX_CAPAS]:
        if not isinstance(x, dict):
            continue
        a = _num(x.get("desde"), 0, 0, dur)
        b = _num(x.get("hasta"), dur, 0, dur)
        if b - a < 0.05:
            continue
        out.append((round(a, 3), round(b, 3), round(_num(x.get("en"), a, 0, 3600), 3)))
    return sorted(out, key=lambda t: (t[2], t[0]))


def colocacion(p, capas, dur_voz, sin_voz=False):
    """Donde va cada pista en el video (el editor las mueve por separado):
    `principal_desde` (los clips unidos), `voz_tramos` y `subs_tramos`. Lo que falte
    sale de `voz_retraso` (las tres juntas, como antes); los subtitulos siguen a la
    voz si no tienen tramos propios. Sin voz propia, la "voz" es el sonido de los
    clips y va con la principal."""
    r = _num(p.get("voz_retraso"), 0, 0, 600)
    pr = round(r if p.get("principal_desde") is None else _num(p.get("principal_desde"), r, 0, 3600), 3)
    voz = [(0.0, round(dur_voz, 3), pr)] if sin_voz else _tramos(p.get("voz_tramos"), dur_voz, r)
    subs = voz if p.get("subs_tramos") is None else _tramos(p.get("subs_tramos"), dur_voz, r)
    fin = max([pr + dur_voz] + [en + b - a for a, b, en in voz + subs] + [c["fin"] for c in capas])
    total = round(min(fin, pr + dur_voz + 600), 3)
    entera = [(0.0, round(dur_voz, 3), 0.0)]
    tal_cual = pr == 0 and voz == entera and subs == entera and total <= dur_voz + 0.001
    return {"principal": pr, "voz": voz, "subs": subs, "total": total, "tal_cual": tal_cual}


def alargar_video(combinado, antes, despues, destino):
    """Negro antes y despues del video unido (las capas lo cubren)."""
    res = medios.correr([medios.ffmpeg(), "-hide_banner", "-loglevel", "error", "-y", "-i", combinado, "-vf",
                         f"tpad=start_duration={antes:.3f}:stop_duration={despues:.3f}:color=black",
                         "-an", "-c:v", "libx264", "-preset", "veryfast", "-crf", "20", "-pix_fmt", "yuv420p", destino],
                        timeout=3600)
    if res.returncode != 0 or not os.path.isfile(destino):
        raise RuntimeError(f"no se pudo alargar el video: {res.stderr[-400:]}")
    return destino


def alargar_audio(audio, antes, despues, destino):
    """Silencio antes (retraso) y despues de una pista de audio."""
    filtro = (f"adelay={int(antes * 1000)}:all=1," if antes > 0 else "") + f"apad=pad_dur={despues + 0.1:.3f}"
    res = medios.correr([medios.ffmpeg(), "-hide_banner", "-loglevel", "error", "-y", "-i", audio, "-af", filtro,
                         "-ar", "44100", "-c:a", "pcm_s16le", destino], timeout=1800)
    if res.returncode != 0 or not os.path.isfile(destino):
        raise RuntimeError(f"no se pudo alargar el audio: {res.stderr[-400:]}")
    return destino


def colocar_audio(audio, tramos, total, destino):
    """La voz por tramos: cada trozo [desde, hasta) suena desde su `en`; el resto, silencio."""
    ff = medios.ffmpeg()
    if not tramos:
        args = [ff, "-hide_banner", "-loglevel", "error", "-y", "-f", "lavfi", "-i", "anullsrc=r=44100:cl=stereo"]
    else:
        n = len(tramos)
        filtros = ["[0:a]aresample=44100" + (f",asplit={n}" + "".join(f"[s{k}]" for k in range(n)) if n > 1 else "[s0]")]
        for k, (a, b, en) in enumerate(tramos):
            filtros.append(f"[s{k}]atrim={a:.3f}:{b:.3f},asetpts=PTS-STARTPTS,adelay={int(en * 1000)}:all=1[t{k}]")
        filtros.append("".join(f"[t{k}]" for k in range(n))
                       + f"amix=inputs={n}:duration=longest:dropout_transition=0:normalize=0,apad[a]")
        args = [ff, "-hide_banner", "-loglevel", "error", "-y", "-i", audio, "-filter_complex", ";".join(filtros),
                "-map", "[a]"]
    res = medios.correr(args + ["-t", f"{total:.3f}", "-ar", "44100", "-c:a", "pcm_s16le", destino], timeout=1800)
    if res.returncode != 0 or not os.path.isfile(destino):
        raise RuntimeError(f"no se pudo colocar la voz: {res.stderr[-400:]}")
    return destino


_DIALOGO = re.compile(r"^(Dialogue: [^,]*,)(\d+:\d\d:\d\d\.\d\d),(\d+:\d\d:\d\d\.\d\d),")


def _seg_ass(t):
    h, m, s = t.split(":")
    return int(h) * 3600 + int(m) * 60 + float(s)


def colocar_ass(origen, tramos, destino):
    """Copia de un ASS (en tiempo de la voz) con cada linea en su tramo: se corre a
    donde va ese trozo y se recorta a sus bordes; lo que cae fuera de todo tramo se quita."""
    with open(origen, encoding="utf-8") as f:
        lineas = f.read().splitlines()
    out = []
    for ln in lineas:
        m = _DIALOGO.match(ln)
        if not m:
            out.append(ln)
            continue
        ini, fin = _seg_ass(m.group(2)), _seg_ass(m.group(3))
        for a, b, en in tramos:
            x, y = max(ini, a), min(fin, b)
            if y - x < 0.02:
                continue
            ta = acabado._t_ass(x - a + en)
            tb = acabado._t_ass(y - a + en)
            out.append(f"{m.group(1)}{ta},{tb}," + ln[m.end():])
    with open(destino, "w", encoding="utf-8") as f:
        f.write("\n".join(out) + "\n")
    return destino
