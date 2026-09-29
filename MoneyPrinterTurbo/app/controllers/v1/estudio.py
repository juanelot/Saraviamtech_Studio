"""
API del Estudio: proyectos por etapas (guion -> voz -> recursos -> asignacion
-> render) con los recursos de la persona y Claude CLI como cerebro.

Todas las rutas cuelgan de /api/v1/estudio.
"""
import os
import re
import shutil

from fastapi import Body, File, HTTPException, UploadFile
from fastapi.responses import FileResponse

from app.controllers.v1.base import new_router
from app.services.estudio import almacen, grafo, medios, recursos

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
        salida.append({"id": p["id"], "titulo": p["titulo"], "creado": p["creado"],
                       "actualizado": p["actualizado"], "mp4": render.get("mp4"),
                       "duracion": render.get("duracion"),
                       "trabajando": grafo.trabajo(p["id"])[0] is not None})
    return {"proyectos": salida}


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
    for n in sorted(os.listdir(carpeta), key=str.lower):
        ruta = os.path.join(carpeta, n)
        if os.path.isfile(ruta) and medios.tipo_de(ruta):
            archivos.append({"nombre": n, "tipo": medios.tipo_de(ruta), "tam": os.path.getsize(ruta)})
    return {"archivos": archivos}


@router.post("/estudio/proyectos/{pid}/recursos", summary="Subir imagenes o videos")
def subir(pid: str, archivos: list[UploadFile] = File(...)):
    _existe(pid)
    carpeta = almacen.dir_proyecto(pid, "recursos", crear=True)
    guardados, rechazados = [], []
    for a in archivos:
        nombre = NOMBRE_SEGURO.sub("_", os.path.basename(a.filename or "")).strip() or "archivo"
        if not medios.tipo_de(nombre):
            rechazados.append(a.filename)
            continue
        destino = almacen.dentro_de(carpeta, nombre)
        with open(destino + ".part", "wb") as f:
            shutil.copyfileobj(a.file, f, 1 << 20)
        os.replace(destino + ".part", destino)
        guardados.append(nombre)
    return {"guardados": guardados, "rechazados": rechazados}


@router.delete("/estudio/proyectos/{pid}/recursos/{nombre}", summary="Quitar un archivo subido")
def quitar(pid: str, nombre: str):
    _existe(pid)
    try:
        ruta = almacen.dentro_de(almacen.dir_proyecto(pid, "recursos"), nombre)
    except ValueError:
        raise HTTPException(400, "nombre no valido")
    if os.path.isfile(ruta):
        os.remove(ruta)
    return {"ok": True}


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


@router.get("/estudio/proyectos/{pid}/descargar", summary="Descargar el MP4 final")
def descargar(pid: str):
    proyecto = _existe(pid)
    ruta = almacen.dir_proyecto(pid, "render", "final.mp4")
    if not os.path.isfile(ruta):
        raise HTTPException(404, "todavia no hay video")
    slug = re.sub(r"[^a-z0-9]+", "-", proyecto["titulo"].lower()).strip("-")[:60] or "video"
    return FileResponse(ruta, filename=f"{slug}-{pid[:6]}.mp4", media_type="video/mp4")
