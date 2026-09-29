"""
Donde viven los proyectos del Estudio y como se leen/escriben.

    storage/estudio/
        proyectos/<id>/
            proyecto.json   titulo + params de cada etapa (lo que edita la persona)
            estado.json     firma y salida de cada etapa, trabajo en curso, log
            recursos/       lo que sube la persona (imagenes y videos)
            guion/ voz/ asignacion/ render/   salidas de cada etapa
        catalogo/
            miniaturas/<hash>.jpg   una por recurso (videos: hoja de 3 fotogramas)
            fichas.json             metadatos + descripcion por hash de contenido

El catalogo es GLOBAL y va por hash de contenido: el mismo archivo usado en dos
proyectos se describe una sola vez.
"""
import json
import os
import re
import tempfile
import threading
import time
import uuid

from app.utils import utils

_candados = {}
_candado_global = threading.Lock()

PATRON_ID = re.compile(r"^[a-f0-9]{12}$")


def raiz(*partes):
    ruta = os.path.join(utils.storage_dir("estudio", create=True), *partes)
    return ruta


def dir_proyectos():
    ruta = raiz("proyectos")
    os.makedirs(ruta, exist_ok=True)
    return ruta


def dir_catalogo(sub: str = ""):
    ruta = raiz("catalogo", sub) if sub else raiz("catalogo")
    os.makedirs(ruta, exist_ok=True)
    return ruta


def validar_id(pid: str):
    if not PATRON_ID.match(pid or ""):
        raise ValueError(f"id de proyecto no valido: {pid!r}")
    return pid


def dir_proyecto(pid: str, *partes, crear=False):
    ruta = os.path.join(dir_proyectos(), validar_id(pid), *partes)
    if crear:
        os.makedirs(ruta, exist_ok=True)
    return ruta


def candado(clave: str) -> threading.RLock:
    with _candado_global:
        if clave not in _candados:
            _candados[clave] = threading.RLock()
        return _candados[clave]


def leer_json(ruta, defecto=None):
    try:
        with open(ruta, encoding="utf-8") as f:
            return json.load(f)
    except FileNotFoundError:
        return defecto
    except json.JSONDecodeError:
        return defecto


def escribir_json(ruta, datos):
    """Escritura atomica: un corte a mitad no deja un JSON roto."""
    os.makedirs(os.path.dirname(ruta), exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=os.path.dirname(ruta), suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(datos, f, ensure_ascii=False, indent=1)
        for intento in range(5):
            try:
                os.replace(tmp, ruta)
                return
            except PermissionError:
                # Windows: el archivo puede estar abierto un instante por un lector.
                time.sleep(0.1 * (intento + 1))
        os.replace(tmp, ruta)
    finally:
        if os.path.exists(tmp):
            os.remove(tmp)


# ------------------------------------------------------------------ proyectos

def crear(titulo: str) -> dict:
    pid = uuid.uuid4().hex[:12]
    ahora = time.time()
    proyecto = {"id": pid, "titulo": (titulo or "Video sin titulo").strip()[:200],
                "creado": ahora, "actualizado": ahora, "params": {}}
    dir_proyecto(pid, "recursos", crear=True)
    escribir_json(dir_proyecto(pid, "proyecto.json"), proyecto)
    escribir_json(dir_proyecto(pid, "estado.json"), {"etapas": {}, "trabajo": None, "log": []})
    return proyecto


def cargar(pid: str) -> dict:
    proyecto = leer_json(dir_proyecto(pid, "proyecto.json"))
    if proyecto is None:
        raise FileNotFoundError(f"proyecto {pid} no existe")
    proyecto.setdefault("params", {})
    return proyecto


def guardar(proyecto: dict):
    proyecto["actualizado"] = time.time()
    escribir_json(dir_proyecto(proyecto["id"], "proyecto.json"), proyecto)


def cargar_estado(pid: str) -> dict:
    estado = leer_json(dir_proyecto(pid, "estado.json"), {}) or {}
    estado.setdefault("etapas", {})
    estado.setdefault("trabajo", None)
    estado.setdefault("log", [])
    return estado


def guardar_estado(pid: str, estado: dict):
    estado["log"] = estado.get("log", [])[-400:]
    escribir_json(dir_proyecto(pid, "estado.json"), estado)


def listar() -> list:
    salida = []
    for pid in os.listdir(dir_proyectos()):
        if not PATRON_ID.match(pid):
            continue
        p = leer_json(os.path.join(dir_proyectos(), pid, "proyecto.json"))
        if p:
            salida.append(p)
    salida.sort(key=lambda p: p.get("actualizado", 0), reverse=True)
    return salida


def dentro_de(base: str, ruta: str) -> str:
    """Resuelve `ruta` y exige que quede dentro de `base` (sin ../)."""
    base_real = os.path.realpath(base)
    real = os.path.realpath(os.path.join(base_real, ruta))
    if real != base_real and not real.startswith(base_real + os.sep):
        raise ValueError("ruta fuera de la carpeta permitida")
    return real
