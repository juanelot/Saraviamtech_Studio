"""
CREAR CONTENIDO con un prompt maestro.

Una "creacion" es una charla con el CLI de Claude que EJECUTA el prompt maestro
(aqui si: es lo que la persona quiere) paso a paso, igual que si lo pegara en un
chat: el primer turno lleva el texto original; los siguientes reanudan la sesion
del CLI (--resume), que ya lo tiene leido.

Para que la app pueda poner botones, cada respuesta termina con una linea oculta
    @@APP {"tipo": "texto|opcion|fin", "opciones": [...], "recomendada": "..."}
que se quita antes de mostrarla. Modo automatico: la app contesta sola con la
opcion recomendada (o con el tema) hasta que el flujo termina.

Al terminar (o cuando se pida), Claude ordena lo producido en ENTREGABLES
(guion, escenas con prompt de imagen/video, miniaturas, bloques) copiando los
prompts tal cual, para copiarlos o descargarlos como prompts.txt / script.json.

CREAR VIDEO: de los entregables sale un proyecto del Estudio ya relleno (guion,
escenas FIJAS con sus prompts, asignacion por escenas, formato). La narracion:
  propia         el guion del prompt maestro, tal cual
  demostracion   Claude escribe una linea por escena contando lo que se ve
  libre          Claude redacta un guion libre del tema (etapa Guion, editable)
  sin_voz        sin locucion: suena el audio de los clips (ASMR, dialogos de Veo)

    storage/estudio/maestros/<mid>/creaciones/<cid>.json
"""
import json
import os
import re
import shutil
import threading
import time
import uuid

from loguru import logger

from app.services import claude_cli
from app.services.estudio import almacen, maestros, referencias, series

MODELOS = ("sonnet", "opus")
TIEMPO_MAX_S = 1500
MAX_TURNOS_AUTO = 30
MAX_MENSAJE = 20000
MODELO_ENTREGABLES = "haiku"

SISTEMA = (
    "Estas dentro de Saraviamtech Studio, una app que guia a una persona por un PROMPT MAESTRO de creacion de video. "
    "Sigue el prompt maestro al pie de la letra: sus estados o pasos en orden, sus paradas (STOP, WAIT), sus textos exactos, "
    "sus formatos y sus reglas. No tienes herramientas: no puedes generar audio, imagenes ni video; si el prompt pide una "
    "herramienta externa (ElevenLabs u otra), usa la alternativa que el propio prompt indica (texto listo para pegar) y sigue. "
    "OBLIGATORIO: termina SIEMPRE cada respuesta con una ultima linea, sola, que empiece por @@APP seguida de un objeto JSON "
    "en una sola linea con las claves tipo, opciones y recomendada. tipo vale texto si esperas que la persona escriba algo "
    "libre, opcion si esperas que elija entre opciones o escriba una palabra clave, y fin si el prompt maestro ya entrego "
    "todos sus entregables finales (usa fin aunque ofrezca repetir, regenerar una etapa o empezar otro tema). opciones es la lista (maximo 12) de respuestas exactas que puede enviar, tal como las espera el prompt maestro "
    "(palabras clave como proceed o next, numeros de opcion, etc.); si son ideas o propuestas numeradas pon el numero seguido "
    "de un titulo corto, por ejemplo 3. El faro abandonado. recomendada es la opcion que AVANZA al siguiente paso del flujo; dejala vacia si el flujo termino o si la "
    "decision solo puede tomarla la persona. "
    "La app oculta esa linea: no la menciones nunca."
)

PRIMER_MENSAJE = """Vas a actuar como el chat que describe este PROMPT MAESTRO. Siguelo al pie de la letra.
La persona acaba de abrir el chat: empieza exactamente como indica el prompt maestro.

<<<PROMPT MAESTRO>>>
{texto}
<<<FIN DEL PROMPT MAESTRO>>>"""

REEMPEZAR = """Vas a actuar como el chat que describe este PROMPT MAESTRO. Siguelo al pie de la letra.
La charla ya empezo (abajo la tienes). Continua desde donde se quedo, respondiendo al ultimo mensaje.

<<<PROMPT MAESTRO>>>
{texto}
<<<FIN DEL PROMPT MAESTRO>>>

CONVERSACION HASTA AHORA:
{charla}

ULTIMO MENSAJE DE LA PERSONA:
{mensaje}"""

AUTO_LIBRE = "Decide tu la mejor opcion y continua."

PROMPT_ENTREGABLES = """Abajo tienes las respuestas de un chat que siguio un prompt maestro para crear un video.
Ordena lo que produjo en JSON para una app. COPIA los textos EXACTAMENTE como aparecen (sin
resumir, sin traducir, sin corregir): los prompts se pegan tal cual en herramientas de imagen/video.
Si algo se genero varias veces, usa la ULTIMA version. Si algo no existe, pon null o [].

ESCENAS: una escena es un TRAMO del video final (lo que se ve durante unos segundos). Cuenta
solo las que el chat planteo como partes del video; puede ser UNA sola (un reel de 10 s).
Una imagen que sirve para CREAR un video (storyboard, fotograma inicial o final, referencia,
hoja de personaje) NO es otra escena: va en "imagen" de la MISMA escena que ese video.
Si un prompt dice su duracion ("10-second video", "8 s"), ponla en duracion_s.
"continua" es true si el chat pide que ese clip EMPIECE desde el ultimo fotograma del clip
anterior (segmentos encadenados, extender el clip anterior).

REFERENCIAS: hojas o imagenes que el chat pide crear ANTES de las escenas para que un
personaje, vehiculo, objeto o lugar salga igual en todas (reference sheet, character sheet,
character.png...). No son escenas. En "refs" de cada escena pon los nombres de las
referencias que esa escena usa. Los bloques de texto fijo (CHARACTER BLOCK...) van en bloques.

<<<CHAT>>>
{charla}
<<<FIN>>>

Responde SOLO con JSON valido:
{{
  "titulo": "titulo corto del video",
  "guion": "la narracion completa lista para locutar (solo el texto que se dice), o null si no hay",
  "escenas": [{{"n": 1, "narracion": "texto que se dice en esta escena o null",
               "imagen": "prompt de imagen completo o null", "video": "prompt de video/animacion completo o null",
               "duracion_s": segundos o null, "continua": false, "refs": ["nombres de referencias que usa"]}}],
  "referencias": [{{"nombre": "nombre corto (protagonista, vehiculo...)",
                    "tipo": "personaje | vehiculo | objeto | lugar | estilo | otro",
                    "prompt": "prompt completo de la hoja de referencia",
                    "archivo": "nombre de archivo que indica el chat (ej. character.png) o null"}}],
  "miniaturas": ["prompts de miniatura completos"],
  "bloques": [{{"titulo": "nombre (ej. CHARACTER BLOCK, ajustes de voz, lista de ideas...)", "texto": "contenido completo"}}]
}}"""

_candado = threading.RLock()
_activas = set()


class ErrorCreacion(ValueError):
    pass


def _dir(mid):
    ruta = os.path.join(maestros._dir(mid), "creaciones")
    os.makedirs(ruta, exist_ok=True)
    return ruta


def _ruta(mid, cid):
    return os.path.join(_dir(mid), f"{almacen.validar_id(cid)}.json")


def _chat_cwd():
    # Carpeta fija y vacia: --resume busca la sesion por la carpeta de trabajo.
    ruta = almacen.raiz("maestros", "_chat")
    os.makedirs(ruta, exist_ok=True)
    return ruta


def cargar(mid, cid):
    c = almacen.leer_json(_ruta(mid, cid))
    if not c:
        raise ErrorCreacion("creacion no encontrada")
    c["pensando"] = cid in _activas
    # Videos creados que la persona ya borro de "Mis videos": fuera de la lista.
    c["proyectos"] = [p for p in c.get("proyectos") or [] if os.path.isdir(almacen.dir_proyecto(p["id"]))]
    c["serie_info"] = None
    if c.get("serie"):
        try:
            s = series.cargar(mid, c["serie"])
            c["serie_info"] = {"id": s["id"], "titulo": s["titulo"], "episodio": c.get("episodio")}
        except series.ErrorSerie:
            c["serie"] = None
    if c.get("entregables"):
        refs = c["entregables"].setdefault("referencias", [])
        if c["serie_info"]:
            # Las de la serie se ven en cada episodio (heredadas: no se guardan en la creacion).
            propias = {referencias.clave(r["nombre"]) for r in refs}
            refs += [{**r, "heredada": True} for r in s["referencias"] if r["clave"] not in propias]
        referencias.con_imagenes(carpeta_ref(mid, c), refs)
    return c


def carpeta_ref(mid, c):
    """Imagenes de referencia: las de la serie si es un episodio."""
    return series.dir_ref(mid, c["serie"]) if c.get("serie") else referencias.dir_ref(mid, cid=c["id"])


def _guardar(mid, c):
    c = {k: v for k, v in c.items() if k not in ("pensando", "serie_info")}
    if c.get("entregables"):
        # `imagen` y `clave` se calculan al cargar; las heredadas son de la serie.
        propias = [r for r in c["entregables"].get("referencias") or [] if not r.get("heredada")]
        c["entregables"] = {**c["entregables"], "referencias": referencias.limpiar(propias)}
    c["actualizado"] = time.time()
    almacen.escribir_json(_ruta(mid, c["id"]), c)


def listar(mid):
    salida = []
    for nombre in os.listdir(_dir(mid)):
        cid = nombre[:-5]
        if not (nombre.endswith(".json") and almacen.PATRON_ID.match(cid)):
            continue
        try:
            c = cargar(mid, cid)
        except ErrorCreacion:
            continue
        ultimo = next((t for t in reversed(c["turnos"]) if t["rol"] == "claude"), None)
        salida.append({"id": cid, "titulo": c["titulo"], "creado": c["creado"], "actualizado": c["actualizado"],
                       "pensando": c["pensando"], "turnos": len(c["turnos"]), "modo": c["modo"],
                       "terminada": bool(ultimo and (ultimo.get("app") or {}).get("tipo") == "fin"),
                       "entregables": bool(c.get("entregables")), "serie": c.get("serie"),
                       "episodio": c.get("episodio")})
    salida.sort(key=lambda x: x["actualizado"], reverse=True)
    return salida


def crear(mid, tema="", modo="guiado", modelo="sonnet", serie=None):
    maestros.cargar(mid)
    modo = "auto" if modo == "auto" else "guiado"
    modelo = modelo if modelo in MODELOS else "sonnet"
    tema = (tema or "").strip()[:4000]
    cid = uuid.uuid4().hex[:12]
    ahora = time.time()
    c = {"id": cid, "maestro": mid, "titulo": tema[:80] or "Nueva creacion", "tema": tema, "tema_usado": False,
         "modo": modo, "modelo": modelo, "creado": ahora, "actualizado": ahora, "sesion": None,
         "turnos": [], "error": None, "auto_turnos": 0,
         "entregables": None, "entregables_estado": None, "entregables_error": None}
    if serie:
        try:
            s = series.cargar(mid, serie)
        except series.ErrorSerie as e:
            raise ErrorCreacion(str(e)) from e
        if s["preparando"]:
            raise ErrorCreacion("espera a que Claude termine la biblia de la serie")
        # El tema va en el contexto del episodio (ver series.contexto): no se reenvia.
        c.update({"serie": serie, "episodio": series.siguiente_numero(mid, serie), "tema_usado": bool(tema)})
        c["titulo"] = f"Episodio {c['episodio']}" + (f": {tema[:70]}" if tema else "")
    _guardar(mid, c)
    if serie:
        series.anadir_episodio(mid, serie, cid)
    _lanzar(mid, cid, None)
    return cargar(mid, cid)


def enviar(mid, cid, texto):
    texto = (texto or "").strip()
    if not texto:
        raise ErrorCreacion("el mensaje esta vacio")
    if len(texto) > MAX_MENSAJE:
        raise ErrorCreacion(f"el mensaje es demasiado largo (max {MAX_MENSAJE} letras)")
    _lanzar(mid, cid, texto)
    return cargar(mid, cid)


def reintentar(mid, cid):
    """Repite el ultimo turno que fallo (el mensaje de la persona ya esta guardado)."""
    c = cargar(mid, cid)
    if not c["turnos"]:
        _lanzar(mid, cid, None)
    elif c["turnos"][-1]["rol"] == "persona":
        _lanzar(mid, cid, c["turnos"][-1]["texto"], repetir=True)
    else:
        raise ErrorCreacion("no hay nada que reintentar")
    return cargar(mid, cid)


def cambiar(mid, cid, cambios):
    with almacen.candado(f"creacion-{cid}"):
        c = cargar(mid, cid)
        if str(cambios.get("titulo") or "").strip():
            c["titulo"] = str(cambios["titulo"]).strip()[:120]
        if "modo" in cambios:
            c["modo"] = "auto" if cambios["modo"] == "auto" else "guiado"
            c["auto_turnos"] = 0
        _guardar(mid, c)
    # Pasar a automatico con una pregunta pendiente: se contesta ya.
    c = cargar(mid, cid)
    if c["modo"] == "auto" and not c["pensando"] and c["turnos"] and c["turnos"][-1]["rol"] == "claude":
        siguiente = _respuesta_auto(c, c["turnos"][-1].get("app") or {})
        if siguiente:
            _lanzar(mid, cid, siguiente, auto=True)
    return cargar(mid, cid)


def borrar(mid, cid):
    if cid in _activas:
        raise ErrorCreacion("espera a que Claude termine de responder")
    ruta = _ruta(mid, cid)
    if os.path.isfile(ruta):
        os.remove(ruta)
    shutil.rmtree(os.path.join(_dir(mid), almacen.validar_id(cid)), ignore_errors=True)


# ------------------------------------------------------------------ turnos

def _lanzar(mid, cid, texto, auto=False, repetir=False):
    with _candado:
        if cid in _activas:
            raise ErrorCreacion("espera a que Claude termine de responder")
        _activas.add(cid)
    try:
        with almacen.candado(f"creacion-{cid}"):
            c = cargar(mid, cid)
            if texto is not None and not repetir:
                c["turnos"].append({"rol": "persona", "texto": texto, "t": time.time(), "auto": auto})
                if c["titulo"] == "Nueva creacion" and not auto:
                    c["titulo"] = texto[:80]
            c["error"] = None
            _guardar(mid, c)
    except Exception:
        _activas.discard(cid)
        raise
    threading.Thread(target=_bucle, args=(mid, cid, texto), daemon=True, name=f"creacion-{cid}").start()


def _bucle(mid, cid, texto):
    """Un turno y, en modo automatico, los siguientes hasta el final."""
    try:
        while True:
            c = cargar(mid, cid)
            respuesta, app, sesion = _turno(mid, c, texto)
            with almacen.candado(f"creacion-{cid}"):
                c = cargar(mid, cid)
                c["sesion"] = sesion or c["sesion"]
                c["turnos"].append({"rol": "claude", "texto": respuesta, "t": time.time(), "app": app})
                _guardar(mid, c)
            if app.get("tipo") == "fin":
                _entregables(mid, cid)
                return
            siguiente = _respuesta_auto(c, app)
            if not siguiente:
                return
            with almacen.candado(f"creacion-{cid}"):
                c = cargar(mid, cid)
                if c["modo"] != "auto" and siguiente != c.get("tema"):
                    return
                if c["auto_turnos"] >= MAX_TURNOS_AUTO:
                    c["modo"] = "guiado"
                    c["error"] = f"El modo automatico se detuvo tras {MAX_TURNOS_AUTO} respuestas; sigue tu."
                    _guardar(mid, c)
                    return
                c["auto_turnos"] += 1
                c["turnos"].append({"rol": "persona", "texto": siguiente, "t": time.time(), "auto": True})
                _guardar(mid, c)
            texto = siguiente
    except claude_cli.LimiteAgotado as e:
        _fallo(mid, cid, f"Tu cuenta de Claude no tiene cupo ahora mismo. {e}")
    except Exception as e:  # noqa: BLE001
        logger.exception(f"creacion {cid}: fallo el turno")
        _fallo(mid, cid, str(e)[:600])
    finally:
        _activas.discard(cid)


def _fallo(mid, cid, mensaje):
    with almacen.candado(f"creacion-{cid}"):
        c = cargar(mid, cid)
        c["error"] = mensaje
        _guardar(mid, c)


def _respuesta_auto(c, app):
    """Lo que la app contesta sola: el tema la primera vez que se pide texto
    (en cualquier modo) y, en automatico, la opcion recomendada."""
    tipo = app.get("tipo")
    if tipo == "fin":
        return None
    if tipo == "texto" and c.get("tema") and not c.get("tema_usado"):
        c["tema_usado"] = True
        _guardar(c["maestro"], c)
        return c["tema"]
    if c["modo"] != "auto":
        return None
    respuestas = [t["texto"] for t in c["turnos"] if t["rol"] == "claude"]
    if len(respuestas) > 1 and respuestas[-1].strip() == respuestas[0].strip():
        return None  # el flujo volvio a empezar: no se da vueltas solo
    recomendada = str(app.get("recomendada") or "").strip()
    if recomendada:
        return recomendada
    # Sin recomendada solo se decide solo una pregunta abierta; una eleccion
    # entre opciones (repetir, regenerar...) se deja a la persona.
    return AUTO_LIBRE if tipo == "texto" else None


def _turno(mid, c, texto):
    original = maestros.texto_original(mid)
    if c["sesion"] and texto is not None:
        try:
            return _llamar(texto, c["modelo"], reanudar=c["sesion"])
        except claude_cli.LimiteAgotado:
            raise
        except Exception as e:  # noqa: BLE001
            logger.warning(f"creacion {c['id']}: no se pudo reanudar la sesion ({e}); se reempieza")
    if not c["turnos"] or texto is None:
        return _llamar(PRIMER_MENSAJE.format(texto=original) + _serie(mid, c), c["modelo"])
    previos = c["turnos"][:-1]
    charla = "\n\n".join(f"{'PERSONA' if t['rol'] == 'persona' else 'CHAT'}: {t['texto']}" for t in previos)
    return _llamar(REEMPEZAR.format(texto=original, charla=charla, mensaje=texto) + _serie(mid, c), c["modelo"])


def _serie(mid, c):
    if not c.get("serie"):
        return ""
    try:
        return series.contexto(mid, c)
    except series.ErrorSerie:
        return ""


def _llamar(mensaje, modelo, reanudar=None):
    salida, sobre = claude_cli.ejecutar_sobre(
        mensaje, modelo=modelo, esfuerzo="low", tiempo_max_s=TIEMPO_MAX_S, sistema=SISTEMA,
        cwd=_chat_cwd(), reanudar=reanudar)
    texto, app = separar_app(salida)
    return texto, app, (sobre or {}).get("session_id")


PATRON_APP = re.compile(r"@@APP\s*:?\s*(\{.*\})", re.DOTALL)


def separar_app(salida):
    """(texto visible, datos de la linea @@APP)."""
    i = salida.rfind("@@APP")
    if i == -1:
        return salida.strip(), {"tipo": "texto", "opciones": [], "recomendada": ""}
    visible = salida[:i].rstrip().removesuffix("```").rstrip()
    app = {}
    m = PATRON_APP.search(salida[i:])
    if m:
        bloque = m.group(1)
        bloque = bloque[: bloque.rfind("}") + 1]
        try:
            app = json.loads(bloque)
        except json.JSONDecodeError:
            app = {}
    tipo = app.get("tipo") if app.get("tipo") in ("texto", "opcion", "fin") else "texto"
    opciones = [str(o).strip() for o in (app.get("opciones") or []) if str(o).strip()][:12]
    return visible, {"tipo": tipo, "opciones": opciones, "recomendada": str(app.get("recomendada") or "").strip()}


# ------------------------------------------------------------------ crear video

NARRACIONES = ("propia", "demostracion", "libre", "sin_voz")
ASPECTOS = ("9:16", "16:9", "1:1")
VOZ_POR_IDIOMA = {"es": "es-MX-JorgeNeural-Male", "en": "en-US-AndrewNeural-Male", "pt": "pt-BR-AntonioNeural-Male"}

PROMPT_DEMOSTRACION = """Vas a escribir la NARRACION de un video corto del estilo "{estilo}".
El prompt maestro de este estilo no trae voz; la persona quiere narrarlo como DEMOSTRACION:
contar, con naturalidad, lo que se ve en cada escena mientras ocurre (que pasa, como se ve,
como suena o se siente), con un gancho en la primera linea y un cierre en la ultima.

Idioma: {idioma}. Tono: {tono}
Una linea por escena, en orden. Cada linea debe llenar casi toda la duracion de su escena
sin pasarse: entre 2 y 2.5 palabras por segundo. Sin emojis, sin comillas, sin acotaciones.

ESCENAS (numero, duracion, lo que se ve segun su prompt):
{escenas}

Responde SOLO con un JSON: una lista de exactamente {n} textos, uno por escena, en orden."""


def aspecto_de(ficha):
    a = str(((ficha or {}).get("formato") or {}).get("aspecto") or "")
    return a if a in ASPECTOS else "9:16"


def narracion_sugerida(c, ficha):
    e = c.get("entregables") or {}
    if e.get("guion") or any(s.get("narracion") for s in e.get("escenas") or []):
        return "propia"
    return "sin_voz"


def crear_video(mid, cid, narracion, aspecto=None, voz=None, titulo=None):
    c = cargar(mid, cid)
    e = c.get("entregables") or {}
    escenas = e.get("escenas") or []
    if not escenas:
        raise ErrorCreacion("primero prepara los entregables: hacen falta las escenas")
    if narracion not in NARRACIONES:
        raise ErrorCreacion("narracion no valida")
    maestro = maestros.cargar(mid)
    ficha = maestro.get("ficha") or {}
    formato = ficha.get("formato") or {}
    clip_s = float(formato.get("clip_s") or 0) or 8.0
    idioma = str((ficha.get("narracion") or {}).get("idioma") or "es").split("-")[0].lower()[:2] or "es"
    aspecto = aspecto if aspecto in ASPECTOS else aspecto_de(ficha)

    fijas = [{"n": s["n"], "narracion": s.get("narracion"), "imagen": s.get("imagen"), "video": s.get("video"),
              "duracion_s": float(s.get("duracion_s") or 0) or clip_s} for s in escenas]
    params = {"escenas": {"generar": "no", "fijas": fijas},
              "asignacion": {"modo": "escenas", "preferir": "video"},
              "render": {"aspecto": aspecto}}
    total = sum(f["duracion_s"] for f in fijas)

    if narracion == "propia":
        guion = (e.get("guion") or "").strip() or " ".join(f["narracion"] or "" for f in fijas).strip()
        if not guion:
            raise ErrorCreacion("esta creacion no trae guion: elige demostracion, libre o sin voz")
        params["guion"] = {"modo": "literal", "material": guion, "idioma": idioma}
    elif narracion == "demostracion":
        lineas = _demostracion(maestro, fijas, idioma, c.get("modelo") or "sonnet")
        for f, linea in zip(fijas, lineas):
            f["narracion"] = linea
        params["guion"] = {"modo": "literal", "material": "\n\n".join(lineas), "idioma": idioma}
    elif narracion == "libre":
        for f in fijas:
            f["narracion"] = None
        vistas = "\n".join(f"- escena {f['n']}: {(f['video'] or f['imagen'] or '')[:300]}" for f in fijas)
        params["guion"] = {
            "modo": "redactar", "idioma": idioma, "duracion_s": max(10, int(round(total))),
            "material": f"Tema: {c.get('tema') or e.get('titulo') or c['titulo']}\n\n"
                        f"Lo que se ve en el video, en orden:\n{vistas}",
            "instrucciones": f"Video del estilo {maestro['nombre']}. La narracion acompana las escenas en su orden, "
                             "sin describirlas literalmente.",
        }
    else:
        for f in fijas:
            f["narracion"] = None
        params["guion"] = {"modo": "literal", "material": "(video sin narracion)", "idioma": idioma}
        params["voz"] = {"voz": "ninguna", "tramos": [f["duracion_s"] for f in fijas]}
        params["render"].update({"subtitulos": False, "musica": ""})

    if narracion != "sin_voz":
        params["voz"] = {"voz": voz or VOZ_POR_IDIOMA.get(idioma, "es-ES-AlvaroNeural-Male")}

    proyecto = almacen.crear((titulo or e.get("titulo") or c["titulo"]).strip())
    proyecto["params"] = params
    proyecto["origen"] = {"maestro": mid, "creacion": cid, "narracion": narracion}
    almacen.guardar(proyecto)
    with almacen.candado(f"creacion-{cid}"):
        c = cargar(mid, cid)
        c.setdefault("proyectos", []).append({"id": proyecto["id"], "narracion": narracion, "t": time.time()})
        _guardar(mid, c)
    return proyecto


def _demostracion(maestro, fijas, idioma, modelo):
    ficha = maestro.get("ficha") or {}
    escenas = "\n".join(f"{f['n']} ({f['duracion_s']:g} s): {(f['video'] or f['imagen'] or '')[:600]}" for f in fijas)
    prompt = PROMPT_DEMOSTRACION.format(
        estilo=maestro["nombre"], idioma={"es": "espanol neutro latinoamericano", "en": "ingles"}.get(idioma, idioma),
        tono=(ficha.get("audio") or "")[:300] or "calmado y cercano", escenas=escenas, n=len(fijas))
    datos = claude_cli.extraer_json(claude_cli.ejecutar(prompt, modelo=modelo, esfuerzo="low", tiempo_max_s=600))
    lineas = [" ".join(str(x).split()) for x in datos] if isinstance(datos, list) else []
    if len(lineas) != len(fijas) or not all(lineas):
        raise ErrorCreacion("Claude no devolvio una linea por escena; intentalo otra vez")
    return lineas


# ------------------------------------------------------------------ entregables

def preparar_entregables(mid, cid):
    c = cargar(mid, cid)
    if not any(t["rol"] == "claude" for t in c["turnos"]):
        raise ErrorCreacion("todavia no hay nada que ordenar")
    with _candado:
        if cid in _activas:
            raise ErrorCreacion("espera a que Claude termine de responder")
        _activas.add(cid)

    def correr():
        try:
            _entregables(mid, cid)
        finally:
            _activas.discard(cid)

    threading.Thread(target=correr, daemon=True, name=f"entregables-{cid}").start()
    return cargar(mid, cid)


def _entregables(mid, cid):
    with almacen.candado(f"creacion-{cid}"):
        c = cargar(mid, cid)
        c.update({"entregables_estado": "preparando", "entregables_error": None})
        _guardar(mid, c)
    try:
        charla = "\n\n---\n\n".join(t["texto"] for t in c["turnos"] if t["rol"] == "claude")
        salida = claude_cli.ejecutar(PROMPT_ENTREGABLES.format(charla=charla), modelo=MODELO_ENTREGABLES,
                                     esfuerzo="low", tiempo_max_s=TIEMPO_MAX_S)
        i, j = salida.find("{"), salida.rfind("}")
        datos = json.loads(salida[i:j + 1]) if i != -1 and j > i else None
        if not isinstance(datos, dict):
            raise ErrorCreacion("Claude no devolvio los entregables en JSON")
        datos = _limpiar_entregables(datos)
        with almacen.candado(f"creacion-{cid}"):
            c = cargar(mid, cid)
            c.update({"entregables": datos, "entregables_estado": "listo", "entregables_error": None})
            if datos.get("titulo") and (c["titulo"] == "Nueva creacion" or c["titulo"] == c.get("tema", "")[:80]):
                c["titulo"] = str(datos["titulo"])[:120]
            _guardar(mid, c)
    except Exception as e:  # noqa: BLE001
        logger.exception(f"creacion {cid}: fallaron los entregables")
        with almacen.candado(f"creacion-{cid}"):
            c = cargar(mid, cid)
            c.update({"entregables_estado": "error", "entregables_error": str(e)[:400]})
            _guardar(mid, c)


def editar_escenas(mid, cid, escenas):
    """La persona ajusta las escenas (unir, quitar, duracion); se renumeran 1..n."""
    if not isinstance(escenas, list) or not escenas:
        raise ErrorCreacion("el video necesita al menos una escena")
    with almacen.candado(f"creacion-{cid}"):
        c = cargar(mid, cid)
        if not c.get("entregables"):
            raise ErrorCreacion("todavia no hay entregables")
        limpias = _limpiar_entregables({"escenas": escenas})["escenas"]
        if not limpias:
            raise ErrorCreacion("el video necesita al menos una escena")
        for k, s in enumerate(limpias, 1):
            s["n"] = k
            if s["duracion_s"] is not None and not 0.5 <= s["duracion_s"] <= 600:
                raise ErrorCreacion(f"escena {k}: duracion fuera de rango (0.5 a 600 s)")
        c["entregables"]["escenas"] = limpias
        _guardar(mid, c)
    return cargar(mid, cid)


# ------------------------------------------------------------------ hojas de referencia

def editar_referencias(mid, cid, lista):
    """La persona quita referencias o corrige su prompt (el nombre es la clave
    de la imagen: no se renombra). Las quitadas pierden su imagen."""
    with almacen.candado(f"creacion-{cid}"):
        c = cargar(mid, cid)
        if not c.get("entregables"):
            raise ErrorCreacion("todavia no hay entregables")
        heredadas = {r["clave"] for r in c["entregables"]["referencias"] if r.get("heredada")}
        antes = {r["clave"] for r in c["entregables"]["referencias"]} - heredadas
        nuevas = referencias.limpiar([r for r in lista or [] if isinstance(r, dict) and not r.get("heredada")])
        quedan = {referencias.clave(r["nombre"]) for r in nuevas} | heredadas
        if not c.get("serie"):  # en una serie la imagen es compartida: se conserva
            for k in antes - quedan:
                referencias.quitar_imagen(carpeta_ref(mid, c), k)
        for s in c["entregables"]["escenas"]:
            s["refs"] = [x for x in s.get("refs") or [] if referencias.clave(x) in quedan]
        c["entregables"]["referencias"] = nuevas
        _guardar(mid, c)
    return cargar(mid, cid)


def proponer_referencias(mid, cid):
    """Claude propone hojas de referencia para los sujetos que se repiten."""
    c = cargar(mid, cid)
    e = c.get("entregables") or {}
    if not e.get("escenas"):
        raise ErrorCreacion("primero prepara los entregables: hacen falta las escenas")
    ficha = maestros.cargar(mid).get("ficha") or {}
    idioma = str((ficha.get("idiomas") or {}).get("prompts") or "en").split("-")[0].lower()[:2]
    try:
        nuevas, usos = referencias.proponer(e["escenas"], [r["nombre"] for r in e["referencias"]], idioma,
                                            c.get("modelo") or "sonnet")
    except referencias.ErrorReferencia as err:
        raise ErrorCreacion(str(err)) from err
    if not nuevas:
        raise ErrorCreacion("Claude no ve personajes, objetos ni lugares que se repitan entre escenas")
    with almacen.candado(f"creacion-{cid}"):
        c = cargar(mid, cid)
        e = c["entregables"]
        e["referencias"] = referencias.limpiar(e["referencias"] + nuevas)
        validas = {referencias.clave(r["nombre"]) for r in e["referencias"]}
        for s in e["escenas"]:
            extra = [x for x in usos.get(s["n"], []) if referencias.clave(x) in validas]
            s["refs"] = list(dict.fromkeys((s.get("refs") or []) + extra))
        _guardar(mid, c)
    return cargar(mid, cid)


def subir_referencia(mid, cid, k, datos):
    c = cargar(mid, cid)
    ref = next((r for r in (c.get("entregables") or {}).get("referencias") or [] if r["clave"] == k), None)
    if not ref:
        raise ErrorCreacion("referencia no encontrada")
    try:
        referencias.guardar_imagen(carpeta_ref(mid, c), ref["nombre"], datos)
    except referencias.ErrorReferencia as err:
        raise ErrorCreacion(str(err)) from err
    return cargar(mid, cid)


def quitar_referencia(mid, cid, k):
    referencias.quitar_imagen(carpeta_ref(mid, cargar(mid, cid)), referencias.clave(k))
    return cargar(mid, cid)


def ruta_referencia(mid, cid, k):
    return referencias.ruta_imagen(carpeta_ref(mid, cargar(mid, cid)), referencias.clave(k))


def convertir_en_serie(mid, cid):
    """La creacion pasa a ser el episodio 1 de una serie nueva (ver series.py)."""
    if cid in _activas:
        raise ErrorCreacion("espera a que Claude termine de responder")
    with almacen.candado(f"creacion-{cid}"):
        c = cargar(mid, cid)
        try:
            sid = series.crear_desde(mid, c)
        except series.ErrorSerie as e:
            raise ErrorCreacion(str(e)) from e
        c.update({"serie": sid, "episodio": 1})
        _guardar(mid, c)
    return sid


def _texto(v):
    return str(v).strip() if isinstance(v, (str, int, float)) and str(v).strip() else None


def _limpiar_entregables(d):
    escenas = []
    for k, e in enumerate(d.get("escenas") or [], 1):
        if not isinstance(e, dict):
            continue
        try:
            dur = float(e.get("duracion_s")) if e.get("duracion_s") not in (None, "") else None
        except (TypeError, ValueError):
            dur = None
        escenas.append({"n": int(e.get("n") or k) if str(e.get("n") or "").isdigit() else k,
                        "narracion": _texto(e.get("narracion")), "imagen": _texto(e.get("imagen")),
                        "video": _texto(e.get("video")), "duracion_s": dur,
                        "continua": e.get("continua") is True and k > 1,
                        "refs": list(dict.fromkeys(str(r).strip()[:60] for r in e.get("refs") or []
                                                   if isinstance(r, str) and r.strip()))})
    return {
        "titulo": _texto(d.get("titulo")) or "",
        "guion": _texto(d.get("guion")),
        "escenas": escenas,
        "referencias": referencias.limpiar(d.get("referencias")),
        "miniaturas": [x for x in (_texto(m) for m in d.get("miniaturas") or []) if x],
        "bloques": [{"titulo": _texto(b.get("titulo")) or "Bloque", "texto": _texto(b.get("texto"))}
                    for b in d.get("bloques") or [] if isinstance(b, dict) and _texto(b.get("texto"))],
    }
