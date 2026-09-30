"""
API del Estudio: proyectos por etapas (guion -> voz -> recursos -> asignacion
-> render) con los recursos de la persona y Claude CLI como cerebro.

Todas las rutas cuelgan de /api/v1/estudio.
"""
import json
import os
import re
import shutil
import tempfile
import zipfile

from fastapi import Body, File, Form, HTTPException, Query, UploadFile
from fastapi.responses import FileResponse, PlainTextResponse, Response

from app.controllers.v1.base import new_router
from app.services import claude_cli
from app.services.estudio import (almacen, asistente, creaciones, grafo, maestros, medios, recursos, referencias,
                                  voz_clonada)
from app.services.estudio import miniatura as portada_video

router = new_router()
router.tags = ["Estudio"]

NOMBRE_SEGURO = re.compile(r"[^\w.\- ()]+", re.UNICODE)


def _existe(pid):
    try:
        return almacen.cargar(pid)
    except (FileNotFoundError, ValueError):
        raise HTTPException(404, "proyecto no encontrado")


def _vista(pid):
    proyecto, _estado, etapas = grafo.evaluar(pid)
    trabajo, log = grafo.trabajo(pid)
    return {"proyecto": proyecto, "etapas": etapas, "orden": grafo.ETAPAS,
            "deps": grafo.DEPS, "trabajo": trabajo, "log": log}


@router.get("/estudio/proyectos", summary="Listar proyectos del Estudio")
def listar():
    salida = []
    for p in almacen.listar():
        estado = almacen.cargar_estado(p["id"])
        render = (estado["etapas"].get("render") or {}).get("salida") or {}
        mini = portada_video.estado(p["id"])
        salida.append({"id": p["id"], "titulo": p["titulo"], "creado": p["creado"],
                       "actualizado": max(p["actualizado"], mini["version"] or 0), "mp4": render.get("mp4"),
                       "portada": _portada(p["id"]) if render.get("mp4") or mini["final"] else None,
                       "duracion": render.get("duracion"),
                       "trabajando": grafo.trabajo(p["id"])[0] is not None})
    return {"proyectos": salida}


def _portada(pid):
    """La miniatura FINAL subida; si no hay, render/portada.jpg: un fotograma del
    video final (se crea si falta o si es vieja)."""
    final = portada_video.estado(pid)["final"]
    if final:
        return final
    video = almacen.dir_proyecto(pid, "render", "final.mp4")
    portada = almacen.dir_proyecto(pid, "render", "portada.jpg")
    if not os.path.isfile(video):
        return None
    if not os.path.isfile(portada) or os.path.getmtime(portada) < os.path.getmtime(video):
        try:
            medios.correr([medios.ffmpeg(), "-hide_banner", "-loglevel", "error", "-y", "-ss", "1.5",
                           "-i", video, "-frames:v", "1", "-vf", "scale=640:-2", "-q:v", "4", portada], timeout=60)
        except Exception:  # noqa: BLE001
            return None
    return "render/portada.jpg" if os.path.isfile(portada) else None


@router.post("/estudio/proyectos", summary="Crear proyecto")
def crear(body: dict = Body(default={})):
    proyecto = almacen.crear(body.get("titulo", ""))
    params = body.get("params") or {}
    if params:
        proyecto["params"] = {e: v for e, v in params.items() if e in grafo.ETAPAS and isinstance(v, dict)}
        almacen.guardar(proyecto)
    return _vista(proyecto["id"])


@router.get("/estudio/proyectos/{pid}", summary="Proyecto + estado de cada etapa")
def ver(pid: str):
    _existe(pid)
    return _vista(pid)


@router.patch("/estudio/proyectos/{pid}", summary="Cambiar titulo y/o params de etapas")
def editar(pid: str, body: dict = Body(...)):
    """body: {"titulo"?: str, "params"?: {etapa: {clave: valor}}} — se FUSIONA."""
    with almacen.candado(pid):
        proyecto = _existe(pid)
        if "titulo" in body:
            proyecto["titulo"] = str(body["titulo"]).strip()[:200] or proyecto["titulo"]
        for etapa, cambios in (body.get("params") or {}).items():
            if etapa not in grafo.ETAPAS or not isinstance(cambios, dict):
                raise HTTPException(400, f"etapa desconocida: {etapa}")
            actual = proyecto["params"].setdefault(etapa, {})
            for k, v in cambios.items():
                if v is None:
                    actual.pop(k, None)
                else:
                    actual[k] = v
        almacen.guardar(proyecto)
    return _vista(pid)


@router.delete("/estudio/proyectos/{pid}", summary="Borrar proyecto")
def borrar(pid: str):
    _existe(pid)
    grafo.cancelar(pid)
    shutil.rmtree(almacen.dir_proyecto(pid), ignore_errors=True)
    return {"ok": True}


@router.post("/estudio/proyectos/{pid}/duplicar", summary="Duplicar proyecto (params + recursos subidos)")
def duplicar(pid: str, body: dict = Body(default={})):
    """Copia los ajustes de todas las etapas y los archivos subidos. No copia lo
    generado: el duplicado empieza sin guion, voz ni video (se regeneran)."""
    origen = _existe(pid)
    nuevo = almacen.crear(body.get("titulo") or f"Copia de {origen['titulo']}")
    params = {e: dict(v) for e, v in (origen.get("params") or {}).items()}
    if not body.get("con_guion"):
        params.get("guion", {}).pop("texto_manual", None)
    params.get("asignacion", {}).pop("fijados", None)
    nuevo["params"] = params
    almacen.guardar(nuevo)
    src = almacen.dir_proyecto(pid, "recursos")
    dst = almacen.dir_proyecto(nuevo["id"], "recursos", crear=True)
    if os.path.isdir(src):
        # Con subcarpetas: images/ y videos/ del modo escenas.
        shutil.copytree(src, dst, dirs_exist_ok=True,
                        ignore=lambda d, ns: [n for n in ns if os.path.isfile(os.path.join(d, n)) and not medios.tipo_de(n)])
    return _vista(nuevo["id"])


@router.post("/estudio/proyectos/{pid}/ejecutar", summary="Ejecutar hasta una etapa")
def ejecutar(pid: str, body: dict = Body(default={})):
    """body: {"hasta": "render", "forzar": ["asignacion"]} — solo corre lo obsoleto."""
    _existe(pid)
    try:
        grafo.lanzar(pid, body.get("hasta", "render"), body.get("forzar") or [])
    except RuntimeError as e:
        raise HTTPException(409, str(e))
    except ValueError as e:
        raise HTTPException(400, str(e))
    return _vista(pid)


@router.post("/estudio/proyectos/{pid}/cancelar", summary="Cancelar el trabajo en curso")
def cancelar(pid: str):
    _existe(pid)
    return {"cancelado": grafo.cancelar(pid)}


# ------------------------------------------------------------------ recursos

@router.get("/estudio/proyectos/{pid}/recursos", summary="Archivos subidos al proyecto")
def listar_subidos(pid: str):
    _existe(pid)
    carpeta = almacen.dir_proyecto(pid, "recursos", crear=True)
    archivos = []
    for base, _dirs, nombres in os.walk(carpeta):
        for n in nombres:
            ruta = os.path.join(base, n)
            if medios.tipo_de(ruta) and not n.endswith(".part"):
                rel = os.path.relpath(ruta, carpeta).replace("\\", "/")
                archivos.append({"nombre": rel, "tipo": medios.tipo_de(ruta), "tam": os.path.getsize(ruta),
                                 "carpeta": recursos.subcarpeta_de(rel), "escena": recursos.numero_escena(rel)})
    archivos.sort(key=lambda a: [int(t) if t.isdigit() else t.lower() for t in re.split(r"(\d+)", a["nombre"])])
    return {"archivos": archivos}


def _guardar_subida(origen, carpeta, nombre, sub):
    nombre = NOMBRE_SEGURO.sub("_", os.path.basename(nombre or "")).strip() or "archivo"
    if not medios.tipo_de(nombre):
        return None
    destino_dir = os.path.join(carpeta, sub) if sub else carpeta
    os.makedirs(destino_dir, exist_ok=True)
    destino = almacen.dentro_de(carpeta, os.path.join(sub, nombre) if sub else nombre)
    with open(destino + ".part", "wb") as f:
        shutil.copyfileobj(origen, f, 1 << 20)
    os.replace(destino + ".part", destino)
    return f"{sub}/{nombre}" if sub else nombre


@router.post("/estudio/proyectos/{pid}/recursos", summary="Subir imagenes, videos o un ZIP")
def subir(pid: str, archivos: list[UploadFile] = File(...),
          sub: str = Query("", description="'' | images | videos (formato de la extension)")):
    """Un ZIP se descomprime: lo que este dentro de images/ o videos/ va a esas
    subcarpetas (carpeta de la extension "AI Content Generator"); el resto, suelto."""
    _existe(pid)
    if sub not in ("", "images", "videos"):
        raise HTTPException(400, "sub debe ser '', images o videos")
    carpeta = almacen.dir_proyecto(pid, "recursos", crear=True)
    guardados, rechazados = [], []
    for a in archivos:
        if (a.filename or "").lower().endswith(".zip"):
            try:
                with zipfile.ZipFile(a.file) as z:
                    for info in z.infolist():
                        if info.is_dir() or "__MACOSX" in info.filename:
                            continue
                        sub_zip = recursos.subcarpeta_de(info.filename) or sub
                        with z.open(info) as origen:
                            hecho = _guardar_subida(origen, carpeta, info.filename, sub_zip)
                        (guardados if hecho else rechazados).append(hecho or info.filename)
            except zipfile.BadZipFile:
                rechazados.append(a.filename)
            continue
        hecho = _guardar_subida(a.file, carpeta, a.filename, sub)
        (guardados if hecho else rechazados).append(hecho or a.filename)
    rechazados = [r for r in rechazados if not r.lower().endswith(("script.json", ".ds_store", "thumbs.db"))]
    return {"guardados": guardados, "rechazados": rechazados}


@router.delete("/estudio/proyectos/{pid}/recursos/{nombre:path}", summary="Quitar un archivo subido")
def quitar(pid: str, nombre: str):
    _existe(pid)
    try:
        ruta = almacen.dentro_de(almacen.dir_proyecto(pid, "recursos"), nombre)
    except ValueError:
        raise HTTPException(400, "nombre no valido")
    if os.path.isfile(ruta):
        os.remove(ruta)
    return {"ok": True}


# ------------------------------------------------------------------ escenas

def _escenas(pid):
    """Escenas de la ultima ejecucion + las ediciones a mano ACTUALES (aunque la
    etapa no se haya vuelto a ejecutar: lo que se descarga es lo que se ve)."""
    _, _, etapas = grafo.evaluar(_existe(pid)["id"])
    salida = etapas["escenas"]["salida"]
    if not salida:
        raise HTTPException(404, "todavia no hay escenas: ejecuta la etapa Escenas")
    ediciones = etapas["escenas"]["params"].get("ediciones") or {}
    escenas = []
    for e in salida["escenas"]:
        e = dict(e)
        ed = ediciones.get(str(e["scene_number"])) or {}
        for campo in ("image_prompt", "video_prompt"):
            if isinstance(ed.get(campo), str) and ed[campo].strip():
                e[campo] = " ".join(ed[campo].split())
        escenas.append(e)
    return escenas


@router.get("/estudio/proyectos/{pid}/script.json", summary="script.json para la extension (Flow/Vibes)")
def script_json(pid: str):
    datos = {"scenes": [{"scene_number": e["scene_number"], "image_prompt": e["image_prompt"],
                         "video_prompt": e["video_prompt"], "narration": e["narration"]} for e in _escenas(pid)]}
    return Response(json.dumps(datos, ensure_ascii=False, indent=2), media_type="application/json",
                    headers={"Content-Disposition": 'attachment; filename="script.json"'})


@router.get("/estudio/proyectos/{pid}/prompts.txt", summary="Prompts en texto, escena por escena")
def prompts_txt(pid: str):
    bloques = []
    for e in _escenas(pid):
        b = [f"ESCENA {e['scene_number']}  ({e['duracion']:.1f}s)", f"Narracion: {e['narration']}"]
        if e.get("image_prompt"):
            b.append(f"IMAGEN: {e['image_prompt']}")
        if e.get("video_prompt"):
            b.append(f"VIDEO: {e['video_prompt']}")
        bloques.append("\n".join(b))
    return PlainTextResponse("\n\n".join(bloques), headers={"Content-Disposition": 'attachment; filename="prompts.txt"'})


# ------------------------------------------------------------------ archivos

@router.get("/estudio/proyectos/{pid}/archivo/{ruta:path}", summary="Servir una salida del proyecto")
def archivo(pid: str, ruta: str):
    _existe(pid)
    try:
        real = almacen.dentro_de(almacen.dir_proyecto(pid), ruta)
    except ValueError:
        raise HTTPException(400, "ruta no valida")
    if not os.path.isfile(real) or real.endswith(".json"):
        raise HTTPException(404, "no existe")
    return FileResponse(real)


@router.get("/estudio/miniatura/{h}", summary="Miniatura de un recurso del catalogo")
def miniatura(h: str):
    if not re.fullmatch(r"[a-f0-9]{16}", h):
        raise HTTPException(400, "id no valido")
    ruta = recursos.ruta_miniatura(h)
    if not os.path.isfile(ruta):
        raise HTTPException(404, "sin miniatura")
    return FileResponse(ruta, headers={"Cache-Control": "public, max-age=86400"})


@router.get("/estudio/proyectos/{pid}/original/{h}", summary="Archivo original de un recurso")
def original(pid: str, h: str):
    _, _, etapas = grafo.evaluar(_existe(pid)["id"])
    for r in ((etapas["recursos"]["salida"] or {}).get("recursos") or []):
        if r["id"] == h and os.path.isfile(r["ruta"]):
            return FileResponse(r["ruta"])
    raise HTTPException(404, "recurso no encontrado")


def _png_ultimo(ruta, nombre):
    with tempfile.TemporaryDirectory() as tmp:
        destino = os.path.join(tmp, "ultimo.png")
        if not medios.ultimo_fotograma(ruta, destino):
            raise HTTPException(422, "no se pudo leer el ultimo fotograma de ese video")
        with open(destino, "rb") as f:
            datos = f.read()
    base = re.sub(r"[^A-Za-z0-9_-]+", "-", os.path.splitext(nombre)[0]).strip("-")[:60] or "clip"
    return Response(datos, media_type="image/png",
                    headers={"Content-Disposition": f'attachment; filename="{base}-ultimo-fotograma.png"'})


@router.get("/estudio/proyectos/{pid}/original/{h}/ultimo-fotograma", summary="Ultimo fotograma de un video subido")
def original_ultimo(pid: str, h: str):
    _, _, etapas = grafo.evaluar(_existe(pid)["id"])
    for r in ((etapas["recursos"]["salida"] or {}).get("recursos") or []):
        if r["id"] == h and os.path.isfile(r["ruta"]) and r["tipo"] == "video":
            return _png_ultimo(r["ruta"], r["nombre"])
    raise HTTPException(404, "video no encontrado")


@router.post("/estudio/herramientas/ultimo-fotograma", summary="Ultimo fotograma de un clip (segmentos encadenados)")
async def herramienta_ultimo(archivo: UploadFile = File(...)):
    ext = os.path.splitext(archivo.filename or "")[1].lower()
    if ext not in medios.EXT_VIDEO:
        raise HTTPException(400, "sube un video (mp4, mov, webm...)")
    with tempfile.TemporaryDirectory() as tmp:
        ruta = os.path.join(tmp, "clip" + ext)
        with open(ruta, "wb") as f:
            while bloque := await archivo.read(1 << 20):
                f.write(bloque)
        return _png_ultimo(ruta, archivo.filename)


@router.get("/estudio/proyectos/{pid}/descargar", summary="Descargar el MP4 final")
def descargar(pid: str):
    proyecto = _existe(pid)
    ruta = almacen.dir_proyecto(pid, "render", "final.mp4")
    if not os.path.isfile(ruta):
        raise HTTPException(404, "todavia no hay video")
    slug = re.sub(r"[^a-z0-9]+", "-", proyecto["titulo"].lower()).strip("-")[:60] or "video"
    return FileResponse(ruta, filename=f"{slug}-{pid[:6]}.mp4", media_type="video/mp4")


# ------------------------------------------------------------------ asistente

@router.post("/estudio/asistente", summary="Preguntar al asistente (Claude CLI)")
def asistente_preguntar(body: dict = Body(...)):
    """body: {"pregunta": str, "charla"?: id, "proyecto"?: id abierto en pantalla}."""
    pid = body.get("proyecto") or None
    if pid and not almacen.PATRON_ID.match(pid):
        pid = None
    try:
        return asistente.preguntar(body.get("charla"), body.get("pregunta", ""), pid)
    except asistente.ErrorAsistente as e:
        raise HTTPException(400, str(e))


@router.get("/estudio/asistente/{cid}", summary="Estado de una charla con el asistente")
def asistente_ver(cid: str):
    try:
        return asistente.ver(cid)
    except asistente.ErrorAsistente as e:
        raise HTTPException(404, str(e))


# ------------------------------------------------------------------ voz clonada

@router.get("/estudio/voces-clonadas", summary="Voces del servidor de clonacion (si hay uno)")
def voces_clonadas():
    if not voz_clonada.url_base():
        return {"activo": False, "voces": [], "error": None}
    try:
        return {"activo": True, "voces": voz_clonada.listar_voces(), "error": None}
    except Exception as e:  # noqa: BLE001 — el servidor externo puede estar apagado
        return {"activo": True, "voces": [], "error": f"no responde el servidor de voz clonada ({type(e).__name__})"}


@router.post("/estudio/voces-clonadas", summary="Crear una voz a partir de 10-15 s de audio")
async def voces_clonadas_crear(audio: UploadFile = File(...), nombre: str = Form(...),
                               transcripcion: str = Form("")):
    datos = await audio.read()
    if len(datos) > 60 * 1024 * 1024:
        raise HTTPException(413, "con 10-15 segundos de voz basta (maximo 60 MB)")
    try:
        return voz_clonada.crear_voz(nombre.strip()[:80] or "Mi voz", datos, audio.filename, transcripcion.strip()[:2000])
    except voz_clonada.NoConfigurado as e:
        raise HTTPException(400, str(e))
    except Exception as e:  # noqa: BLE001
        raise HTTPException(502, f"el servidor de voz clonada fallo: {e}")


@router.get("/estudio/voces-clonadas/{vid}/audio", summary="Muestra de referencia de una voz")
def voces_clonadas_audio(vid: str):
    try:
        return Response(voz_clonada.audio_voz(vid), media_type="audio/wav")
    except ValueError:
        raise HTTPException(400, "voz invalida")
    except Exception:  # noqa: BLE001
        raise HTTPException(404, "no se pudo traer la muestra")


# ------------------------------------------------------------------ miniatura

@router.get("/estudio/proyectos/{pid}/miniatura", summary="Conceptos, referencia y miniatura final")
def miniatura_ver(pid: str):
    _existe(pid)
    return portada_video.estado(pid)


@router.post("/estudio/proyectos/{pid}/miniatura/generar", summary="Claude propone conceptos y prompts")
def miniatura_generar(pid: str, body: dict = Body(default={})):
    _existe(pid)
    params = {k: body[k] for k in portada_video.DEFECTOS if k in body}
    try:
        portada_video.generar(pid, params)
    except RuntimeError as e:
        raise HTTPException(409, str(e))
    return portada_video.estado(pid)


@router.post("/estudio/proyectos/{pid}/miniatura/{tipo}", summary="Subir la referencia o la miniatura final")
async def miniatura_subir(pid: str, tipo: str, archivo: UploadFile = File(...)):
    _existe(pid)
    if tipo not in ("referencia", "final"):
        raise HTTPException(404, "tipo desconocido")
    datos = await archivo.read()
    if len(datos) > 25 * 1024 * 1024:
        raise HTTPException(413, "la imagen no puede pasar de 25 MB")
    try:
        portada_video.guardar_archivo(pid, tipo, datos)
    except ValueError as e:
        raise HTTPException(400, str(e))
    return portada_video.estado(pid)


@router.delete("/estudio/proyectos/{pid}/miniatura/{tipo}", summary="Quitar la referencia o la final")
def miniatura_quitar(pid: str, tipo: str):
    _existe(pid)
    if tipo not in ("referencia", "final"):
        raise HTTPException(404, "tipo desconocido")
    portada_video.quitar_archivo(pid, tipo)
    return portada_video.estado(pid)


@router.get("/estudio/proyectos/{pid}/miniatura-descargar", summary="Descargar la miniatura final")
def miniatura_descargar(pid: str):
    proyecto = _existe(pid)
    final = portada_video.estado(pid)["final"]
    if not final:
        raise HTTPException(404, "todavia no hay miniatura final")
    ruta = almacen.dir_proyecto(pid, final)
    slug = re.sub(r"[^a-z0-9]+", "-", proyecto["titulo"].lower()).strip("-")[:60] or "miniatura"
    return FileResponse(ruta, filename=f"{slug}-miniatura{os.path.splitext(ruta)[1]}")


# ------------------------------------------------------------------ prompts maestros

def _maestro(mid):
    if not almacen.PATRON_ID.match(mid or ""):
        raise HTTPException(404, "prompt maestro no encontrado")
    try:
        return maestros.cargar(mid)
    except maestros.ErrorMaestro as e:
        raise HTTPException(404, str(e))


@router.get("/estudio/maestros", summary="Biblioteca de prompts maestros")
def maestros_listar():
    return {"maestros": maestros.listar()}


@router.post("/estudio/maestros", summary="Subir un prompt maestro (.docx/.txt/.md o texto) y desglosarlo")
async def maestros_crear(archivo: UploadFile | None = File(None), texto: str = Form(""), nombre: str = Form(""),
                         modelo: str = Form(""), esfuerzo: str = Form("")):
    try:
        if archivo is not None and archivo.filename:
            datos = await archivo.read()
            if len(datos) > 30 * 1024 * 1024:
                raise HTTPException(413, "el archivo no puede pasar de 30 MB")
            contenido, portada = maestros.extraer(archivo.filename, datos)
            origen = archivo.filename
            nombre = nombre or os.path.splitext(archivo.filename)[0].replace("_", " ").strip()
        else:
            contenido, portada, origen = texto, None, "texto pegado"
        return maestros.crear(nombre, contenido, origen, portada, modelo or None, esfuerzo or None)
    except maestros.ErrorMaestro as e:
        raise HTTPException(400, str(e))


@router.get("/estudio/maestros/{mid}", summary="Ficha de un prompt maestro")
def maestros_ver(mid: str):
    return _maestro(mid)


@router.get("/estudio/maestros/{mid}/original", summary="Texto original del prompt maestro")
def maestros_original(mid: str):
    _maestro(mid)
    return PlainTextResponse(maestros.texto_original(mid))


@router.get("/estudio/maestros/{mid}/portada", summary="Portada del prompt maestro")
def maestros_portada(mid: str):
    _maestro(mid)
    ruta = os.path.join(almacen.raiz("maestros"), mid, "portada.jpg")
    if not os.path.isfile(ruta):
        raise HTTPException(404, "sin portada")
    return FileResponse(ruta, media_type="image/jpeg")


@router.post("/estudio/maestros/{mid}/portada", summary="Poner una portada propia")
async def maestros_poner_portada(mid: str, archivo: UploadFile = File(...)):
    _maestro(mid)
    datos = await archivo.read()
    if len(datos) > 20 * 1024 * 1024:
        raise HTTPException(413, "la imagen no puede pasar de 20 MB")
    try:
        return maestros.poner_portada(mid, datos)
    except maestros.ErrorMaestro as e:
        raise HTTPException(400, str(e))


@router.delete("/estudio/maestros/{mid}/portada", summary="Quitar la portada")
def maestros_quitar_portada(mid: str):
    _maestro(mid)
    return maestros.quitar_portada(mid)


@router.patch("/estudio/maestros/{mid}", summary="Renombrar, notas o corregir la ficha")
def maestros_editar(mid: str, body: dict = Body(...)):
    _maestro(mid)
    return maestros.editar(mid, body)


@router.post("/estudio/maestros/{mid}/analizar", summary="Volver a desglosar con Claude")
def maestros_analizar(mid: str, body: dict = Body(default={})):
    _maestro(mid)
    try:
        maestros.analizar(mid, body.get("modelo") or None, body.get("esfuerzo") or None)
    except maestros.ErrorMaestro as e:
        raise HTTPException(409, str(e))
    return maestros.cargar(mid)


@router.delete("/estudio/maestros/{mid}", summary="Borrar un prompt maestro")
def maestros_borrar(mid: str):
    _maestro(mid)
    maestros.borrar(mid)
    return {"ok": True}


# ------------------------------------------------------------------ crear contenido con un prompt maestro

def _creacion(mid, cid):
    _maestro(mid)
    if not almacen.PATRON_ID.match(cid or ""):
        raise HTTPException(404, "creacion no encontrada")
    try:
        return creaciones.cargar(mid, cid)
    except creaciones.ErrorCreacion as e:
        raise HTTPException(404, str(e))


@router.get("/estudio/maestros/{mid}/creaciones", summary="Creaciones hechas con un prompt maestro")
def creaciones_listar(mid: str):
    _maestro(mid)
    return {"creaciones": creaciones.listar(mid)}


@router.post("/estudio/maestros/{mid}/creaciones", summary="Empezar a crear contenido con el prompt maestro")
def creaciones_crear(mid: str, body: dict = Body(default={})):
    _maestro(mid)
    try:
        return creaciones.crear(mid, body.get("tema", ""), body.get("modo", "guiado"), body.get("modelo", "sonnet"))
    except creaciones.ErrorCreacion as e:
        raise HTTPException(400, str(e))


@router.get("/estudio/maestros/{mid}/creaciones/{cid}", summary="Estado de una creacion")
def creaciones_ver(mid: str, cid: str):
    return _creacion(mid, cid)


@router.post("/estudio/maestros/{mid}/creaciones/{cid}/mensaje", summary="Responder en la creacion")
def creaciones_mensaje(mid: str, cid: str, body: dict = Body(...)):
    _creacion(mid, cid)
    try:
        return creaciones.enviar(mid, cid, body.get("texto", ""))
    except creaciones.ErrorCreacion as e:
        raise HTTPException(409, str(e))


@router.post("/estudio/maestros/{mid}/creaciones/{cid}/reintentar", summary="Repetir el turno que fallo")
def creaciones_reintentar(mid: str, cid: str):
    _creacion(mid, cid)
    try:
        return creaciones.reintentar(mid, cid)
    except creaciones.ErrorCreacion as e:
        raise HTTPException(409, str(e))


@router.post("/estudio/maestros/{mid}/creaciones/{cid}/entregables", summary="Ordenar lo producido en entregables")
def creaciones_entregables(mid: str, cid: str):
    _creacion(mid, cid)
    try:
        return creaciones.preparar_entregables(mid, cid)
    except creaciones.ErrorCreacion as e:
        raise HTTPException(409, str(e))


@router.put("/estudio/maestros/{mid}/creaciones/{cid}/escenas", summary="Editar a mano las escenas (unir, quitar, duracion)")
def creaciones_escenas(mid: str, cid: str, body: dict = Body(...)):
    _creacion(mid, cid)
    try:
        return creaciones.editar_escenas(mid, cid, body.get("escenas"))
    except creaciones.ErrorCreacion as e:
        raise HTTPException(400, str(e))


@router.put("/estudio/maestros/{mid}/creaciones/{cid}/referencias", summary="Quitar referencias o corregir su prompt")
def creaciones_referencias(mid: str, cid: str, body: dict = Body(...)):
    _creacion(mid, cid)
    try:
        return creaciones.editar_referencias(mid, cid, body.get("referencias"))
    except creaciones.ErrorCreacion as e:
        raise HTTPException(400, str(e))


@router.post("/estudio/maestros/{mid}/creaciones/{cid}/referencias/proponer", summary="Claude propone hojas de referencia")
def creaciones_proponer_referencias(mid: str, cid: str):
    _creacion(mid, cid)
    try:
        return creaciones.proponer_referencias(mid, cid)
    except creaciones.ErrorCreacion as e:
        raise HTTPException(400, str(e))
    except claude_cli.LimiteAgotado as e:
        raise HTTPException(429, str(e))


@router.get("/estudio/maestros/{mid}/creaciones/{cid}/referencias/{k}", summary="Imagen de una hoja de referencia")
def creaciones_ver_referencia(mid: str, cid: str, k: str):
    _creacion(mid, cid)
    ruta = referencias.ruta_imagen(mid, cid, referencias.clave(k))
    if not ruta:
        raise HTTPException(404, "sin imagen")
    return FileResponse(ruta, filename=os.path.basename(ruta))


@router.post("/estudio/maestros/{mid}/creaciones/{cid}/referencias/{k}", summary="Subir la imagen de una referencia")
async def creaciones_subir_referencia(mid: str, cid: str, k: str, archivo: UploadFile = File(...)):
    _creacion(mid, cid)
    datos = await archivo.read()
    if len(datos) > 30 * 1024 * 1024:
        raise HTTPException(413, "la imagen no puede pasar de 30 MB")
    try:
        return creaciones.subir_referencia(mid, cid, referencias.clave(k), datos)
    except creaciones.ErrorCreacion as e:
        raise HTTPException(400, str(e))


@router.delete("/estudio/maestros/{mid}/creaciones/{cid}/referencias/{k}", summary="Quitar la imagen de una referencia")
def creaciones_quitar_referencia(mid: str, cid: str, k: str):
    _creacion(mid, cid)
    return creaciones.quitar_referencia(mid, cid, k)


@router.post("/estudio/maestros/{mid}/creaciones/{cid}/video", summary="Crear un proyecto del Estudio con la creacion")
def creaciones_video(mid: str, cid: str, body: dict = Body(...)):
    _creacion(mid, cid)
    try:
        proyecto = creaciones.crear_video(mid, cid, body.get("narracion", ""), body.get("aspecto") or None,
                                          body.get("voz") or None, body.get("titulo") or None)
    except creaciones.ErrorCreacion as e:
        raise HTTPException(400, str(e))
    except claude_cli.LimiteAgotado as e:
        raise HTTPException(429, str(e))
    return {"proyecto": proyecto}


@router.patch("/estudio/maestros/{mid}/creaciones/{cid}", summary="Renombrar o cambiar de modo (guiado/auto)")
def creaciones_cambiar(mid: str, cid: str, body: dict = Body(...)):
    _creacion(mid, cid)
    try:
        return creaciones.cambiar(mid, cid, body)
    except creaciones.ErrorCreacion as e:
        raise HTTPException(409, str(e))


@router.delete("/estudio/maestros/{mid}/creaciones/{cid}", summary="Borrar una creacion")
def creaciones_borrar(mid: str, cid: str):
    _creacion(mid, cid)
    try:
        creaciones.borrar(mid, cid)
    except creaciones.ErrorCreacion as e:
        raise HTTPException(409, str(e))
    return {"ok": True}
