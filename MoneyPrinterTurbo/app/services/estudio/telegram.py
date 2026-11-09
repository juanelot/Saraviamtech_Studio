"""
Bot de Telegram del Estudio: manejar la Fabrica (y despues los otros modulos) desde el celular o el PC.

Corre DENTRO del backend (un hilo), asi el token no sale del servidor y funciona igual en el PC y en el
VPS. Long polling (getUpdates): no hace falta dominio ni abrir puertos. Un token solo admite un lector:
el bot del PC y el del VPS necesitan tokens distintos.

Botones y comandos = 0 tokens de Claude: Claude solo se usa donde ya se usaba (el guion).

Seguridad: solo atiende a los chats de `telegram_chats`. Un chat nuevo que escribe /start queda en
"pendientes" y se permite desde la pagina Configuracion.

Config (config.toml, [app]): telegram_habilitado, telegram_token, telegram_chats = ["123", ...].
Estado (storage/estudio/telegram.json): offset, pendientes, conversaciones y videos que se siguen
(para avisar al terminar aunque se reinicie el backend).
"""
import os
import threading
import time

import re

import requests
from loguru import logger

from app.config import config
from app.services.estudio import almacen, fabrica

API = "https://api.telegram.org"
LIMITE_ENVIO_MB = 49          # la Bot API no deja mandar mas de 50 MB
TRABAJANDO = {"en cola", "guion", "voz", "render", "montaje"}
VOCES = [
    ("es-ES-AlvaroNeural-Male", "Alvaro (Espana)"), ("es-ES-ElviraNeural-Female", "Elvira (Espana)"),
    ("es-MX-JorgeNeural-Male", "Jorge (Mexico)"), ("es-MX-DaliaNeural-Female", "Dalia (Mexico)"),
    ("es-US-AlonsoNeural-Male", "Alonso (EE. UU.)"), ("es-US-PalomaNeural-Female", "Paloma (EE. UU.)"),
    ("es-CO-GonzaloNeural-Male", "Gonzalo (Colombia)"), ("es-AR-TomasNeural-Male", "Tomas (Argentina)"),
]
DURACIONES = [30, 60, 90, 180]
URL_EN = re.compile(r"https?://")
AYUDA = (
    "🎬 *Estudio por Telegram*\n\n"
    "*Fabrica*\n"
    "/molde \\- video con un molde guardado \\(directo hasta el MP4\\)\n"
    "/nuevo \\- video paso a paso \\(te enseño el guion antes\\)\n"
    "/lote \\- varios temas con un molde\n"
    "/siguiente \\- siguiente episodio de un video\n"
    "/ultimos \\- los ultimos videos hechos\n\n"
    "*Mis videos* \\(con tus fotos y videos\\)\n"
    "/proyecto \\- video nuevo: material, voz, tus archivos\n"
    "/proyectos \\- los ultimos proyectos\n\n"
    "*General*\n"
    "/estado \\- que se esta haciendo\n"
    "/cancelar \\- salir de lo que estabas haciendo aqui\n"
    "/ayuda \\- este menu"
)

_hilo = None
_parar = threading.Event()
_candado = threading.RLock()
_bot = {"usuario": None, "error": None, "desde": None}


# ------------------------------------------------------------------ config y estado

def _token():
    return str(config.app.get("telegram_token", "") or "").strip()


def _permitidos():
    return {str(c).strip() for c in (config.app.get("telegram_chats") or []) if str(c).strip()}


def _ruta():
    return os.path.join(almacen.raiz(), "telegram.json")


def _estado():
    with _candado:
        d = almacen.leer_json(_ruta(), {}) or {}
        d.setdefault("offset", 0)
        d.setdefault("pendientes", {})
        d.setdefault("charlas", {})
        d.setdefault("siguiendo", {})
        return d


def _guardar(d):
    with _candado:
        almacen.escribir_json(_ruta(), d)


def _cambiar(fn):
    with _candado:
        d = _estado()
        r = fn(d)
        _guardar(d)
        return r


def info():
    d = _estado()
    vivo = bool(_hilo and _hilo.is_alive())
    return {"activo": vivo, "usuario": _bot["usuario"], "error": _bot["error"],
            "pendientes": [{"chat": k, **v} for k, v in d["pendientes"].items()],
            "siguiendo": len(d["siguiendo"])}


# ------------------------------------------------------------------ Bot API

def _llamar(metodo, timeout=40, archivos=None, **datos):
    url = f"{API}/bot{_token()}/{metodo}"
    if archivos:
        r = requests.post(url, data=datos, files=archivos, timeout=timeout)
    else:
        r = requests.post(url, json=datos, timeout=timeout)
    j = r.json()
    if not j.get("ok"):
        raise RuntimeError(j.get("description") or f"Telegram {metodo}: {r.status_code}")
    return j["result"]


def _botones(filas):
    return {"inline_keyboard": [[{"text": t, "callback_data": c} for t, c in fila] for fila in filas]}


def _en_filas(pares, por_fila=2):
    return [pares[i:i + por_fila] for i in range(0, len(pares), por_fila)]


def enviar(chat, texto, botones=None, md=False):
    datos = {"chat_id": chat, "text": texto[:4000], "disable_web_page_preview": True}
    if md:
        datos["parse_mode"] = "MarkdownV2"
    if botones:
        datos["reply_markup"] = _botones(botones)
    try:
        return _llamar("sendMessage", **datos)
    except Exception as e:  # noqa: BLE001
        logger.warning(f"telegram: no se pudo enviar a {chat}: {e}")


def _editar(chat, mid, texto):
    try:
        _llamar("editMessageText", chat_id=chat, message_id=mid, text=texto[:4000])
        return True
    except Exception:  # noqa: BLE001 -- "message is not modified" o borrado: no importa
        return False


# ------------------------------------------------------------------ charla (lo que espera cada chat)

def _charla(chat):
    return _estado()["charlas"].get(str(chat)) or {}


def _poner_charla(chat, **c):
    _cambiar(lambda d: d["charlas"].__setitem__(str(chat), c))


def _seguir(chat, fid, revisar=False):
    def f(d):
        d["siguiendo"][fid] = {"chat": str(chat), "visto": "", "mensaje": None, "revisar": revisar}
    _cambiar(f)


# ------------------------------------------------------------------ comandos

def _molde_menu(chat, accion):
    ms = fabrica.moldes()
    if not ms:
        enviar(chat, "No hay moldes guardados. Guarda uno en la web (tarjeta de un video → Guardar como molde) o usa /nuevo.")
        return
    enviar(chat, "¿Con que molde?" if accion == "m" else "¿Con que molde hago el lote?",
           [[(m["nombre"][:40], f"{accion}:{m['id']}")] for m in ms[:20]])


def _sin_pausa(o):
    # Por Telegram nadie sube clips: un molde con clips/revisar se haria entero (como el CLI sin --con-pausa)
    return {**o, "clips": False, "revisar": False, "leer": False}


def _crear(chat, opciones, revisar):
    try:
        v = fabrica.crear({**opciones, "clips": False, "revisar": revisar})
    except Exception as e:  # noqa: BLE001
        enviar(chat, f"❌ No se pudo empezar: {e}")
        return
    _seguir(chat, v["id"], revisar)
    m = enviar(chat, f"⏳ Empezando «{v['titulo']}»...")
    if m:
        _cambiar(lambda d: d["siguiendo"][v["id"]].__setitem__("mensaje", m["message_id"]))


def _comando(chat, texto):
    cmd = texto.split()[0].split("@")[0].lower()
    resto = texto[len(texto.split()[0]):].strip()
    # un comando cancela lo que se estaba preguntando (pero no la voz/musica elegidas en una revision)
    _poner_charla(chat, rev=_charla(chat).get("rev") or {})
    if cmd in ("/start", "/ayuda", "/help", "/menu"):
        enviar(chat, AYUDA, md=True)
    elif cmd == "/molde":
        _molde_menu(chat, "m")
    elif cmd == "/lote":
        _molde_menu(chat, "l")
    elif cmd == "/nuevo":
        cat = fabrica.catalogo()
        _poner_charla(chat, paso="nicho", o={})
        enviar(chat, "¿De que nicho?", _en_filas([(n["nombre"][:30], f"n:{n['id']}") for n in cat["nichos"]]))
    elif cmd == "/siguiente":
        vs = [v for v in fabrica.listar() if v.get("estado") == "listo"][:8]
        if not vs:
            enviar(chat, "Aun no hay videos terminados.")
            return
        enviar(chat, "¿De que video hago el siguiente episodio?", [[(v["titulo"][:45], f"s:{v['id']}")] for v in vs])
    elif cmd == "/ultimos":
        vs = [v for v in fabrica.listar() if v.get("estado") == "listo" and v.get("videos")][:6]
        if not vs:
            enviar(chat, "Aun no hay videos terminados.")
            return
        enviar(chat, "Toca uno para enviarlo o borrarlo:", [[(v["titulo"][:45], f"o:{v['id']}")] for v in vs])
    elif cmd == "/proyecto":
        from app.services.estudio import tg_proyectos
        tg_proyectos.nuevo(chat)
    elif cmd == "/proyectos":
        from app.services.estudio import tg_proyectos
        tg_proyectos.listar(chat)
    elif cmd == "/estado":
        _estado_cmd(chat)
    elif cmd == "/cancelar":
        enviar(chat, "Listo, cancelado. /ayuda para ver lo que puedo hacer.")
    else:
        enviar(chat, "No conozco ese comando. /ayuda")


def _estado_cmd(chat):
    from app.services.estudio import tg_proyectos
    vs = fabrica.listar()
    trabajando = [v for v in vs if v.get("estado") in TRABAJANDO]
    revision = [v for v in vs if v.get("estado") == "revision"]
    proyectos = tg_proyectos.estado_lineas()
    if not trabajando and not revision and not proyectos:
        enviar(chat, "😴 No hay nada en marcha.")
        return
    lineas = (["🎞 Mis videos"] + proyectos + [""]) if proyectos else []
    lineas.append("🏭 Fabrica")
    for v in trabajando:
        lineas.append(f"⏳ {v['titulo'][:50]} — {v.get('estado')} {v.get('progreso', 0)}%")
    for v in revision:
        lineas.append(f"✋ {v['titulo'][:50]} — esperando revision")
    enviar(chat, "\n".join(lineas), [[(f"Revisar: {v['titulo'][:35]}", f"q:{v['id']}")] for v in revision[:5]] or None)


# ------------------------------------------------------------------ botones

def _boton(chat, dato, mensaje):
    tipo, _, valor = dato.partition(":")
    c = _charla(chat)
    if len(tipo) == 2 and tipo[0] == "P":   # Mis videos
        from app.services.estudio import tg_proyectos
        tg_proyectos.boton(chat, tipo, valor, mensaje)
    elif tipo == "m":        # molde -> pedir tema
        _poner_charla(chat, paso="tema_molde", molde=valor)
        enviar(chat, "Escribe el tema del video:")
    elif tipo == "l":
        _poner_charla(chat, paso="temas_lote", molde=valor)
        enviar(chat, "Escribe los temas, uno por linea:")
    elif tipo == "n":
        estilos = fabrica.catalogo()["estilos"]
        _poner_charla(chat, paso="estilo", o={"nicho": valor})
        enviar(chat, "¿Que estilo?", _en_filas([(e.get("nombre", e["id"])[:24], f"e:{e['id']}") for e in estilos], 3))
    elif tipo == "e" and c.get("paso") == "estilo":
        visuales = fabrica.catalogo()["visuales"]
        _poner_charla(chat, paso="visual", o={**c["o"], "estilo": valor})
        enviar(chat, "¿Como son los dibujos?", _en_filas(
            [("El del estilo", "i:")] + [(v["nombre"][:24], f"i:{v['id']}") for v in visuales], 3))
    elif tipo == "i" and c.get("paso") == "visual":
        _poner_charla(chat, paso="formato", o={**c["o"], "visual": valor})
        enviar(chat, "¿Formato?", [[("Vertical 9:16", "f:9:16"), ("Horizontal 16:9", "f:16:9"), ("Cuadrado 1:1", "f:1:1")]])
    elif tipo == "f" and c.get("paso") == "formato":
        _poner_charla(chat, paso="duracion", o={**c["o"], "formatos": [valor]})
        enviar(chat, "¿Cuanto dura?", [[(f"{d // 60} min" if d >= 120 else f"{d} s", f"d:{d}") for d in DURACIONES]])
    elif tipo == "d" and c.get("paso") == "duracion":
        pres = fabrica.catalogo()["presentadores"]
        _poner_charla(chat, paso="presentador", o={**c["o"], "duracion": int(valor)})
        enviar(chat, "¿Lleva presentador?", _en_filas(
            [("Sin presentador", "p:")] + [(x["nombre"][:24], f"p:{x['id']}") for x in pres], 3))
    elif tipo == "p" and c.get("paso") == "presentador":
        _poner_charla(chat, paso="voz", o={**c["o"], "presentador": valor})
        enviar(chat, "¿Que voz?\n🎤 Mi voz: te mando el guion, lo grabas en una nota de voz y se monta con ella.",
               [[("🎤 Mi voz (leo el guion)", "w:mi")]] + _en_filas([(n, f"w:{i}") for i, (_, n) in enumerate(VOCES)]))
    elif tipo == "w" and c.get("paso") == "voz":
        canciones = _canciones()
        mia = valor == "mi"
        o = {**c["o"], "voz": VOCES[0 if mia else int(valor)][0], "leer": mia}
        _poner_charla(chat, paso="musica", o=o, canciones=canciones)
        enviar(chat, "¿Que musica?", [[("🎲 Al azar", "u:r"), ("🔇 Sin musica", "u:-")]]
               + _en_filas([(n.rsplit(".", 1)[0][:30], f"u:{i}") for i, n in enumerate(canciones)]))
    elif tipo == "u" and c.get("paso") == "musica":
        musica = "random" if valor == "r" else "" if valor == "-" else (c.get("canciones") or [])[int(valor)]
        o = {**c["o"], "musica": musica, **OPCIONES_DEFECTO}
        _poner_charla(chat, paso="opciones", o=o)
        enviar(chat, TEXTO_OPCIONES, _teclado_opciones(o))
    elif tipo == "op" and c.get("paso") == "opciones":
        o = dict(c["o"])
        if valor == "marca":
            _poner_charla(chat, paso="marca_texto", o=o)
            enviar(chat, "Escribe el nombre del canal para el cierre (p. ej. @tucanal), o «no» para quitarlo:")
            return
        if valor == "banco":
            if o.get("banco"):
                o["banco"] = []
            else:
                bancos = _bancos()
                if not bancos:
                    enviar(chat, "El banco de clips esta vacio: corta videos en Fabrica → Banco de clips (en la web).")
                    return
                _poner_charla(chat, paso="banco", o=o, bancos=[b["id"] for b in bancos])
                enviar(chat, TEXTO_BANCO, _teclado_banco(o, bancos))
                return
        elif valor == "seguir":
            _poner_charla(chat, paso="tema_nuevo", o=o)
            enviar(chat, "Escribe el tema del video:")
            return
        elif valor in OPCIONES_DEFECTO:
            o[valor] = not o.get(valor)
        _poner_charla(chat, paso="opciones", o=o)
        _cambiar_teclado(chat, mensaje, _teclado_opciones(o))
    elif tipo == "bk" and c.get("paso") == "banco":
        o = dict(c["o"])
        bancos = [b for b in _bancos() if b["id"] in (c.get("bancos") or [])]
        if valor == "listo":
            _poner_charla(chat, paso="opciones", o=o)
            enviar(chat, TEXTO_OPCIONES, _teclado_opciones(o))
            return
        if valor in ("insertos", "mayoria"):
            o["banco_modo"] = valor
        else:
            sel = list(o.get("banco") or [])
            if valor in sel:
                sel.remove(valor)
            elif len(sel) < 6:
                sel.append(valor)
            o["banco"] = sel
        _poner_charla(chat, paso="banco", o=o, bancos=c.get("bancos"))
        _cambiar_teclado(chat, mensaje, _teclado_banco(o, bancos))
    elif tipo == "y" and c.get("paso") == "confirmar":
        _poner_charla(chat)
        _crear(chat, c["o"], True)
    elif tipo == "z":
        _comando(chat, "/nuevo")
    elif tipo == "s":
        _poner_charla(chat, paso="idea_siguiente", fid=valor)
        enviar(chat, "¿Que pasa en el siguiente episodio? Escribelo, o toca el boton y lo decide Claude.",
               [[("Que lo decida Claude", f"S:{valor}")]])
    elif tipo == "S":
        _siguiente(chat, valor, "")
    elif tipo == "o":      # un video de /ultimos: que hacer con el
        try:
            titulo = fabrica.ver(valor)["titulo"]
        except Exception as e:  # noqa: BLE001
            enviar(chat, f"❌ {e}")
            return
        enviar(chat, f"«{titulo[:60]}»", [[("📩 Enviar", f"k:{valor}"), ("🗑 Borrar", f"x:{valor}")],
                                          [("➡️ Siguiente episodio", f"s:{valor}"), ("📺 Temporada", f"T:{valor}")]])
    elif tipo == "T":      # temporada: cuantos episodios
        enviar(chat, "¿Cuantos episodios seguidos?", [[(str(n), f"T2:{valor}|{n}") for n in (2, 3, 5, 10)]])
    elif tipo == "T2":
        fid, _, n = valor.partition("|")
        enviar(chat, "¿El ultimo episodio cierra la historia?",
               [[("Si, termina ahi", f"T3:{fid}|{n}|1"), ("No, sigue abierta", f"T3:{fid}|{n}|0")]])
    elif tipo == "T3":
        fid, n, final = valor.split("|")
        _poner_charla(chat, paso="idea_temporada", fid=fid, cuantos=int(n), final=final == "1")
        enviar(chat, "¿Hacia donde va la tanda? Escribelo, o toca el boton y lo planea Claude.",
               [[("Que lo planee Claude", f"T4:{fid}|{n}|{final}")]])
    elif tipo == "T4":
        fid, n, final = valor.split("|")
        _temporada(chat, fid, int(n), final == "1", "")
    elif tipo == "k":
        _mandar_video(chat, valor)
    elif tipo == "q":
        _mandar_revision(chat, valor)
    elif tipo == "v":      # otra voz para un video en revision: se guarda y se vuelve a ensenar la revision
        fid, _, i = valor.partition("|")
        _cambio_revision(chat, fid, voz=VOCES[int(i)][0])
    elif tipo == "V":
        enviar(chat, "¿Que voz?", _en_filas([(n, f"v:{valor}|{i}") for i, (_, n) in enumerate(VOCES)]))
    elif tipo == "U":
        canciones = _canciones()
        _poner_charla(chat, paso="musica_rev", fid=valor, canciones=canciones)
        enviar(chat, "¿Que musica?", [[("🎲 Al azar", f"t:{valor}|r"), ("🔇 Sin musica", f"t:{valor}|-")]]
               + _en_filas([(n.rsplit(".", 1)[0][:30], f"t:{valor}|{i}") for i, n in enumerate(canciones)]))
    elif tipo == "t":
        fid, _, i = valor.partition("|")
        canciones = c.get("canciones") or _canciones()
        _cambio_revision(chat, fid, musica="random" if i == "r" else "" if i == "-" else canciones[int(i)])
    elif tipo == "a":      # montar con lo elegido (voz y musica)
        _montar(chat, valor, (_charla(chat).get("rev") or {}).get(valor) or None)
    elif tipo == "r":
        _poner_charla(chat, paso="mi_voz", fid=valor, rev=c.get("rev") or {})
        enviar(chat, "🎤 Mandame una nota de voz leyendo el guion (hasta 10 min). /cancelar para salir.")
    elif tipo == "g":
        try:
            fabrica.rehacer(valor, "guion")
            _seguir(chat, valor, True)
            enviar(chat, "🔄 Escribiendo otro guion...")
        except Exception as e:  # noqa: BLE001
            enviar(chat, f"❌ {e}")
    elif tipo == "x":      # borrar no se deshace: primero se pregunta
        try:
            titulo = fabrica.ver(valor)["titulo"]
        except Exception:  # noqa: BLE001
            titulo = valor
        enviar(chat, f"¿Borrar «{titulo[:60]}»? No se puede deshacer.",
               [[("🗑 Si, borrar", f"X:{valor}"), ("No", "n0:")]])
    elif tipo == "n0":
        enviar(chat, "Vale, no se borra.")
    elif tipo == "X":
        try:
            fabrica.borrar(valor)
            _cambiar(lambda d: d["siguiendo"].pop(valor, None))
            enviar(chat, "🗑 Descartado.")
        except Exception as e:  # noqa: BLE001
            enviar(chat, f"❌ {e}")


OPCIONES_DEFECTO = {"subtitulos": True, "efectos": True, "foco": True, "nuevos": True}
NOMBRES_OPCION = {"subtitulos": "Subtitulos", "efectos": "Efectos de sonido", "foco": "Foco",
                  "nuevos": "Dibujos nuevos (Nano Banana)"}
TEXTO_OPCIONES = ("⚙️ Opciones (toca para cambiar)\n\n"
                  "Foco: al pasar de un sitio a otro, lo de antes se apaga.\n"
                  "Dibujos nuevos: si falta un dibujo, se crea (solo en el PC con Flow).\n"
                  "Clips del banco: Claude pone clips reales detras de las escenas donde pegan.")
TEXTO_BANCO = ("🎞 Elige hasta 6 videos del banco y cuanto se usan.\n"
               "Insertos: 1 de cada 3 escenas. Casi todo: la mayoria con clips.")


def _teclado_opciones(o):
    filas = [[(("✅ " if o.get(k) else "⬜ ") + NOMBRES_OPCION[k], f"op:{k}")] for k in OPCIONES_DEFECTO]
    filas.append([(("✅ " if o.get("banco") else "⬜ ") + "Clips del banco"
                   + (f" ({len(o['banco'])})" if o.get("banco") else ""), "op:banco")])
    filas.append([("🏷 Cierre de marca: " + (o.get("marca") or "no"), "op:marca")])
    filas.append([("➡️ Seguir", "op:seguir")])
    return filas


def _bancos():
    from app.services.estudio import banco
    return [b for b in banco.listar() if b.get("estado") in (None, "listo")][:20]


def _teclado_banco(o, bancos):
    sel = o.get("banco") or []
    modo = o.get("banco_modo") or "insertos"
    filas = [[(("✅ " if b["id"] in sel else "⬜ ") + str(b.get("titulo") or b["id"])[:40], f"bk:{b['id']}")]
             for b in bancos]
    filas.append([(("● " if modo == "insertos" else "○ ") + "Insertos", "bk:insertos"),
                  (("● " if modo == "mayoria" else "○ ") + "Casi todo", "bk:mayoria")])
    filas.append([("✔ Listo", "bk:listo")])
    return filas


def _cambiar_teclado(chat, mensaje, filas):
    try:
        _llamar("editMessageReplyMarkup", chat_id=chat, message_id=mensaje["message_id"], reply_markup=_botones(filas))
    except Exception:  # noqa: BLE001 -- sin cambios visibles: no importa
        pass


def _canciones():
    from app.utils import utils
    try:
        return sorted(f for f in os.listdir(utils.song_dir()) if f.lower().endswith(".mp3"))[:60]
    except OSError:
        return []


def _resumen(o):
    cat = fabrica.catalogo()
    nombre = lambda lista, k: next((x.get("nombre", x["id"]) for x in cat[lista] if x["id"] == k), k)  # noqa: E731
    voz = "tu voz (grabas el guion)" if o.get("leer") else next((n for v, n in VOCES if v == o.get("voz")), o.get("voz"))
    musica = {"random": "al azar", "": "sin musica"}.get(o.get("musica"), str(o.get("musica", "")).rsplit(".", 1)[0])
    d = o.get("duracion") or 60
    return "\n".join([
        "📋 Resumen del video", "",
        f"Tema: {o.get('tema')}",
        f"Nicho: {nombre('nichos', o.get('nicho'))}",
        f"Estilo: {nombre('estilos', o.get('estilo'))}",
        f"Dibujos: {nombre('visuales', o['visual']) if o.get('visual') else 'los del estilo'}",
        f"Formato: {', '.join(o.get('formatos') or ['9:16'])}",
        f"Duracion: {d // 60} min" if d >= 120 else f"Duracion: {d} s",
        f"Presentador: {nombre('presentadores', o['presentador']) if o.get('presentador') else 'no'}",
        f"Voz: {voz}",
        f"Musica: {musica}",
        "Opciones: " + (", ".join(NOMBRES_OPCION[k] for k in OPCIONES_DEFECTO if o.get(k)) or "ninguna"),
        (f"Clips del banco: {len(o['banco'])} videos ({o.get('banco_modo') or 'insertos'})"
         if o.get("banco") else "Clips del banco: no"),
        f"Cierre de marca: {o.get('marca') or 'no'}",
        "", "Primero te mando el guion para revisarlo.",
    ])


def _temporada(chat, fid, cuantos, final, idea):
    _poner_charla(chat)
    try:
        r = fabrica.temporada(fid, None, cuantos, idea, final, True)
    except Exception as e:  # noqa: BLE001
        enviar(chat, f"❌ {e}")
        return
    for v in r.get("videos") or []:
        _seguir(chat, v["id"], False)
    enviar(chat, f"📺 Temporada «{r.get('nombre') or ''}»: {len(r.get('videos') or [])} episodios en cola. "
                 "Te mando cada uno al terminar.")


def _siguiente(chat, fid, idea):
    _poner_charla(chat)
    try:
        v = fabrica.siguiente_episodio(fid, idea)
    except Exception as e:  # noqa: BLE001
        enviar(chat, f"❌ {e}")
        return
    v = v[0] if isinstance(v, list) else v
    _seguir(chat, v["id"], bool(v.get("opciones", {}).get("revisar")))
    enviar(chat, f"⏳ Empezando «{v['titulo']}»...")


def _montar(chat, fid, opciones):
    _poner_charla(chat)
    try:
        fabrica.montar(fid, opciones)
    except Exception as e:  # noqa: BLE001
        enviar(chat, f"❌ {e}")
        return
    _seguir(chat, fid, False)
    enviar(chat, "🎬 Montando el video. Te lo mando al terminar.")


# ------------------------------------------------------------------ texto y voz libres

def _texto(chat, texto):
    c = _charla(chat)
    paso = c.get("paso")
    if str(paso or "").startswith("p_"):   # Mis videos
        from app.services.estudio import tg_proyectos
        tg_proyectos.texto(chat, texto)
    elif paso == "tema_molde":
        molde = next((m for m in fabrica.moldes() if m["id"] == c["molde"]), None)
        _poner_charla(chat)
        if not molde:
            enviar(chat, "Ese molde ya no existe. /molde")
            return
        _crear(chat, {**_sin_pausa(molde["opciones"]), "tema": texto}, False)
    elif paso == "temas_lote":
        molde = next((m for m in fabrica.moldes() if m["id"] == c["molde"]), None)
        temas = [t.strip() for t in texto.splitlines() if t.strip()]
        _poner_charla(chat)
        if not molde or not temas:
            enviar(chat, "Falta el molde o los temas. /lote")
            return
        try:
            vs = fabrica.lote(temas, _sin_pausa(molde["opciones"]))
        except Exception as e:  # noqa: BLE001
            enviar(chat, f"❌ {e}")
            return
        for v in vs:
            _seguir(chat, v["id"], False)
        enviar(chat, f"⏳ {len(vs)} videos en cola. Te los mando uno a uno al terminar.")
    elif paso == "marca_texto":
        marca = "" if texto.strip().lower() in ("no", "-", "ninguna", "ninguno") else texto.strip()[:40]
        o = {**c["o"], "marca": marca}
        _poner_charla(chat, paso="opciones", o=o)
        enviar(chat, TEXTO_OPCIONES, _teclado_opciones(o))
    elif paso == "idea_temporada":
        _temporada(chat, c["fid"], c["cuantos"], c["final"], texto)
    elif paso == "tema_nuevo":
        o = {**c["o"], "tema": texto}
        _poner_charla(chat, paso="confirmar", o=o)
        enviar(chat, _resumen(o), [[("✅ Empezar", "y:1")], [("✏️ Empezar de nuevo", "z:nuevo")]])
    elif paso == "idea_siguiente":
        _siguiente(chat, c["fid"], texto)
    elif paso == "mi_voz":
        enviar(chat, "Espero una nota de voz 🎤 (o /cancelar).")
    else:
        enviar(chat, "Usa un comando para empezar. /ayuda")


def _voz(chat, archivo_id, nombre="voz.ogg"):
    c = _charla(chat)
    if c.get("paso") == "p_voz":
        from app.services.estudio import tg_proyectos
        tg_proyectos.voz(chat, archivo_id)
        return
    if c.get("paso") == "p_grabacion":
        from app.services.estudio import tg_proyectos
        tg_proyectos.grabacion(chat, archivo_id, nombre)
        return
    if c.get("paso") != "mi_voz":
        enviar(chat, "Para usar tu voz, primero elige un video en revision (te aviso cuando haya uno).")
        return
    try:
        f = _llamar("getFile", file_id=archivo_id)
        r = requests.get(f"{API}/file/bot{_token()}/{f['file_path']}", timeout=120)
        r.raise_for_status()
        subida = fabrica.subir_audio(r.content, os.path.basename(f["file_path"]) or "voz.ogg")
    except Exception as e:  # noqa: BLE001
        enviar(chat, f"❌ No pude usar la grabacion: {e}")
        return
    nombre = subida["voz"].split(":", 1)[1]
    enviar(chat, f"✅ Grabacion de {subida['duracion']:.0f} s recibida.")
    elegido = (c.get("rev") or {}).get(c["fid"]) or {}
    _montar(chat, c["fid"], {**elegido, "voz": fabrica.NARRADA + nombre})


# ------------------------------------------------------------------ avisos de los videos que se siguen

def _texto_guion(fid):
    s = fabrica.ver(fid)
    g = s.get("guion") or {}
    partes = [f"📝 {g.get('titulo') or s['titulo']}"]
    if g.get("mensaje"):
        partes.append(f"Mensaje: {g['mensaje']}")
    partes.append("")
    partes += [f"{i}. {e.get('texto', '')}" for i, e in enumerate(g.get("escenas") or [], 1)]
    return "\n".join(partes)


def _cambio_revision(chat, fid, **cambio):
    """Guarda en la charla la voz/musica elegidas para ese video (se aplican al Montar) y repite la revision."""
    rev = dict(_charla(chat).get("rev") or {})
    rev[fid] = {**(rev.get(fid) or {}), **cambio}
    _poner_charla(chat, rev=rev)
    _mandar_revision(chat, fid, solo_botones=True)


def _mandar_revision(chat, fid, solo_botones=False):
    try:
        s = fabrica.ver(fid)
        texto = _texto_guion(fid)
    except Exception as e:  # noqa: BLE001
        enviar(chat, f"❌ {e}")
        return
    elegido = {**s["opciones"], **((_charla(chat).get("rev") or {}).get(fid) or {})}
    voz = next((n for v, n in VOCES if v == elegido.get("voz")), elegido.get("voz"))
    musica = {"random": "al azar", "": "sin musica"}.get(elegido.get("musica"), str(elegido.get("musica", "")).rsplit(".", 1)[0])
    if s["opciones"].get("leer") and "voz" not in ((_charla(chat).get("rev") or {}).get(fid) or {}):
        # espera tu grabacion: sin Montar hasta que llegue la nota de voz (o se elija una voz de Microsoft)
        pie = (f"🎤 Lee este guion tal cual, de corrido, y mandamelo en una nota de voz: tus palabras marcan "
               f"cada escena y los subtitulos.\n🎵 Musica: {musica}")
        enviar(chat, pie if solo_botones else f"{texto}\n\n{pie}", [
            [("🎤 Grabar mi voz", f"r:{fid}")],
            [("🎙 Mejor voz de Microsoft", f"V:{fid}"), ("🎵 Musica", f"U:{fid}")],
            [("🔄 Otro guion", f"g:{fid}"), ("🗑 Descartar", f"x:{fid}")],
        ])
        return
    pie = f"🎙 Voz: {voz}\n🎵 Musica: {musica}"
    enviar(chat, pie if solo_botones else f"{texto}\n\n{pie}", [
        [("✅ Montar", f"a:{fid}")],
        [("🎙 Otra voz", f"V:{fid}"), ("🎤 Mi voz", f"r:{fid}"), ("🎵 Musica", f"U:{fid}")],
        [("🔄 Otro guion", f"g:{fid}"), ("🗑 Descartar", f"x:{fid}")],
    ])


def _mandar_video(chat, fid):
    try:
        s = fabrica.ver(fid)
    except Exception as e:  # noqa: BLE001
        enviar(chat, f"❌ {e}")
        return
    g = s.get("guion") or {}
    for v in s.get("videos") or []:
        try:
            ruta = fabrica.ruta_video(fid, v["formato"])
        except Exception:  # noqa: BLE001
            continue
        mb = os.path.getsize(ruta) / (1 << 20)
        if mb > LIMITE_ENVIO_MB:
            enviar(chat, f"🎞 «{s['titulo']}» ({v['formato']}) pesa {mb:.0f} MB: Telegram no deja mandar mas de 50 MB. "
                         "Descargalo desde la Fabrica en el estudio.")
            continue
        try:
            with open(ruta, "rb") as f:
                _llamar("sendVideo", timeout=600, archivos={"video": (f"{fid}-{v['formato'].replace(':', 'x')}.mp4", f, "video/mp4")},
                        chat_id=chat, caption=f"🎬 {s['titulo']} ({v['formato']})"[:1000], supports_streaming="true",
                        width=str(v.get("ancho") or ""), height=str(v.get("alto") or ""),
                        duration=str(int(v.get("duracion") or 0)))
        except Exception as e:  # noqa: BLE001
            enviar(chat, f"❌ No pude mandar el video: {e}")
    saga = [[("➡️ Siguiente episodio", f"s:{fid}"), ("📺 Temporada", f"T:{fid}")]]
    if g.get("descripcion"):
        enviar(chat, f"📋 Para publicar\n\n{g.get('titulo') or s['titulo']}\n\n{g['descripcion']}", saga)
    else:
        enviar(chat, "¿Seguimos la historia?", saga)


def _revisar_seguidos():
    d = _estado()
    for fid, x in list(d["siguiendo"].items()):
        try:
            s = fabrica.ver(fid)
        except Exception:  # noqa: BLE001 -- borrado desde la web
            _cambiar(lambda e: e["siguiendo"].pop(fid, None))
            continue
        estado = s.get("estado")
        linea = f"⏳ «{s['titulo'][:60]}»\n{estado} {s.get('progreso', 0)}% {s.get('mensaje') or ''}".strip()
        if estado in TRABAJANDO:
            if linea != x.get("visto"):
                if x.get("mensaje"):
                    _editar(x["chat"], x["mensaje"], linea)
                else:
                    m = enviar(x["chat"], linea)
                    if m:
                        _cambiar(lambda e: e["siguiendo"][fid].__setitem__("mensaje", m["message_id"]))
                _cambiar(lambda e: e["siguiendo"][fid].__setitem__("visto", linea))
            continue
        _cambiar(lambda e: e["siguiendo"].pop(fid, None))
        if x.get("mensaje"):
            _editar(x["chat"], x["mensaje"], f"✔ «{s['titulo'][:60]}»: {estado}")
        if estado == "listo":
            _mandar_video(x["chat"], fid)
        elif estado == "revision":
            enviar(x["chat"], "✋ El guion esta listo. Revisalo:")
            _mandar_revision(x["chat"], fid)
        elif estado == "error":
            enviar(x["chat"], f"❌ «{s['titulo'][:60]}» fallo: {s.get('error') or 'sin detalle'}")


# ------------------------------------------------------------------ bucle

def _atender(u):
    if "callback_query" in u:
        q = u["callback_query"]
        chat = str(q["message"]["chat"]["id"])
        try:
            _llamar("answerCallbackQuery", callback_query_id=q["id"])
        except Exception:  # noqa: BLE001
            pass
        if chat in _permitidos():
            _boton(chat, q.get("data") or "", q["message"])
        return
    m = u.get("message") or {}
    if not m:
        return
    chat = str(m["chat"]["id"])
    if chat not in _permitidos():
        nombre = " ".join(x for x in (m["chat"].get("first_name"), m["chat"].get("last_name")) if x) or m["chat"].get("title") or ""
        usuario = m["chat"].get("username") or ""
        _cambiar(lambda d: d["pendientes"].__setitem__(chat, {"nombre": nombre, "usuario": usuario, "cuando": time.time()}))
        enviar(chat, f"Hola. Este bot es privado. Tu numero de chat es {chat}: permitelo en el Estudio → Configuracion → Telegram.")
        return
    texto = (m.get("text") or "").strip()
    if texto.startswith("/"):
        _comando(chat, texto)
    elif m.get("voice") or m.get("audio"):
        a = m.get("voice") or m.get("audio")
        if (a.get("file_size") or 0) > 20 << 20:
            enviar(chat, "Ese audio pasa de 20 MB: Telegram no me deja bajarlo. Mandalo comprimido (mp3/m4a) o subelo en la web.")
            return
        _voz(chat, a["file_id"], a.get("file_name") or ("voz.ogg" if m.get("voice") else "voz.mp3"))
    elif m.get("photo") or m.get("video") or m.get("document") or m.get("animation"):
        from app.services.estudio import tg_proyectos
        tg_proyectos.archivo(chat, m)
        if URL_EN.search(m.get("caption") or ""):   # un enlace junto a la foto
            tg_proyectos.texto(chat, m["caption"])
    elif texto:
        _texto(chat, texto)


def _bucle():
    try:
        yo = _llamar("getMe")
        _bot.update(usuario=yo.get("username"), error=None, desde=time.time())
        _llamar("setMyCommands", commands=[
            {"command": "molde", "description": "Video con un molde (directo)"},
            {"command": "nuevo", "description": "Video paso a paso"},
            {"command": "lote", "description": "Varios temas con un molde"},
            {"command": "siguiente", "description": "Siguiente episodio"},
            {"command": "ultimos", "description": "Ultimos videos"},
            {"command": "proyecto", "description": "Mis videos: con tus fotos y videos"},
            {"command": "proyectos", "description": "Mis videos: ultimos proyectos"},
            {"command": "estado", "description": "Que se esta haciendo"},
            {"command": "ayuda", "description": "Ayuda"},
        ])
        logger.info(f"telegram: bot @{_bot['usuario']} activo")
    except Exception as e:  # noqa: BLE001
        _bot.update(usuario=None, error=str(e))
        logger.warning(f"telegram: no arranca: {e}")
        return
    ultimo_repaso = 0.0
    while not _parar.is_set():
        try:
            d = _estado()
            updates = _llamar_updates(d["offset"])
            for u in updates:
                _cambiar(lambda e: e.__setitem__("offset", u["update_id"] + 1))
                try:
                    _atender(u)
                except Exception:  # noqa: BLE001
                    logger.exception("telegram: fallo atendiendo un mensaje")
            _bot["error"] = None
        except Exception as e:  # noqa: BLE001 -- red caida, token cambiado...
            _bot["error"] = str(e)
            logger.warning(f"telegram: {e}")
            _parar.wait(10)
        if time.time() - ultimo_repaso > 8:
            ultimo_repaso = time.time()
            try:
                _revisar_seguidos()
                from app.services.estudio import tg_proyectos
                tg_proyectos.revisar_seguidos()
                tg_proyectos.revisar_flow()
            except Exception:  # noqa: BLE001
                logger.exception("telegram: fallo revisando videos")
    logger.info("telegram: bot parado")


def _llamar_updates(offset):
    # Espera corta (10 s) para que los avisos de progreso no se retrasen mucho.
    url = f"{API}/bot{_token()}/getUpdates"
    r = requests.post(url, json={"offset": offset, "timeout": 10, "allowed_updates": ["message", "callback_query"]}, timeout=25)
    j = r.json()
    if not j.get("ok"):
        raise RuntimeError(j.get("description") or "getUpdates fallo")
    return j["result"]


def iniciar():
    """Arranca el bot si esta activado y tiene token (al iniciar el backend o al cambiar la config)."""
    global _hilo
    detener()
    if not config.app.get("telegram_habilitado") or not _token():
        _bot.update(usuario=None, error=None)
        return
    _parar.clear()
    _hilo = threading.Thread(target=_bucle, daemon=True, name="telegram-bot")
    _hilo.start()


def detener():
    global _hilo
    if _hilo and _hilo.is_alive():
        _parar.set()
        _hilo.join(timeout=30)
    _hilo = None


def quitar_pendiente(chat):
    _cambiar(lambda d: d["pendientes"].pop(str(chat).strip(), None))
