"""
El grafo de etapas del Estudio (idea de AS Video Studio, simplificada).

    guion ──► voz ──┬──────────────┐
                    └─► escenas ···┤  (solo en modo "escenas")
    recursos ──────────────────────┴──► asignacion ──► render

La dependencia asignacion -> escenas existe SOLO si asignacion.modo == "escenas"
(ver deps_de): asi los proyectos en modo "claude"/"orden" no ven cambiar su firma
por una etapa que no usan.

Cada etapa guarda la FIRMA de sus entradas: sus params efectivos + la firma de
salida de las etapas de las que depende (+ una huella extra si la etapa la
declara, p. ej. el listado de archivos de recursos). Si la firma calculada no
cuadra con la guardada, la etapa esta OBSOLETA, y en cascada todo lo que cuelga.

Ejecutar "hasta X" corre SOLO lo obsoleto o pendiente que X necesita. Cambiar
un parametro de render no vuelve a llamar a Claude ni a sintetizar la voz.

Contrato de cada modulo de etapa:
    DEFECTOS: dict           params por defecto
    ejecutar(ctx) -> dict    salida pequena (se guarda en estado.json)
    huella(ctx) -> any       opcional: datos extra que entran en la firma
"""
import hashlib
import json
import threading
import time
import traceback
from collections import deque

from loguru import logger

import app.config  # noqa: F401  -- configura loguru ANTES de anadir sinks (hace logger.remove())
from app.services.estudio import almacen

ETAPAS = ["guion", "voz", "escenas", "recursos", "asignacion", "render"]
# Dependencias maximas (la de asignacion -> escenas depende del modo: deps_de).
DEPS = {
    "guion": [],
    "voz": ["guion"],
    "escenas": ["voz"],
    "recursos": [],
    "asignacion": ["voz", "recursos", "escenas"],
    "render": ["asignacion", "voz"],
}


def deps_de(proyecto, etapa):
    if etapa == "asignacion":
        modo = ((proyecto.get("params") or {}).get("asignacion") or {}).get("modo", "claude")
        return ["voz", "recursos", "escenas"] if modo == "escenas" else ["voz", "recursos"]
    return DEPS[etapa]


class Cancelado(Exception):
    pass


def modulo(etapa):
    from app.services.estudio import asignacion, escenas, guion, recursos, render, voz

    return {"guion": guion, "voz": voz, "escenas": escenas, "recursos": recursos,
            "asignacion": asignacion, "render": render}[etapa]


def params_efectivos(proyecto, etapa):
    base = dict(getattr(modulo(etapa), "DEFECTOS", {}))
    base.update(proyecto.get("params", {}).get(etapa) or {})
    return base


def _hash(obj) -> str:
    texto = json.dumps(obj, sort_keys=True, ensure_ascii=False, default=str)
    return hashlib.sha256(texto.encode("utf-8")).hexdigest()[:20]


def cierre(hasta, proyecto):
    """Las etapas que `hasta` necesita, en orden de ejecucion."""
    necesarias = set()

    def subir(e):
        if e in necesarias:
            return
        necesarias.add(e)
        for d in deps_de(proyecto, e):
            subir(d)

    subir(hasta)
    return [e for e in ETAPAS if e in necesarias]


# ------------------------------------------------------------------ contexto

class Contexto:
    def __init__(self, pid, proyecto, estado, etapa, vivo=None):
        self.pid = pid
        self.proyecto = proyecto
        self.etapa = etapa
        self.params = params_efectivos(proyecto, etapa)
        self.salidas = {d: (estado["etapas"].get(d) or {}).get("salida") for d in deps_de(proyecto, etapa)}
        self._vivo = vivo

    def dir(self, *partes, crear=True):
        return almacen.dir_proyecto(self.pid, *partes, crear=crear)

    def params_de(self, etapa):
        return params_efectivos(self.proyecto, etapa)

    def avisar(self, mensaje=None, progreso=None):
        if self._vivo is not None:
            if self._vivo["cancelar"].is_set():
                raise Cancelado("cancelado por la persona")
            if progreso is not None:
                self._vivo["trabajo"]["progreso"] = max(0, min(100, int(progreso)))
            if mensaje:
                self._vivo["trabajo"]["mensaje"] = mensaje
                _anotar(self._vivo, mensaje)

    def cancelado(self):
        return self._vivo is not None and self._vivo["cancelar"].is_set()


def firma_entrada(pid, proyecto, estado, etapa):
    ctx = Contexto(pid, proyecto, estado, etapa)
    mod = modulo(etapa)
    extra = mod.huella(ctx) if hasattr(mod, "huella") else None
    deps = {d: (estado["etapas"].get(d) or {}).get("firma_salida") for d in deps_de(proyecto, etapa)}
    return _hash({"params": ctx.params, "deps": deps, "extra": extra})


# ------------------------------------------------------------------ evaluacion

_vivos = {}          # pid -> {"hilo", "cancelar", "trabajo", "log"}
_vivos_candado = threading.Lock()


def _anotar(vivo, linea):
    vivo["log"].append(f"{time.strftime('%H:%M:%S')} {linea}")


def evaluar(pid):
    """Estado de cada etapa: ok | obsoleta | pendiente | error | ejecutando."""
    proyecto = almacen.cargar(pid)
    estado = almacen.cargar_estado(pid)
    vivo = _vivos.get(pid)
    etapa_viva = vivo["trabajo"]["etapa"] if vivo else None
    vista = {}
    for e in ETAPAS:
        reg = estado["etapas"].get(e) or {}
        calc = firma_entrada(pid, proyecto, estado, e)
        deps_ok = all(vista[d]["estado"] == "ok" for d in deps_de(proyecto, e))
        if e == etapa_viva:
            est = "ejecutando"
        elif reg.get("error") and reg.get("firma_error") == calc:
            est = "error"
        elif not reg.get("salida"):
            est = "pendiente"
        elif reg.get("firma") != calc or not deps_ok:
            est = "obsoleta"
        else:
            est = "ok"
        vista[e] = {
            "estado": est,
            "salida": reg.get("salida"),
            "error": reg.get("error"),
            "duracion_s": reg.get("duracion_s"),
            "terminado": reg.get("terminado"),
            "params": params_efectivos(proyecto, e),
        }
    return proyecto, estado, vista


def trabajo(pid):
    vivo = _vivos.get(pid)
    if not vivo:
        return None, list(almacen.cargar_estado(pid).get("log", []))[-200:]
    return dict(vivo["trabajo"]), list(vivo["log"])[-200:]


# ------------------------------------------------------------------ ejecucion

def lanzar(pid, hasta, forzar=()):
    if hasta not in ETAPAS:
        raise ValueError(f"etapa desconocida: {hasta}")
    almacen.cargar(pid)  # existe
    with _vivos_candado:
        if pid in _vivos:
            raise RuntimeError("este proyecto ya tiene un trabajo en marcha")
        previo = almacen.cargar_estado(pid).get("log", [])[-150:]
        vivo = {
            "cancelar": threading.Event(),
            "trabajo": {"hasta": hasta, "etapa": None, "progreso": 0,
                        "mensaje": "arrancando", "inicio": time.time()},
            "log": deque(previo, maxlen=600),
        }
        _vivos[pid] = vivo
        hilo = threading.Thread(target=_correr, args=(pid, hasta, set(forzar), vivo),
                                daemon=True, name=f"estudio-{pid}")
        vivo["hilo"] = hilo
        hilo.start()


def cancelar(pid):
    vivo = _vivos.get(pid)
    if not vivo:
        return False
    vivo["cancelar"].set()
    _anotar(vivo, "cancelacion pedida: se para al terminar el paso en curso")
    return True


def _persistir_log(pid, vivo):
    with almacen.candado(pid):
        estado = almacen.cargar_estado(pid)
        estado["log"] = list(vivo["log"])
        almacen.guardar_estado(pid, estado)


def _correr(pid, hasta, forzar, vivo):
    hilo_id = threading.get_ident()
    sink = logger.add(
        lambda m: _anotar(vivo, m.record["message"].strip()[:400]),
        level="INFO",
        filter=lambda r: r["thread"].id == hilo_id,
        format="{message}",
    )
    _anotar(vivo, f"== ejecutar hasta «{hasta}»")
    try:
        for etapa in cierre(hasta, almacen.cargar(pid)):
            proyecto, estado, vista = evaluar(pid)
            if vista[etapa]["estado"] == "ok" and etapa not in forzar:
                _anotar(vivo, f"[{etapa}] al dia, se reutiliza")
                continue
            for d in deps_de(proyecto, etapa):
                if vista[d]["estado"] != "ok":
                    raise RuntimeError(f"no se puede ejecutar {etapa}: {d} no esta al dia")
            _ejecutar_etapa(pid, etapa, vivo)
        _anotar(vivo, "== listo")
    except Cancelado:
        _anotar(vivo, "== cancelado")
    except Exception as e:  # noqa: BLE001
        _anotar(vivo, f"== fallo: {e}")
        _anotar(vivo, traceback.format_exc()[-1500:])
    finally:
        try:
            logger.remove(sink)
        except ValueError:
            pass
        try:
            _persistir_log(pid, vivo)
        finally:
            with _vivos_candado:
                _vivos.pop(pid, None)


def _ejecutar_etapa(pid, etapa, vivo):
    proyecto = almacen.cargar(pid)
    estado = almacen.cargar_estado(pid)
    firma = firma_entrada(pid, proyecto, estado, etapa)
    vivo["trabajo"].update({"etapa": etapa, "progreso": 0, "mensaje": f"{etapa}: empezando"})
    _anotar(vivo, f"[{etapa}] empezando")
    ctx = Contexto(pid, proyecto, estado, etapa, vivo)
    t0 = time.time()
    try:
        salida = modulo(etapa).ejecutar(ctx)
    except Cancelado:
        vivo["trabajo"]["etapa"] = None
        _registrar(pid, etapa, error="cancelado", firma_error=firma)
        raise
    except Exception as e:  # noqa: BLE001
        vivo["trabajo"]["etapa"] = None
        logger.error(traceback.format_exc())
        _registrar(pid, etapa, error=str(e)[:1000], firma_error=firma)
        raise
    duracion = round(time.time() - t0, 1)
    _registrar(pid, etapa, salida=salida, firma=firma, duracion_s=duracion)
    vivo["trabajo"]["etapa"] = None
    _anotar(vivo, f"[{etapa}] listo en {duracion}s")


def _registrar(pid, etapa, salida=None, firma=None, duracion_s=None, error=None, firma_error=None):
    with almacen.candado(pid):
        estado = almacen.cargar_estado(pid)
        reg = estado["etapas"].get(etapa) or {}
        if error is not None:
            reg.update({"error": error, "firma_error": firma_error})
        else:
            reg.update({
                "salida": salida, "firma": firma, "firma_salida": _hash(salida),
                "duracion_s": duracion_s, "terminado": time.time(),
                "error": None, "firma_error": None,
            })
        estado["etapas"][etapa] = reg
        almacen.guardar_estado(pid, estado)
