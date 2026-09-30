"""
MODO SERIE: varios episodios con la misma identidad, hechos con un prompt maestro.

Una serie nace de una creacion terminada (que pasa a ser el episodio 1). Claude
escribe la BIBLIA: lo que no cambia entre episodios (premisa, personajes y bloques
fijos copiados literalmente, look, voz, estructura). Si el chat ya escribio una
biblia de serie, se copia tal cual.

Cada episodio nuevo es una creacion normal con `serie` y `episodio`: su primer
mensaje lleva la biblia BLOQUEADA, las referencias ya creadas y la lista de
episodios hechos (para no repetirlos). Las imagenes de referencia son comunes:
viven en la carpeta de la serie y todos los episodios las ven.

    storage/estudio/maestros/<mid>/series/<sid>.json
    storage/estudio/maestros/<mid>/series/<sid>/ref/<clave>.<ext>
"""
import os
import shutil
import threading
import time
import uuid

from loguru import logger

from app.services import claude_cli
from app.services.estudio import almacen, maestros, referencias

MODELO_BIBLIA = "sonnet"
MAX_BIBLIA = 30000

PROMPT_BIBLIA = """Abajo tienes un chat que siguio un PROMPT MAESTRO y produjo un video. La persona
quiere convertirlo en una SERIE: mas episodios con la misma identidad.

Escribe la BIBLIA DE LA SERIE: lo que debe quedar IGUAL en todos los episodios.
- Si el chat ya escribio una biblia de serie (SERIES BIBLE, BIBLIA DE SERIE, SERIES
  CONSISTENCY LOCK...), COPIALA TAL CUAL, completa, sin resumir.
- Si no, redactala con estas secciones: premisa de la serie; personajes, vehiculos y objetos
  recurrentes (sus bloques fijos, como CHARACTER BLOCK, COPIADOS LITERALMENTE); identidad visual
  (copia literal el bloque de estilo si existe); voz y tono de la narracion; estructura de cada
  episodio (como abre, como cierra); que CAMBIA en cada episodio.
- Los bloques y prompts se copian en su idioma original; el resto en espanol.
- No incluyas los prompts de escenas de este episodio ni su guion: la serie es el FORMATO, no
  este caso concreto (el tema de este episodio sera solo uno de muchos).
- La PRIMERA linea es el titulo de la serie como encabezado: "# Titulo de la serie" (generico,
  que sirva para todos los episodios; no el titulo de este episodio).

<<<CHAT>>>
{charla}
<<<FIN>>>

Responde SOLO con el texto de la biblia en Markdown (sin comentarios antes ni despues)."""

CONTEXTO_EPISODIO = """

CONTEXTO DE LA APP (no es parte del prompt maestro): esta charla produce el EPISODIO {n} de la
serie "{titulo}", ya creada con este mismo prompt maestro.
- TEMA DE ESTE EPISODIO: {tema}
- La BIBLIA de abajo esta BLOQUEADA: usala tal cual y copia sus bloques fijos literalmente.
- Si el prompt maestro tiene pasos para crear la serie, su biblia o las hojas de referencia de
  personajes/vehiculos que ya estan en la biblia, SALTALOS: ya estan hechos. Sigue el resto del
  flujo del prompt maestro para ESTE episodio (sus preguntas, ideas, guion, prompts...).
- Hojas de referencia que YA existen (usa estos mismos nombres; no las reescribas): {refs}
- Episodios ya hechos (no repitas su tema, lugar ni arco):
{episodios}

<<<BIBLIA DE LA SERIE>>>
{biblia}
<<<FIN BIBLIA>>>"""

_activas = set()
_candado = threading.Lock()


class ErrorSerie(ValueError):
    pass


def _dir(mid):
    ruta = os.path.join(maestros._dir(mid), "series")
    os.makedirs(ruta, exist_ok=True)
    return ruta


def _ruta(mid, sid):
    return os.path.join(_dir(mid), f"{almacen.validar_id(sid)}.json")


def dir_ref(mid, sid):
    return referencias.dir_ref(mid, sid=almacen.validar_id(sid))


def _creacion(mid, cid):
    return almacen.leer_json(os.path.join(maestros._dir(mid), "creaciones", f"{cid}.json"))


def resumen_episodio(mid, cid):
    c = _creacion(mid, cid)
    if not c:
        return None
    e = c.get("entregables") or {}
    texto = e.get("guion") or next((s.get("narracion") or s.get("video") or s.get("imagen")
                                    for s in e.get("escenas") or [] if s.get("narracion") or s.get("video") or s.get("imagen")), "")
    return {"id": cid, "episodio": c.get("episodio"), "titulo": e.get("titulo") or c["titulo"],
            "resumen": " ".join(str(texto or c.get("tema") or "").split())[:220],
            "listo": bool(e.get("escenas")), "actualizado": c.get("actualizado")}


def cargar(mid, sid):
    s = almacen.leer_json(_ruta(mid, sid))
    if not s:
        raise ErrorSerie("serie no encontrada")
    s["preparando"] = sid in _activas
    s["episodios_info"] = [x for x in (resumen_episodio(mid, cid) for cid in s["episodios"]) if x]
    referencias.con_imagenes(dir_ref(mid, sid), s["referencias"])
    return s


def _guardar(mid, s):
    s = {k: v for k, v in s.items() if k not in ("preparando", "episodios_info")}
    s["referencias"] = referencias.limpiar(s.get("referencias"))
    s["actualizado"] = time.time()
    almacen.escribir_json(_ruta(mid, s["id"]), s)


def listar(mid):
    salida = []
    for nombre in os.listdir(_dir(mid)):
        sid = nombre[:-5]
        if nombre.endswith(".json") and almacen.PATRON_ID.match(sid):
            try:
                s = cargar(mid, sid)
            except ErrorSerie:
                continue
            salida.append({"id": sid, "titulo": s["titulo"], "episodios": len(s["episodios_info"]),
                           "actualizado": s["actualizado"], "preparando": s["preparando"]})
    salida.sort(key=lambda x: x["actualizado"], reverse=True)
    return salida


def crear_desde(mid, c):
    """Convierte la creacion `c` (ya cargada) en el episodio 1 de una serie nueva."""
    if c.get("serie"):
        raise ErrorSerie("esta creacion ya es un episodio de una serie")
    if not any(t["rol"] == "claude" for t in c["turnos"]):
        raise ErrorSerie("la creacion todavia no tiene contenido")
    sid = uuid.uuid4().hex[:12]
    e = c.get("entregables") or {}
    ahora = time.time()
    s = {"id": sid, "maestro": mid, "titulo": (e.get("titulo") or c["titulo"])[:120], "biblia": "",
         "referencias": e.get("referencias") or [], "episodios": [c["id"]], "creado": ahora,
         "actualizado": ahora, "error": None}
    # Las imagenes de referencia de la creacion pasan a ser de la serie.
    origen = referencias.dir_ref(mid, cid=c["id"])
    if os.path.isdir(origen):
        os.makedirs(os.path.dirname(dir_ref(mid, sid)), exist_ok=True)
        shutil.move(origen, dir_ref(mid, sid))
    _guardar(mid, s)
    _lanzar_biblia(mid, sid, c)
    return sid


def _lanzar_biblia(mid, sid, c):
    with _candado:
        if sid in _activas:
            raise ErrorSerie("ya se esta escribiendo la biblia")
        _activas.add(sid)
    threading.Thread(target=_biblia, args=(mid, sid, c), daemon=True, name=f"biblia-{sid}").start()


def rehacer_biblia(mid, sid):
    s = cargar(mid, sid)
    c = _creacion(mid, s["episodios"][0]) if s["episodios"] else None
    if not c:
        raise ErrorSerie("el episodio 1 ya no existe: escribe la biblia a mano")
    _lanzar_biblia(mid, sid, c)
    return cargar(mid, sid)


def _biblia(mid, sid, c):
    try:
        charla = "\n\n---\n\n".join(t["texto"] for t in c["turnos"] if t["rol"] == "claude")
        texto = claude_cli.ejecutar(PROMPT_BIBLIA.format(charla=charla[-150000:]), modelo=MODELO_BIBLIA,
                                    esfuerzo="low", tiempo_max_s=1200).strip()
        if not texto:
            raise ErrorSerie("Claude devolvio la biblia vacia")
        with almacen.candado(f"serie-{sid}"):
            s = cargar(mid, sid)
            s.update({"biblia": texto[:MAX_BIBLIA], "error": None})
            titulo = _titulo_de(texto)
            if titulo and not s.get("titulo_propio"):
                s["titulo"] = titulo
            _guardar(mid, s)
    except Exception as e:  # noqa: BLE001
        logger.exception(f"serie {sid}: fallo la biblia")
        with almacen.candado(f"serie-{sid}"):
            s = cargar(mid, sid)
            s["error"] = str(e)[:400]
            _guardar(mid, s)
    finally:
        _activas.discard(sid)


def _titulo_de(biblia):
    """El '# Titulo' con que empieza la biblia (sin 'Biblia de la serie —')."""
    primera = biblia.strip().splitlines()[0] if biblia.strip() else ""
    if not primera.startswith("#"):
        return None
    t = primera.lstrip("#").strip().strip("*").strip()
    for sep in ("—", " - ", ":"):
        if sep in t and t.split(sep)[0].strip().lower().startswith(("biblia", "series bible")):
            t = t.split(sep, 1)[1].strip()
    return t[:120] or None


def cambiar(mid, sid, cambios):
    with almacen.candado(f"serie-{sid}"):
        s = cargar(mid, sid)
        if str(cambios.get("titulo") or "").strip():
            s["titulo"] = str(cambios["titulo"]).strip()[:120]
            s["titulo_propio"] = True
        if isinstance(cambios.get("biblia"), str):
            s["biblia"] = cambios["biblia"][:MAX_BIBLIA]
        if isinstance(cambios.get("referencias"), list):
            s["referencias"] = cambios["referencias"]
        _guardar(mid, s)
    return cargar(mid, sid)


def anadir_episodio(mid, sid, cid):
    with almacen.candado(f"serie-{sid}"):
        s = cargar(mid, sid)
        if cid not in s["episodios"]:
            s["episodios"].append(cid)
        _guardar(mid, s)


def siguiente_numero(mid, sid):
    s = cargar(mid, sid)
    return max([x.get("episodio") or 1 for x in s["episodios_info"]] + [0]) + 1


def contexto(mid, c):
    """Texto que se anade al primer mensaje de un episodio."""
    s = cargar(mid, c["serie"])
    hechos = [x for x in s["episodios_info"] if x["id"] != c["id"]]
    episodios = "\n".join(f"  {x.get('episodio') or '?'}. {x['titulo']}: {x['resumen']}" for x in hechos) or "  (ninguno)"
    refs = ", ".join(f"{r['nombre']}{' (' + r['archivo'] + ')' if r.get('archivo') else ''}"
                     for r in s["referencias"]) or "(ninguna)"
    tema = c.get("tema") or ("(la persona aun no lo dio: preguntaselo como indique el prompt maestro; "
                             "no lo inventes ni continues un episodio anterior)")
    return CONTEXTO_EPISODIO.format(n=c.get("episodio") or "?", titulo=s["titulo"], refs=refs, tema=tema,
                                    episodios=episodios, biblia=s["biblia"] or "(todavia sin biblia)")


def borrar(mid, sid):
    """Borra la serie; sus episodios quedan como creaciones sueltas (sin imagenes compartidas)."""
    s = cargar(mid, sid)
    if s["preparando"]:
        raise ErrorSerie("espera a que termine la biblia")
    for cid in s["episodios"]:
        ruta = os.path.join(maestros._dir(mid), "creaciones", f"{cid}.json")
        with almacen.candado(f"creacion-{cid}"):  # el mismo candado que usa creaciones.py
            c = almacen.leer_json(ruta)
            if c and c.get("serie") == sid:
                c.pop("serie", None)
                almacen.escribir_json(ruta, c)
    shutil.rmtree(os.path.join(_dir(mid), sid), ignore_errors=True)
    os.remove(_ruta(mid, sid))
