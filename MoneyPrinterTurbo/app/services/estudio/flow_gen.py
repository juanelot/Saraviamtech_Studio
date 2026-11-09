"""
Imagenes de las escenas generadas en Google Flow (Nano Banana, gratis), SOLO en la
maquina local (config `estudio_flow_habilitado`). Automatiza el paso manual del modo
escenas: en vez de bajar script.json, usar la extension y subir images/, se lanza
tools/flow/lote.js, que maneja el Chrome dedicado y deja cada imagen directamente en
recursos/images/scene_NNNN.<ext>.

El ARCHIVO manda (como en la extension): una escena con imagen en recursos/images
esta hecha; sin archivo, esta pendiente. flow/estado.json solo guarda lo que no se
ve en los archivos (fallos, intentos, motivo, como acabo la ultima corrida), asi
que reiniciar el backend o apagar la maquina no pierde nada.

Una sola generacion a la vez en toda la maquina: Flow solo admite una accion.
"""
import json
import os
import shutil
import subprocess
import threading
import time

from loguru import logger

from app.config import config
from app.services.estudio import almacen, medios, recursos
from app.utils import utils

SIN_VENTANA = {"creationflags": getattr(subprocess, "CREATE_NO_WINDOW", 0x08000000)} if os.name == "nt" else {}
CODIGOS = {0: "fin", 2: "detenido", 3: "sin_sesion", 4: "limite"}
MODELOS = ("pro", "2", "lite")

_actual = {}            # {"pid", "proceso", "hilo"} de la corrida en marcha
_candado = threading.Lock()


class NoHabilitado(RuntimeError):
    pass


def habilitado():
    return bool(config.app.get("estudio_flow_habilitado", False))


def _dir_flow():
    d = (config.app.get("estudio_flow_dir", "") or "").strip()
    return os.path.abspath(d or os.path.join(utils.root_dir(), "..", "tools", "flow"))


def _node():
    ruta = shutil.which("node")
    if not ruta:
        raise RuntimeError("no se encontro Node.js (hace falta Node 18+ para generar en Flow)")
    return ruta


def _exigir():
    if not habilitado():
        raise NoHabilitado("Flow no esta habilitado en esta maquina (estudio_flow_habilitado)")
    if not os.path.isfile(os.path.join(_dir_flow(), "node_modules", "playwright-core", "package.json")):
        raise RuntimeError(f"falta instalar el generador: ejecuta `npm install` en {_dir_flow()}")


def _cli(*args, timeout=60):
    _exigir()
    r = subprocess.run([_node(), os.path.join(_dir_flow(), "cli.js"), *args], cwd=_dir_flow(),
                       capture_output=True, text=True, encoding="utf-8", errors="replace",
                       timeout=timeout, **SIN_VENTANA)
    lineas = [x for x in (r.stdout or "").splitlines() if x.strip().startswith("{")]
    if not lineas:
        raise RuntimeError((r.stderr or r.stdout or "sin respuesta del generador de Flow").strip()[-300:])
    return json.loads(lineas[-1])


def sesion():
    """{"chrome", "sesion", "ocupado"}: sesion None = Chrome cerrado (no se sabe)."""
    return _cli("sesion")


def conectar():
    """Abre el Chrome de Flow (perfil dedicado) para iniciar sesion una vez."""
    return _cli("chrome")


def cerrar():
    """Cierra el Chrome de Flow (no borra la sesion de Google: queda en el perfil)."""
    if corriendo():
        raise RuntimeError("Flow esta generando: detén la generacion antes de desconectar")
    return _cli("cerrar")


# ------------------------------------------------------------------ estado

def _ruta_estado(pid):
    return almacen.dir_proyecto(pid, "flow", "estado.json")


def _leer(pid):
    return almacen.leer_json(_ruta_estado(pid), {}) or {}


def _imagenes(pid):
    """{escena: archivo} de las que ya tienen imagen en recursos/ (en images/ o
    suelta: asignacion._por_escenas acepta las dos), como la extension."""
    carpeta = almacen.dir_proyecto(pid, "recursos")
    hechas = {}
    for base, _dirs, nombres in os.walk(carpeta):
        for n in nombres:
            ruta = os.path.join(base, n)
            if n.endswith(".part") or medios.tipo_de(ruta) != "imagen":
                continue
            rel = os.path.relpath(ruta, carpeta).replace("\\", "/")
            k = recursos.numero_escena(rel)
            if k is not None and (k not in hechas or recursos.subcarpeta_de(rel) == "images"):
                hechas[k] = rel
    return hechas


def corriendo(pid=None):
    with _candado:
        vivo = bool(_actual) and _actual["proceso"].poll() is None
        return vivo and (pid is None or _actual["pid"] == pid)


def estado(pid, escenas):
    """Progreso por escena. `escenas` = las del proyecto (con ediciones aplicadas)."""
    datos = _leer(pid)
    hechas = _imagenes(pid)
    en_marcha = corriendo(pid) and _actual.get("tipo") != "video"   # Veo tiene su propio estado (estado_videos)
    por_escena = datos.get("escenas") or {}
    filas = []
    for e in escenas:
        n = e["scene_number"]
        info = por_escena.get(str(n)) or {}
        if not (e.get("image_prompt") or "").strip():
            est = "sin_prompt"
        elif n in hechas:
            est = "lista"
        elif en_marcha and info.get("estado") in ("generando", "intento"):
            est = "en_curso"
        elif info.get("estado") == "error":
            est = "error"
        else:
            est = "pendiente"
        filas.append({"escena": n, "estado": est, "archivo": hechas.get(n),
                      "intento": info.get("intento"), "motivo": info.get("motivo") or ""})
    cuenta = {k: sum(1 for f in filas if f["estado"] == k) for k in ("lista", "pendiente", "error", "en_curso", "sin_prompt")}
    return {"habilitado": True, "corriendo": en_marcha, "otro_proyecto": corriendo() and not en_marcha,
            "deteniendo": en_marcha and os.path.exists(_ruta_detener(pid)),
            "resultado": None if en_marcha else datos.get("resultado"), "motivo": datos.get("motivo") or "",
            "pasada": datos.get("pasada"), "inicio": datos.get("inicio"), "fin": datos.get("fin"),
            "cuenta": cuenta, "escenas": filas, "log": (datos.get("log") or [])[-30:]}


def _ruta_detener(pid):
    return almacen.dir_proyecto(pid, "flow", ".detener")


# ------------------------------------------------------------------ corrida

def iniciar(pid, escenas, aspecto, reintentar_fallidas=True):
    """Lanza el lote en segundo plano. Solo las escenas sin imagen; las que fallaron
    en una corrida anterior entran salvo reintentar_fallidas=False."""
    _exigir()
    previo = _leer(pid)
    hechas = _imagenes(pid)
    excluir = set()
    if not reintentar_fallidas:
        excluir = {int(k) for k, v in (previo.get("escenas") or {}).items() if v.get("estado") == "error"}
    elegidas = [e for e in escenas if (e.get("image_prompt") or "").strip()
                and e["scene_number"] not in hechas and e["scene_number"] not in excluir]
    if not elegidas:
        raise ValueError("no hay escenas pendientes con prompt de imagen")

    modelo = str(config.app.get("estudio_flow_modelo", "2") or "2")
    if modelo not in MODELOS:
        modelo = "2"
    carpeta = almacen.dir_proyecto(pid, "flow", crear=True)
    script = os.path.join(carpeta, "script.json")
    almacen.escribir_json(script, {"scenes": [{"scene_number": e["scene_number"], "image_prompt": e["image_prompt"],
                                               "video_prompt": e.get("video_prompt", ""),
                                               "narration": e.get("narration", "")} for e in elegidas]})
    detener = _ruta_detener(pid)
    if os.path.exists(detener):
        os.remove(detener)
    salida = almacen.dir_proyecto(pid, "recursos", "images", crear=True)
    orden = [_node(), os.path.join(_dir_flow(), "lote.js"), "--script", script, "--out", salida,
             "--aspect", aspecto if aspecto in ("16:9", "9:16", "1:1", "4:3", "3:4") else "16:9",
             "--model", modelo, "--pasadas-extra", str(int(config.app.get("estudio_flow_pasadas_extra", 2) or 0)),
             "--detener", detener]

    with _candado:
        if _actual and _actual["proceso"].poll() is None:
            otro = _actual["pid"]
            raise RuntimeError("ya se esta generando en Flow" + ("" if otro == pid else " para otro proyecto"))
        # Se conservan los fallos previos (motivo) hasta que la escena se vuelva a intentar.
        datos = {"escenas": {k: v for k, v in (previo.get("escenas") or {}).items() if v.get("estado") == "error"},
                 "inicio": time.time(), "fin": None, "pasada": 1, "resultado": None, "motivo": "",
                 "log": (previo.get("log") or [])[-100:]}
        _anotar(datos, f"inicio: {len(elegidas)} escenas ({len(hechas)} ya tenian imagen)")
        almacen.escribir_json(_ruta_estado(pid), datos)
        proceso = subprocess.Popen(orden, cwd=_dir_flow(), stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                   text=True, encoding="utf-8", errors="replace", **SIN_VENTANA)
        hilo = threading.Thread(target=_seguir, args=(pid, proceso, datos), daemon=True, name=f"flow-{pid}")
        _actual.clear()
        _actual.update({"pid": pid, "proceso": proceso, "hilo": hilo})
        hilo.start()
    return {"lanzadas": len(elegidas)}


def _anotar(datos, linea):
    datos.setdefault("log", []).append(f"{time.strftime('%H:%M:%S')} {linea}")
    datos["log"] = datos["log"][-200:]


def _seguir(pid, proceso, datos):
    """Lee las lineas JSON del lote y las vuelca en flow/estado.json."""
    escenas = datos["escenas"]
    errores_stderr = []
    hilo_err = threading.Thread(target=lambda: errores_stderr.extend(proceso.stderr), daemon=True)
    hilo_err.start()
    try:
        for linea in proceso.stdout:
            linea = linea.strip()
            if not linea.startswith("{"):
                continue
            try:
                ev = json.loads(linea)
            except json.JSONDecodeError:
                continue
            if "escena" in ev and "estado" in ev:
                n = str(ev["escena"])
                previo = escenas.get(n) or {}
                escenas[n] = {"estado": ev["estado"], "intento": ev.get("intento", previo.get("intento")),
                              "motivo": ev.get("motivo", previo.get("motivo", "") if ev["estado"] == "error" else "")}
                if ev["estado"] == "ok":
                    escenas.pop(n, None)
                    _anotar(datos, f"escena {n} lista ({ev.get('segundos')} s)")
                elif ev["estado"] == "intento":
                    _anotar(datos, f"escena {n}: intento {ev.get('intento')} fallido: {ev.get('motivo', '')[:120]}")
                elif ev["estado"] == "error":
                    _anotar(datos, f"escena {n}: sin imagen tras {ev.get('intentos')} intentos")
            elif ev.get("evento") == "pasada":
                datos["pasada"] = ev.get("n")
                _anotar(datos, f"repaso {ev.get('n')}: {ev.get('pendientes')} escenas fallidas")
            elif ev.get("evento") in ("sin_sesion", "limite", "error"):
                datos["motivo"] = ev.get("motivo", "")
                _anotar(datos, f"{ev['evento']}: {datos['motivo'][:200]}")
            elif ev.get("evento") == "fin":
                _anotar(datos, f"fin: {ev.get('ok')} listas, {ev.get('error')} sin imagen"
                        + (" (detenido)" if ev.get("detenido") else ""))
            almacen.escribir_json(_ruta_estado(pid), datos)
        codigo = proceso.wait()
    except Exception as e:  # noqa: BLE001
        logger.exception(f"flow {pid}: fallo leyendo el lote")
        codigo, datos["motivo"] = 1, str(e)
    hilo_err.join(timeout=2)
    # Las escenas que quedaron "generando" al cortar vuelven a pendientes.
    for n in [n for n, v in escenas.items() if v.get("estado") in ("generando", "intento")]:
        escenas.pop(n)
    datos["resultado"] = CODIGOS.get(codigo, "error")
    if datos["resultado"] == "error" and not datos.get("motivo"):
        datos["motivo"] = "".join(errores_stderr).strip()[-300:] or f"el generador termino con codigo {codigo}"
    datos["fin"] = time.time()
    almacen.escribir_json(_ruta_estado(pid), datos)
    detener = _ruta_detener(pid)
    if os.path.exists(detener):
        os.remove(detener)
    logger.info(f"flow {pid}: {datos['resultado']} {datos.get('motivo', '')[:200]}")


def detener(pid, forzar=False):
    """Pide parar: el lote termina el intento en curso (hasta ~2 min) y sale.
    forzar=True mata el proceso; la escena en curso queda pendiente."""
    with _candado:
        if not _actual or _actual["pid"] != pid or _actual["proceso"].poll() is not None:
            return False
        proceso = _actual["proceso"]
    with open(_ruta_detener(pid), "w") as f:
        f.write(str(time.time()))
    if forzar:
        if os.name == "nt":
            subprocess.run(["taskkill", "/F", "/T", "/PID", str(proceso.pid)], capture_output=True, **SIN_VENTANA)
        else:
            proceso.terminate()
    return True


# ------------------------------------------------------------------ cuentas (perfiles de Chrome) y clips de Veo

COSTE_VIDEO = 10           # creditos de un clip de Veo 3.1 Lite
_revision = {"hilo": None}


def perfiles():
    """{"actual", "perfiles": [{"dir", "email", "creditos", "visto", "sin_sesion"}], "ocupado", "revisando"}."""
    d = _cli("perfiles")
    d["revisando"] = bool(_revision["hilo"] and _revision["hilo"].is_alive())
    d["coste_video"] = COSTE_VIDEO
    for p in d.get("perfiles") or []:
        p.pop("dir", None)   # la ruta del disco no le sirve a la pantalla
    return d


def _libre():
    if corriendo() or (_revision["hilo"] and _revision["hilo"].is_alive()):
        raise RuntimeError("Flow esta ocupado: espera a que termine")


def perfil_nuevo():
    """Crea un perfil y abre su Chrome en el inicio de sesion de Google (otra cuenta)."""
    _libre()
    _cli("perfil-nuevo", timeout=60)
    return perfiles()


def perfil_abrir(i):
    _libre()
    _cli("perfil-abrir", str(int(i)), timeout=60)
    return perfiles()


def perfil_quitar(i):
    _libre()
    _cli("perfil-quitar", str(int(i)), timeout=60)
    return perfiles()


def revisar_perfiles():
    """Entra en cada cuenta y anota correo, sesion y creditos (en segundo plano: ~15 s por cuenta)."""
    _libre()

    def correr():
        try:
            _cli("revisar", timeout=60 * 30)
        except Exception as e:  # noqa: BLE001
            logger.warning(f"flow: revisar cuentas: {e}")
    _revision["hilo"] = threading.Thread(target=correr, daemon=True, name="flow-revisar")
    _revision["hilo"].start()
    return perfiles()


def creditos_video():
    """Clips de video que quedan entre todas las cuentas (por lo ultimo que se vio), o None si no se sabe."""
    try:
        d = _cli("perfiles")
    except Exception:  # noqa: BLE001
        return None
    vistos = [p.get("creditos") for p in d.get("perfiles") or [] if not p.get("sin_sesion")]
    if not any(c is not None for c in vistos):
        return None
    return sum((c or 0) // COSTE_VIDEO for c in vistos if c is not None)


def videos(clips, salida, aspecto="9:16", avisar=lambda evento: None, detener=None, timeout=60 * 60 * 6,
           al_lanzar=lambda proceso: None):
    """Clips de Veo, uno por {"n", "prompt", "inicio"} (inicio = imagen del cuadro inicial), en salida/clip_NNNN.mp4.
    Bloquea (unos 4 min por clip) y rota las cuentas de Flow segun sus creditos. avisar(evento) recibe cada linea
    de tools/flow/videos.js. Devuelve {"codigo", "ok", "fallidos"}: codigo 4 = sin creditos en ninguna cuenta,
    3 = ninguna cuenta con sesion (los clips que falten se quedan sin hacer)."""
    _exigir()
    os.makedirs(salida, exist_ok=True)
    script = os.path.join(salida, "clips.json")
    with open(script, "w", encoding="utf-8") as f:
        json.dump({"clips": clips}, f, ensure_ascii=False)
    orden = [_node(), os.path.join(_dir_flow(), "videos.js"), "--script", script, "--out", salida, "--aspect", aspecto]
    if detener:
        orden += ["--detener", detener]
    proceso = subprocess.Popen(orden, cwd=_dir_flow(), stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
                               encoding="utf-8", errors="replace", **SIN_VENTANA)
    al_lanzar(proceso)
    final = {}
    inicio = time.time()
    for linea in proceso.stdout:
        if not linea.strip().startswith("{"):
            continue
        try:
            evento = json.loads(linea)
        except ValueError:
            continue
        final = evento if evento.get("evento") else final
        try:
            avisar(evento)
        except Exception:  # noqa: BLE001
            pass
        if time.time() - inicio > timeout:
            proceso.kill()
            break
    proceso.wait()
    return {"codigo": proceso.returncode, "ok": final.get("ok", 0), "fallidos": final.get("fallidos") or [],
            "motivo": final.get("motivo")}


# ------------------------------------------------------------------ clips de Veo para las escenas de un proyecto

def _ruta_estado_videos(pid):
    return almacen.dir_proyecto(pid, "flow", "videos.json")


def _videos_hechos(pid):
    """{escena: archivo} de los videos que ya hay en recursos/videos (subidos o hechos con Veo)."""
    carpeta = almacen.dir_proyecto(pid, "recursos", "videos")
    hechos = {}
    if os.path.isdir(carpeta):
        for n in os.listdir(carpeta):
            ruta = os.path.join(carpeta, n)
            if not n.endswith(".part") and medios.tipo_de(ruta) == "video":
                k = recursos.numero_escena(n)
                if k is not None:
                    hechos[k] = f"videos/{n}"
    return hechos


def estado_videos(pid, escenas):
    datos = almacen.leer_json(_ruta_estado_videos(pid), {}) or {}
    imagenes, hechos = _imagenes(pid), _videos_hechos(pid)
    en_marcha = corriendo(pid) and _actual.get("tipo") == "video"
    filas = []
    for e in escenas:
        n = e["scene_number"]
        info = (datos.get("escenas") or {}).get(str(n)) or {}
        if n in hechos:
            est = "lista"
        elif not (e.get("video_prompt") or "").strip():
            est = "sin_prompt"
        elif n not in imagenes:
            est = "sin_imagen"
        elif en_marcha and info.get("estado") == "generando":
            est = "en_curso"
        elif info.get("estado") == "error":
            est = "error"
        else:
            est = "pendiente"
        filas.append({"escena": n, "estado": est, "archivo": hechos.get(n), "motivo": info.get("motivo") or ""})
    cuenta = {k: sum(1 for f in filas if f["estado"] == k)
              for k in ("lista", "pendiente", "error", "en_curso", "sin_prompt", "sin_imagen")}
    return {"corriendo": en_marcha, "otro": corriendo() and not en_marcha, "resultado": None if en_marcha else datos.get("resultado"),
            "motivo": datos.get("motivo") or "", "mensaje": datos.get("mensaje") or "", "cuenta": cuenta, "escenas": filas,
            "clips_disponibles": creditos_video()}


def iniciar_videos(pid, escenas, aspecto):
    """Un clip de Veo por escena que tenga imagen y prompt de video y aun no tenga video: la imagen es el primer
    cuadro. Van a recursos/videos/scene_NNNN.mp4 (el video de una escena gana a su imagen). En segundo plano."""
    _exigir()
    imagenes, hechos = _imagenes(pid), _videos_hechos(pid)
    elegidas = [e for e in escenas if (e.get("video_prompt") or "").strip()
                and e["scene_number"] in imagenes and e["scene_number"] not in hechos]
    if not elegidas:
        raise ValueError("no hay escenas con imagen y prompt de video que falten por hacer")
    carpeta = almacen.dir_proyecto(pid, "flow", "veo", crear=True)
    clips = [{"n": e["scene_number"], "inicio": almacen.dir_proyecto(pid, "recursos", imagenes[e["scene_number"]]),
              "prompt": f"{e['video_prompt'].strip()} No text on screen."} for e in elegidas]
    detener = _ruta_detener(pid)
    if os.path.exists(detener):
        os.remove(detener)
    datos = {"escenas": {}, "resultado": None, "motivo": "", "mensaje": "preparando Flow", "inicio": time.time()}
    almacen.escribir_json(_ruta_estado_videos(pid), datos)
    destino = almacen.dir_proyecto(pid, "recursos", "videos", crear=True)

    def avisar(ev):
        if "clip" in ev:
            datos["escenas"][str(ev["clip"])] = {"estado": ev.get("estado"), "motivo": ev.get("motivo") or ""}
            if ev.get("estado") == "ok":
                hecho = os.path.join(carpeta, f"clip_{int(ev['clip']):04d}.mp4")
                if os.path.isfile(hecho):
                    os.replace(hecho, os.path.join(destino, f"scene_{int(ev['clip']):04d}.mp4"))
            datos["mensaje"] = {"generando": f"Veo hace la escena {ev['clip']} (2-4 min)",
                                "espera": f"Google pide ir mas despacio: esperando {ev.get('segundos')} s",
                                }.get(ev.get("estado"), datos["mensaje"])
        elif ev.get("evento") == "cuenta" and ev.get("estado") == "probando":
            datos["mensaje"] = f"mirando los creditos de la cuenta {ev['perfil'] + 1}"
        almacen.escribir_json(_ruta_estado_videos(pid), datos)

    def registrar(proceso):
        with _candado:
            _actual.clear()
            _actual.update({"pid": pid, "proceso": proceso, "tipo": "video"})

    def correr():
        try:
            r = videos(clips, carpeta, aspecto if aspecto in ("9:16", "16:9") else "16:9", avisar, detener, al_lanzar=registrar)
            datos["resultado"] = {0: "fin", 2: "detenido", 3: "sin_sesion", 4: "sin_creditos", 5: "inusual"}.get(r["codigo"], "error")
            datos["motivo"] = r.get("motivo") or ""
        except Exception as e:  # noqa: BLE001
            datos["resultado"], datos["motivo"] = "error", str(e)[:300]
        datos["mensaje"], datos["fin"] = "", time.time()
        almacen.escribir_json(_ruta_estado_videos(pid), datos)

    with _candado:
        if _actual and _actual["proceso"].poll() is None:
            raise RuntimeError("Flow ya esta trabajando" + ("" if _actual["pid"] == pid else " para otro proyecto"))
    threading.Thread(target=correr, daemon=True, name=f"veo-{pid}").start()
    return {"lanzadas": len(elegidas)}
