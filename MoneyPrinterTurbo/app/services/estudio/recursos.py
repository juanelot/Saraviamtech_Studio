"""
Etapa RECURSOS: inventario de lo que aporta la persona (imagenes y videos
mezclados) y catalogo visual hecho por Claude.

Origenes:
  - lo subido al proyecto            storage/estudio/proyectos/<id>/recursos/
  - una carpeta del servidor         params.carpeta (local o montada: NAS, Drive...)
  - una lista de URLs                params.urls (se descargan a recursos/)

Catalogo: cada archivo tiene una miniatura (videos: hoja de 3 fotogramas) y
Claude la MIRA (CLI con Read sobre la carpeta de miniaturas) y la describe. Va
por hash de contenido y es global: un archivo ya descrito no se vuelve a mirar,
ni en este proyecto ni en otro. La persona puede corregir cualquier descripcion
(params.descripciones) sin volver a llamar a Claude.
"""
import hashlib
import os
from concurrent.futures import ThreadPoolExecutor, as_completed
from urllib.parse import urlparse

import requests
from loguru import logger

from app.config import config
from app.services import claude_cli
from app.services.estudio import almacen, medios

DEFECTOS = {
    "carpeta": "",
    "urls": [],
    "descripciones": {},
    "vision": True,
    "idioma": "es",
    "modelo": "sonnet",
    "esfuerzo": "low",
}

LOTE_VISION = 8
PARALELO_VISION = 3


def _carpeta_externa(ruta):
    ruta = (ruta or "").strip()
    if not ruta:
        return None
    if not os.path.isdir(ruta):
        raise ValueError(f"la carpeta no existe en el servidor: {ruta}")
    permitidas = [r for r in (config.app.get("estudio_carpetas_permitidas") or []) if r]
    if permitidas:
        real = os.path.realpath(ruta)
        if not any(real == os.path.realpath(p) or real.startswith(os.path.realpath(p) + os.sep)
                   for p in permitidas):
            raise ValueError("esa carpeta no esta en estudio_carpetas_permitidas (config.toml)")
    return ruta


def _listar(ctx):
    """[(origen, nombre_visible, ruta_abs)] ordenado por nombre."""
    archivos = []
    subidos = ctx.dir("recursos")
    for n in sorted(os.listdir(subidos), key=str.lower):
        ruta = os.path.join(subidos, n)
        if os.path.isfile(ruta) and medios.tipo_de(ruta):
            archivos.append(("subido", n, ruta))
    externa = _carpeta_externa(ctx.params.get("carpeta"))
    if externa:
        encontrados = []
        for base, _dirs, nombres in os.walk(externa):
            for n in nombres:
                ruta = os.path.join(base, n)
                if medios.tipo_de(ruta):
                    encontrados.append(("carpeta", os.path.relpath(ruta, externa).replace("\\", "/"), ruta))
        archivos += sorted(encontrados, key=lambda a: a[1].lower())
    return archivos


def huella(ctx):
    datos = []
    try:
        for origen, nombre, ruta in _listar(ctx):
            st = os.stat(ruta)
            datos.append([origen, nombre, st.st_size, int(st.st_mtime)])
    except ValueError as e:
        datos.append(["error", str(e)])
    return datos


def _descargar_urls(ctx):
    destino = ctx.dir("recursos")
    for url in [u.strip() for u in ctx.params.get("urls") or [] if u and u.strip()]:
        ext = os.path.splitext(urlparse(url).path)[1].lower()
        base = "url_" + hashlib.sha1(url.encode()).hexdigest()[:10]
        if any(n.startswith(base) for n in os.listdir(destino)):
            continue
        ctx.avisar(f"descargando {url[:80]}")
        r = requests.get(url, stream=True, timeout=60)
        r.raise_for_status()
        if ext not in medios.EXT_IMAGEN | medios.EXT_VIDEO:
            ct = r.headers.get("content-type", "")
            ext = {"image/jpeg": ".jpg", "image/png": ".png", "image/webp": ".webp",
                   "video/mp4": ".mp4", "video/quicktime": ".mov", "video/webm": ".webm"}.get(ct.split(";")[0], "")
        if not ext:
            logger.warning(f"URL ignorada (no es imagen ni video): {url}")
            continue
        ruta = os.path.join(destino, base + ext)
        with open(ruta + ".part", "wb") as f:
            for trozo in r.iter_content(1 << 16):
                f.write(trozo)
        os.replace(ruta + ".part", ruta)


def _fichas():
    return almacen.leer_json(os.path.join(almacen.dir_catalogo(), "fichas.json"), {}) or {}


def _guardar_fichas(nuevas: dict):
    with almacen.candado("catalogo"):
        todas = _fichas()
        for h, f in nuevas.items():
            todas.setdefault(h, {}).update(f)
        almacen.escribir_json(os.path.join(almacen.dir_catalogo(), "fichas.json"), todas)


def ruta_miniatura(h):
    return os.path.join(almacen.dir_catalogo("miniaturas"), f"{h}.jpg")


def _describir_lote(lote, idioma, modelo, esfuerzo):
    """lote: [(hash, tipo)] -> {hash: descripcion}"""
    lineas = []
    for h, tipo in lote:
        if tipo == "video":
            lineas.append(f"- {h}.jpg  (VIDEO: hoja con 3 fotogramas: inicio, mitad y final)")
        else:
            lineas.append(f"- {h}.jpg  (IMAGEN)")
    idioma_txt = {"es": "espanol", "en": "ingles", "pt": "portugues"}.get(idioma, idioma)
    prompt = f"""Vas a catalogar recursos visuales para montar un video.
Abre con la herramienta Read cada uno de estos archivos de la carpeta actual:
{chr(10).join(lineas)}

Para cada uno escribe una descripcion objetiva en {idioma_txt} de 12 a 30 palabras:
que se ve (sujeto, accion, lugar), el estilo (foto, dibujo, animacion...), el
tono o emocion, y cualquier texto legible. En los videos, describe lo que pasa.

Responde SOLO con JSON: [{{"id": "<nombre sin .jpg>", "descripcion": "..."}}]"""
    texto = claude_cli.ejecutar(prompt, modelo=modelo, esfuerzo=esfuerzo,
                                cwd=almacen.dir_catalogo("miniaturas"), permitidas=("Read",))
    datos = claude_cli.extraer_json(texto)
    validos = {h for h, _ in lote}
    return {str(d.get("id", "")).replace(".jpg", ""): str(d.get("descripcion", "")).strip()
            for d in datos if isinstance(d, dict) and str(d.get("id", "")).replace(".jpg", "") in validos}


def ejecutar(ctx):
    p = ctx.params
    if p.get("urls"):
        _descargar_urls(ctx)
    archivos = _listar(ctx)
    if not archivos:
        raise ValueError("no hay recursos: sube imagenes o videos, o indica una carpeta")

    ctx.avisar(f"{len(archivos)} archivos: leyendo y haciendo miniaturas", 5)
    fichas = _fichas()
    nuevas = {}
    recursos, vistos = [], set()
    for k, (origen, nombre, ruta) in enumerate(archivos):
        ctx.avisar(progreso=5 + 35 * k / len(archivos))
        try:
            h = medios.huella(ruta)
            if h in vistos:
                continue
            ficha = fichas.get(h) or {}
            if "ancho" not in ficha:
                ficha = {**ficha, **medios.sondear(ruta), "tipo": medios.tipo_de(ruta)}
                nuevas[h] = ficha
            if ficha["tipo"] == "video" and ficha.get("duracion", 0) <= 0:
                logger.warning(f"video sin duracion legible, se omite: {nombre}")
                continue
            if min(ficha.get("ancho", 0), ficha.get("alto", 0)) < 200:
                logger.warning(f"resolucion demasiado baja, se omite: {nombre}")
                continue
            if not medios.miniatura(ruta, ruta_miniatura(h), ficha):
                logger.warning(f"no se pudo hacer la miniatura, se omite: {nombre}")
                continue
        except Exception as e:  # noqa: BLE001
            logger.warning(f"recurso ilegible, se omite: {nombre} ({e})")
            continue
        vistos.add(h)
        recursos.append({"id": h, "nombre": nombre, "origen": origen, "ruta": ruta,
                         "tipo": ficha["tipo"], "ancho": ficha["ancho"], "alto": ficha["alto"],
                         "duracion": ficha.get("duracion", 0.0)})
    if nuevas:
        _guardar_fichas(nuevas)
        fichas = _fichas()

    if not recursos:
        raise ValueError("ningun recurso se pudo leer")

    faltan = [(r["id"], r["tipo"]) for r in recursos if not fichas.get(r["id"], {}).get("descripcion")]
    if p.get("vision", True) and faltan:
        lotes = [faltan[i:i + LOTE_VISION] for i in range(0, len(faltan), LOTE_VISION)]
        ctx.avisar(f"Claude mirando {len(faltan)} recursos nuevos ({len(lotes)} lotes)", 40)
        hechos = 0
        with ThreadPoolExecutor(max_workers=PARALELO_VISION) as ex:
            futuros = {ex.submit(_describir_lote, lote, p["idioma"], p["modelo"], p["esfuerzo"]): lote
                       for lote in lotes}
            for fut in as_completed(futuros):
                try:
                    desc = fut.result()
                    _guardar_fichas({h: {"descripcion": d} for h, d in desc.items() if d})
                except Exception as e:  # noqa: BLE001
                    logger.warning(f"lote de vision fallo: {e}")
                hechos += 1
                ctx.avisar(f"catalogo: {hechos}/{len(lotes)} lotes", 40 + 55 * hechos / len(lotes))
        fichas = _fichas()

    manuales = p.get("descripciones") or {}
    sin_desc = 0
    for r in recursos:
        if (manuales.get(r["id"]) or "").strip():
            r["descripcion"], r["descripcion_manual"] = manuales[r["id"]].strip(), True
        else:
            r["descripcion"] = fichas.get(r["id"], {}).get("descripcion", "")
            r["descripcion_manual"] = False
            if not r["descripcion"]:
                sin_desc += 1
    if sin_desc:
        logger.warning(f"{sin_desc} recursos sin descripcion (se asignaran por su nombre de archivo)")

    n_img = sum(r["tipo"] == "imagen" for r in recursos)
    ctx.avisar(f"recursos listos: {n_img} imagenes, {len(recursos) - n_img} videos", 100)
    return {"recursos": recursos, "total": len(recursos), "imagenes": n_img,
            "videos": len(recursos) - n_img, "sin_descripcion": sin_desc}
