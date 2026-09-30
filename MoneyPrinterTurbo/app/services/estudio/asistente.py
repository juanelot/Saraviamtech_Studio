"""
El asistente del Estudio: un chat que contesta con el CLI de Claude (la misma
suscripcion que escribe los guiones) y con el Estudio delante.

Idea tomada de AS Video Studio (pasos/asistente.py), simplificada:

1. La GUIA del producto (abajo) + README/DEPLOY si estan, en el primer turno.
   Los siguientes REANUDAN la sesion del CLI (--resume): ya los tiene leidos.
2. El CODIGO a demanda: corre en la carpeta del backend con Read/Grep/Glob y
   nada mas (ni Bash, ni escribir, ni internet). "Me dio este error" se resuelve
   buscando el texto del error en el codigo.
3. Una FOTO del estado AHORA delante de cada pregunta: sistema (CLI, ffmpeg,
   TTS), proyectos, y el proyecto abierto con sus etapas, errores y registro.

No puede leer config.toml (tiene las API keys) ni credenciales: se veta por
regla de permiso del CLI y ademas se le dice en el prompt.

Cada charla vive en memoria (se pierde al reiniciar el servicio, a proposito).
Un turno corre en un hilo; la pantalla consulta hasta que llega la respuesta.
"""
import os
import threading
import time
import uuid

from loguru import logger

from app.config import config
from app.services import claude_cli
from app.services.estudio import almacen, grafo, medios
from app.utils import utils

MODELO = os.environ.get("ESTUDIO_ASISTENTE_MODELO") or "sonnet"
ESFUERZO = os.environ.get("ESTUDIO_ASISTENTE_ESFUERZO") or "low"
TIEMPO_MAX_S = 420
MAX_CHARLAS = 40
CADUCIDAD_S = 24 * 3600
MAX_PREGUNTA = 20000
TURNOS_AL_REEMPEZAR = 10

PERMITIDAS = ("Read", "Grep", "Glob")
VETADAS = (
    "Read(./config.toml)", "Read(**/config.toml)", "Read(**/.env)", "Read(**/.env.*)",
    "Read(**/.credentials.json)", "Read(**/*.pem)", "Read(./.venv/**)",
)

SISTEMA = (
    "Eres el asistente del Estudio de video (app estudio-ui sobre el backend MoneyPrinterTurbo). "
    "Respondes en espanol, claro y breve, a quien usa la app: como se usa, por que algo fallo, "
    "que significa un estado, como desplegar. Usa la FOTO del estado que acompana cada pregunta y, "
    "si hace falta, busca en el codigo con Read/Grep/Glob. Nunca muestres ni intentes leer config.toml, "
    "claves, tokens ni credenciales: si te las piden, di que se configuran en config.toml del servidor. "
    "No inventes funciones que no existen; si algo no se puede hacer, dilo y sugiere la alternativa real. "
    "No uses tablas anchas; listas cortas y pasos numerados."
)

GUIA = """GUIA DEL ESTUDIO (resumen del producto)

Flujo por etapas (ids del grafo): guion -> voz -> escenas -> recursos -> asignacion -> render.
Dos formas de poner imagenes (asignacion.modo):
  * "escenas" (contenido creado A MANO en Google Flow / la extension "AI Content
    Generator"): la etapa ESCENAS agrupa las frases de la voz en escenas (segundos, ~6-8 s)
    y Claude escribe image_prompt y, si se pide, video_prompt (generar = no | imagenes |
    imagenes_videos; estilo visual comun; idioma de prompts, ingles por defecto). Se
    descarga script.json (formato de la extension: {"scenes":[{scene_number, image_prompt,
    video_prompt, narration}]}) o prompts.txt, o se copian uno a uno. La persona genera y
    sube en CONTENIDO la carpeta de la extension (images/ y videos/), un ZIP o archivos
    sueltos: cada archivo va a su escena por el NUMERO del nombre (1.png, scene_2.mp4).
    Si hay video e imagen de una escena se usa el video (asignacion.preferir). Escenas sin
    archivo repiten el anterior (se avisa). NO se usan APIs de imagen: solo el CLI de Claude.
  * "claude" / "orden": recursos propios; Claude elige uno por frase (o en orden). La
    etapa escenas no se usa.
En pantalla los pasos son: Material, Guion, Voz, Escenas, Contenido, Ajuste, Video.
- Material/Guion: la persona pega material; Claude CLI redacta con duracion objetivo
  (hasta 3 h; palabras = segundos x ~2.5) o usa el texto tal cual (modo literal).
  Editar el guion guarda `texto_manual`; "Rehacer con Claude" lo vacia.
- Voz: TTS de MoneyPrinterTurbo (voces Azure/Edge). La narracion se corta en PLANOS
  por sus pausas (plano_min_s / plano_max_s). Opcion "Voz clonada" (voz = "clon:<id>"):
  la genera un servidor Clonar-voz externo (config estudio_voz_clonada_url), por bloques
  de ~240 caracteres cacheados en voz/clon/; en CPU tarda 5-12x la duracion del audio.
  Si falla, suele ser que el servidor de clonacion esta apagado o la voz se borro alli.
- Recursos: imagenes y videos mezclados (subidos, carpeta del servidor o URLs). Claude
  mira una miniatura de cada uno y lo describe; catalogo global por hash, cacheado.
- Planos (asignacion): Claude elige un recurso por plano segun lo que se dice; o en
  orden de archivo. La persona puede fijar planos a mano (params.asignacion.fijados
  {indice: id_recurso}). La eleccion de Claude se cachea (asignacion/base.json): fijar
  o soltar un plano NO vuelve a llamar a Claude; al soltarlo vuelve la eleccion original
  de Claude. Solo se rehace el clip de ese plano. Claude se vuelve a llamar solo si
  cambian los planos, los recursos/descripciones, el criterio o el modelo.
- Video (render): un clip por plano con ffmpeg (cacheado) y acabado rapido con ffmpeg
  (subtitulos ASS + voz + musica) o clasico MPT (MoviePy, lento).
- Edicion editorial (render, render.edicion="editorial", edicion.py): subtitulos palabra
  a palabra con clave en color, rotulos de datos, sfx (whoosh/golpe) + musica bajo la voz,
  ritmo (subcortes con otro encuadre los primeros 30 s), zoom en revelaciones, color
  (ed_look natural/calido/cine/frio) y gancho. Claude marca en una pasada cacheada
  (render/marcas.json). Necesita acabado rapido. Voz guarda voz/palabras.json.
  Momentos clave (ed_momentos; max 1 cada 20 s, prioridad cita > pausa > destello):
  cita destacada, pausa dramatica (congelado 1 s), destello en revelaciones y B/N en
  tramos del "pasado" que marque Claude.
- Miniatura (fuera del grafo, usable en cualquier momento): Claude propone conceptos con
  prompt para Flow (con o sin texto en la imagen) a partir del guion, el estilo de Escenas,
  una miniatura de REFERENCIA opcional (copia su estilo, no su contenido) y hasta 4
  imagenes del proyecto. La persona la genera a mano y sube la FINAL: pasa a ser la
  portada en Mis videos y se descarga. Archivos en proyectos/<id>/miniatura/.
Prompts maestros (/maestros, maestros.py): biblioteca de estilos. Se sube un prompt maestro
(docx/txt/md/pegado) y Claude lo desglosa en una ficha (pasos, preguntas, entregables,
formato, narracion, bloques fijos, reglas). Guardado en storage/estudio/maestros/<id>/.
Portada propia: en la ficha, "Cambiar portada" sobre la imagen (o quitarla).
Crear contenido (boton en la ficha, creaciones.py): una charla que EJECUTA el prompt maestro
con el CLI de Claude, paso a paso. Tema opcional de antemano; modo Guiado (botones con las
opciones de cada paso, la recomendada con estrella, o texto libre) o Automatico (elige la
recomendada hasta el final; se puede parar). Al terminar se ordenan los ENTREGABLES (guion,
escenas con prompt de imagen y de video, miniaturas, bloques) y se descargan guion.txt,
prompts de imagen/video .txt (separados por linea en blanco) y script.json (extension de Flow).
Las creaciones se guardan en storage/estudio/maestros/<id>/creaciones/.
Crear video en el Estudio (tarjeta arriba de los entregables): crea un proyecto ya relleno con
las escenas FIJAS del prompt maestro y sus prompts (escenas.fijas; la etapa Escenas solo las
coloca sobre la voz: por palabras si traen narracion, por duracion si no), asignacion por
escenas y el formato. Narracion: "Su guion" (el del maestro, literal), "Guion demostracion"
(Claude escribe una linea por escena contando lo que se ve), "Guion libre" (etapa Guion en
modo redactar, editable) o "Sin voz" (voz = "ninguna": pista muda con la duracion de las
escenas, sin subtitulos ni musica; el render usa el AUDIO DE LOS CLIPS). Despues: voz, subir
en Contenido lo hecho en Flow (cada archivo con su numero de escena) y montar.
La pantalla (estudio-ui): inicio con "Nuevo video" y tarjetas de "Mis videos" (Ver,
Descargar, Editar, Duplicar, Renombrar, Borrar). Dentro de un video, 8 pasos arriba:
Material, Guion, Voz, Escenas, Contenido, Ajuste, Video, Miniatura. Boton "Todo hasta el video" (arriba a la
derecha) ejecuta todo lo pendiente. La barra de abajo tiene el boton principal del paso
(Escribir guion -> Generar voz -> Elegir recursos -> Asignar planos -> Montar video),
"Registro" (log) y, mientras trabaja, progreso y "Cancelar". Cada paso tiene ademas su
boton propio (Rehacer con Claude, Volver a sintetizar, Catalogar recursos, Volver a
asignar / Aplicar cambios, Volver a montar). Los cambios se guardan solos al escribir.
Estados de etapa: ok (al dia), obsoleta (algo de lo que depende cambio), pendiente,
error, ejecutando. Solo se rehace lo obsoleto: cada etapa guarda la firma de sus
entradas (params + salidas de las etapas de las que depende).
Codigo: app/services/estudio/*.py (grafo.py, guion.py, voz.py, recursos.py,
asignacion.py, render.py, acabado.py), app/services/claude_cli.py,
app/controllers/v1/estudio.py. Datos: storage/estudio/proyectos/<id>/ (proyecto.json,
estado.json con el log). CLI de automatizacion: estudio_cli.py (en la raiz del repo).
Requisitos: CLI `claude` con sesion; ffmpeg con libass para el acabado rapido.
"""

_candado = threading.RLock()
_charlas = {}


class ErrorAsistente(ValueError):
    pass


# ------------------------------------------------------------------ contexto

def _documentos():
    partes = []
    for nombre in ("README.md", "DEPLOY.md"):
        for base in (os.path.dirname(utils.root_dir()), utils.root_dir()):
            ruta = os.path.join(base, nombre)
            if os.path.isfile(ruta):
                with open(ruta, encoding="utf-8", errors="replace") as f:
                    partes.append(f"=== {nombre} ===\n{f.read()[:40000]}")
                break
    return "\n\n".join(partes)


def foto(pid=None) -> str:
    """El estado AHORA, en texto, para ponerlo delante de cada pregunta."""
    lineas = ["FOTO DEL ESTADO (ahora)"]
    try:
        ruta_cli = claude_cli.localizar()
    except RuntimeError:
        ruta_cli = "NO ENCONTRADO"
    ff = medios.ffmpeg()
    try:
        from app.services.estudio import acabado
        libass = "si" if acabado.tiene_libass(ff) else "NO (se usara el acabado clasico)"
    except Exception:  # noqa: BLE001
        libass = "desconocido"
    lineas += [
        f"- CLI claude: {ruta_cli}",
        f"- ffmpeg: {ff} | libass: {libass}",
        f"- tts_server: {config.ui.get('tts_server', '?')} | subtitle_provider: {config.app.get('subtitle_provider', '?')}",
        f"- carpetas permitidas para recursos: {config.app.get('estudio_carpetas_permitidas') or 'cualquiera'}",
    ]
    proyectos = almacen.listar()
    lineas.append(f"- proyectos: {len(proyectos)}")
    for p in proyectos[:8]:
        trab = " [TRABAJANDO]" if grafo.trabajo(p["id"])[0] else ""
        lineas.append(f"  · {p['id']} «{p['titulo']}»{trab}")

    if pid:
        try:
            proyecto, _estado, vista = grafo.evaluar(pid)
            trabajo, log = grafo.trabajo(pid)
            lineas.append(f"\nPROYECTO ABIERTO EN PANTALLA: {pid} «{proyecto['titulo']}»")
            if trabajo:
                lineas.append(f"- trabajo en curso: etapa={trabajo['etapa']} {trabajo['progreso']}% «{trabajo['mensaje']}»")
            for e in grafo.ETAPAS:
                v = vista[e]
                params = dict(v["params"])
                for k in ("material", "texto_manual"):
                    if isinstance(params.get(k), str) and len(params[k]) > 300:
                        params[k] = params[k][:300] + f"… ({len(params[k])} letras)"
                resumen = _resumen_salida(e, v["salida"])
                lineas.append(f"- {e}: {v['estado']}"
                              + (f" | ERROR: {v['error']}" if v.get("error") else "")
                              + (f" | {resumen}" if resumen else "")
                              + f" | params: {params}")
            planos = (vista["asignacion"]["salida"] or {}).get("planos") or []
            if planos:
                lineas.append("- planos asignados (en pantalla se numeran #1, #2... = indice+1):")
                for x in planos[:80]:
                    marca = " [FIJADO A MANO]" if x.get("fijado") else ""
                    lineas.append(f"    #{x['i'] + 1} {x['fin'] - x['inicio']:.1f}s -> {x.get('nombre')}{marca}"
                                  f" (motivo: {x.get('motivo', '')}) «{x['texto'][:70]}»")
                if len(planos) > 80:
                    lineas.append(f"    ... y {len(planos) - 80} planos mas")
            recursos_s = (vista["recursos"]["salida"] or {}).get("recursos") or []
            if recursos_s:
                lineas.append("- recursos catalogados (id -> archivo: descripcion):")
                for r in recursos_s[:60]:
                    lineas.append(f"    {r['id']} -> {r['nombre']} [{r['tipo']}]: {(r.get('descripcion') or '')[:90]}")
            if log:
                lineas.append("- ultimas lineas del registro:\n" + "\n".join("    " + l for l in log[-30:]))
        except FileNotFoundError:
            lineas.append(f"\n(el proyecto {pid} ya no existe)")
    return "\n".join(lineas)


def _resumen_salida(etapa, s):
    if not s:
        return ""
    if etapa == "guion":
        return f"{s.get('palabras')} palabras, origen {s.get('origen')}"
    if etapa == "voz":
        return f"{s.get('duracion')}s de voz, {len(s.get('planos') or [])} planos"
    if etapa == "recursos":
        return f"{s.get('imagenes')} imagenes, {s.get('videos')} videos, {s.get('sin_descripcion')} sin descripcion"
    if etapa == "asignacion":
        return f"{len(s.get('planos') or [])} planos, {s.get('recursos_usados')} recursos usados"
    if etapa == "render":
        return f"video {s.get('duracion')}s, {s.get('tam_mb')} MB"
    return ""


# ------------------------------------------------------------------ charlas

def _limpiar_viejas():
    ahora = time.time()
    for cid in [c for c, v in _charlas.items() if ahora - v["tocada"] > CADUCIDAD_S]:
        _charlas.pop(cid, None)
    if len(_charlas) > MAX_CHARLAS:
        for cid in sorted(_charlas, key=lambda c: _charlas[c]["tocada"])[: len(_charlas) - MAX_CHARLAS]:
            _charlas.pop(cid, None)


def ver(cid):
    with _candado:
        c = _charlas.get(cid)
        if not c:
            raise ErrorAsistente("esa charla ya no existe (el servicio se reinicio o caduco)")
        return {"id": cid, "turnos": list(c["turnos"]), "pensando": c["pensando"], "error": c["error"]}


def preguntar(cid, pregunta, pid=None):
    pregunta = (pregunta or "").strip()
    if not pregunta:
        raise ErrorAsistente("la pregunta esta vacia")
    if len(pregunta) > MAX_PREGUNTA:
        raise ErrorAsistente(f"la pregunta es demasiado larga (max {MAX_PREGUNTA} letras)")
    with _candado:
        _limpiar_viejas()
        if cid and cid in _charlas:
            c = _charlas[cid]
            if c["pensando"]:
                raise ErrorAsistente("espera a que termine la respuesta anterior")
        else:
            cid = uuid.uuid4().hex[:12]
            c = {"turnos": [], "sesion": None, "pensando": False, "error": None, "tocada": time.time()}
            _charlas[cid] = c
        c["turnos"].append({"rol": "persona", "texto": pregunta, "t": time.time()})
        c["pensando"], c["error"], c["tocada"] = True, None, time.time()
    threading.Thread(target=_turno, args=(cid, pregunta, pid), daemon=True, name=f"asistente-{cid}").start()
    return ver(cid)


def _turno(cid, pregunta, pid):
    c = _charlas[cid]
    estado_ahora = foto(pid)
    try:
        if c["sesion"]:
            try:
                texto, sobre = _llamar(f"{estado_ahora}\n\nPREGUNTA:\n{pregunta}", reanudar=c["sesion"])
            except Exception as e:  # noqa: BLE001
                logger.warning(f"asistente: no se pudo reanudar la sesion ({e}); se reempieza")
                texto, sobre = _llamar(_primer_mensaje(estado_ahora, pregunta, c["turnos"][:-1]))
        else:
            texto, sobre = _llamar(_primer_mensaje(estado_ahora, pregunta, []))
        with _candado:
            c["sesion"] = sobre.get("session_id") or c["sesion"]
            c["turnos"].append({"rol": "asistente", "texto": texto.strip(), "t": time.time()})
    except claude_cli.LimiteAgotado as e:
        c["error"] = f"Tu cuenta de Claude no tiene cupo ahora mismo. {e}"
    except Exception as e:  # noqa: BLE001
        c["error"] = str(e)[:600]
    finally:
        with _candado:
            c["pensando"], c["tocada"] = False, time.time()


def _primer_mensaje(estado_ahora, pregunta, previos):
    partes = [GUIA, _documentos()]
    if previos:
        charla = "\n".join(f"{t['rol'].upper()}: {t['texto']}" for t in previos[-TURNOS_AL_REEMPEZAR:])
        partes.append(f"CONVERSACION HASTA AHORA:\n{charla}")
    partes += [estado_ahora, f"PREGUNTA:\n{pregunta}"]
    return "\n\n".join(p for p in partes if p)


def _llamar(mensaje, reanudar=None):
    return claude_cli.ejecutar_sobre(
        mensaje, modelo=MODELO, esfuerzo=ESFUERZO, tiempo_max_s=TIEMPO_MAX_S,
        sistema=SISTEMA, cwd=utils.root_dir(), permitidas=PERMITIDAS,
        reglas_vetadas=VETADAS, reanudar=reanudar,
    )
