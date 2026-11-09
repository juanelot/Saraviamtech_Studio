"""
Mis videos (proyectos por etapas) desde el bot de Telegram.

/proyecto: titulo -> material -> como usar el material -> duracion -> formato -> voz -> musica ->
tus fotos/videos (o enlaces directos) -> resumen -> se hace el guion y se para para revisarlo ->
Montar (o tu voz en una nota de voz) -> te llega el MP4. /proyectos: los ultimos, para mandarlos,
sacar titulos y descripcion o borrarlos.

Usa las mismas funciones que la web (controlador del Estudio), asi no hay dos caminos distintos.
Botones: "P<letra>:<valor>". Pasos de la charla: "p_<algo>".
"""
import io
import os
import re
import threading
from types import SimpleNamespace

import requests
from loguru import logger

from app.services.estudio import almacen, grafo
from app.services.estudio import telegram as tg

DURACIONES = [30, 60, 90, 180, 300]
FORMATOS = ["9:16", "16:9", "1:1"]
MAX_ARCHIVO_MB = 20   # getFile de la Bot API no baja archivos mas grandes
URL = re.compile(r"https?://\S+")
# estilo de los dibujos de Nano Banana (va al prompt de cada escena, en ingles como los prompts)
ESTILOS_IMG = [("📷 Realista", "photorealistic cinematic photo"), ("🖌 Ilustracion", "detailed digital illustration"),
               ("🌸 Anime", "anime style illustration"), ("🧸 3D animado", "3D animated cartoon style"),
               ("🎨 Acuarela", "watercolor painting"), ("🤖 Que decida Claude", ""), ("✍️ Lo escribo yo", None)]
SEGUNDOS = [4, 6, 8]   # duracion de cada escena (un clip de Flow dura 8 s)


def _flow_ok():
    from app.services.estudio import ajustes, flow_gen
    return ajustes.flow_disponible() and flow_gen.habilitado()


def _api():
    from app.controllers.v1 import estudio
    return estudio


def _error(e):
    return str(getattr(e, "detail", None) or e)


def _meta(pid):
    return (tg._estado().get("pmeta") or {}).get(pid) or {}


def _poner_meta(pid, **cambios):
    def f(d):
        d.setdefault("pmeta", {}).setdefault(pid, {}).update(cambios)
    tg._cambiar(f)


def _seguir(chat, pid, hasta):
    def f(d):
        d.setdefault("proyectos", {})[pid] = {"chat": str(chat), "hasta": hasta, "visto": "", "mensaje": None}
    tg._cambiar(f)
    m = tg.enviar(chat, "⏳ Empezando...")
    if m:
        tg._cambiar(lambda d: d["proyectos"][pid].__setitem__("mensaje", m["message_id"]))


def _lanzar(chat, pid, hasta, forzar=()):
    try:
        _api().ejecutar(pid, {"hasta": hasta, "forzar": list(forzar)})
    except Exception as e:  # noqa: BLE001
        tg.enviar(chat, f"❌ {_error(e)}")
        return
    _seguir(chat, pid, hasta)


# ------------------------------------------------------------------ comandos

def nuevo(chat):
    tg._poner_charla(chat, paso="p_titulo", p={})
    tg.enviar(chat, "🎞 Video nuevo de Mis videos (con tus fotos y videos).\n\n¿Que titulo le pongo?")


def listar(chat):
    ps = sorted(almacen.listar(), key=lambda p: p.get("actualizado") or 0, reverse=True)[:8]
    if not ps:
        tg.enviar(chat, "Aun no hay proyectos. /proyecto para hacer uno.")
        return
    tg.enviar(chat, "Toca uno:", [[(("🎬 " if _mp4(p["id"]) else "📝 ") + p["titulo"][:42], f"Po:{p['id']}")] for p in ps])


def estado_lineas():
    lineas = []
    for p in almacen.listar():
        t, _ = grafo.trabajo(p["id"])
        if t:
            lineas.append(f"⏳ {p['titulo'][:50]} — {t.get('etapa') or ''} {int(t.get('progreso') or 0)}%")
    return lineas


def _mp4(pid):
    ruta = almacen.dir_proyecto(pid, "render", "final.mp4")
    return ruta if os.path.isfile(ruta) else None


# ------------------------------------------------------------------ texto

def texto(chat, texto):
    c = tg._charla(chat)
    paso, p = c.get("paso"), dict(c.get("p") or {})
    if paso == "p_titulo":
        p["titulo"] = texto.strip()[:200]
        tg._poner_charla(chat, paso="p_material", p=p)
        tg.enviar(chat, "Escribe o pega el material: de que trata, datos, notas... o el guion ya escrito.")
    elif paso == "p_material":
        p["material"] = texto.strip()
        tg._poner_charla(chat, paso="p_modo", p=p)
        tg.enviar(chat, "¿Que hago con ese texto?", [[("✍️ Claude redacta el guion", "Pm:redactar")],
                                                     [("📄 Es el guion: usalo tal cual", "Pm:literal")]])
    elif paso == "p_recursos":
        urls = URL.findall(texto)
        if not urls:
            tg.enviar(chat, "Mandame fotos, videos o un ZIP (o enlaces directos), y toca ✅ Listo al acabar.")
            return
        p["urls"] = list(dict.fromkeys((p.get("urls") or []) + urls))
        tg._poner_charla(chat, paso="p_recursos", p=p)
        _recursos_cuenta(chat, p)
    elif paso == "p_voz":
        tg.enviar(chat, "Espero una nota de voz 🎤 leyendo el guion (o /cancelar).")
    elif paso == "p_grabacion":
        tg.enviar(chat, "Espero tu grabacion 📼 (nota de voz o archivo de audio), o /cancelar.")
    elif paso == "p_estilo_txt":
        p["estilo_img"], p["estilo_nombre"] = texto.strip()[:300], texto.strip()[:60]
        _pedir_segundos(chat, p)
    elif paso == "p_indic":
        p["indicaciones"] = texto.strip()[:1000]
        _confirmar(chat, p)


# ------------------------------------------------------------------ botones

def boton(chat, tipo, valor, mensaje):
    c = tg._charla(chat)
    p = dict(c.get("p") or {})
    paso = c.get("paso")
    if tipo == "Pm" and paso == "p_modo":
        p["modo"] = valor
        tg._poner_charla(chat, paso="p_duracion", p=p)
        tg.enviar(chat, "¿Cuanto dura?" if valor == "redactar" else "¿Cuanto dura? (aprox., el texto manda)",
                  [[(f"{d // 60} min" if d >= 120 else f"{d} s", f"Pd:{d}") for d in DURACIONES]])
    elif tipo == "Pd" and paso == "p_duracion":
        p["duracion"] = int(valor)
        tg._poner_charla(chat, paso="p_formato", p=p)
        tg.enviar(chat, "¿Formato?", [[("📱 9:16 vertical", "Pf:9:16"), ("🖥 16:9", "Pf:16:9"), ("⬛ 1:1", "Pf:1:1")]])
    elif tipo == "Pf" and paso == "p_formato" and valor in FORMATOS:
        p["formato"] = valor
        tg._poner_charla(chat, paso="p_vozelegir", p=p)
        tg.enviar(chat, "¿Que voz?\n🎤 Mi voz: te mando el guion, lo grabas en una nota de voz y se monta con ella.\n"
                        "📼 Ya grabada: me mandas tu audio y el texto sale de lo que dices.",
                  [[("🎤 Mi voz (leo el guion)", "Pw:mi")], [("📼 Ya tengo la grabacion", "Pw:ya")]]
                  + tg._en_filas([(n, f"Pw:{i}") for i, (_, n) in enumerate(tg.VOCES)])
                  + [[("🔇 Sin voz (solo musica)", "Pw:no")]])
    elif tipo == "Pw" and paso == "p_vozelegir":
        if valor == "ya":
            if not _crear_proyecto(chat, p):
                return
            tg._poner_charla(chat, paso="p_grabacion", p=p)
            tg.enviar(chat, "📼 Mandame tu grabacion: nota de voz o archivo de audio (mp3, wav, m4a... hasta 20 MB).")
            return
        p["leer"] = valor == "mi"
        p["voz"] = "ninguna" if valor == "no" else tg.VOCES[0 if valor == "mi" else int(valor)][0]
        _pedir_musica(chat, p)
    elif tipo == "Pu" and paso == "p_musica":
        p["musica"] = "random" if valor == "r" else "" if valor == "-" else (c.get("canciones") or [])[int(valor)]
        if not _crear_proyecto(chat, p):
            return
        tg._poner_charla(chat, paso="p_recursos", p=p)
        tg.enviar(chat, "📎 Ahora mandame tus fotos y videos (hasta 20 MB cada uno), un ZIP o enlaces directos.\n"
                        "Claude los mira y pone cada uno donde pega con lo que se dice."
                  + ("\n\n🎨 ¿No tienes? Nano Banana (Flow) dibuja cada escena." if _flow_ok() else ""),
                  [[("✅ Listo", "Pl:")]] + ([[("🎨 Que las haga Nano Banana", "Pn:")]] if _flow_ok() else []))
    elif tipo == "Pn" and paso == "p_recursos":
        if p.get("voz") == "ninguna":
            tg.enviar(chat, "Con Nano Banana hace falta voz: marca cuanto dura cada escena. Empieza de nuevo con /proyecto.")
            return
        if _cuantos(p) or p.get("urls"):
            tg.enviar(chat, "Ya me mandaste archivos: con Nano Banana no se usan. Toca ✅ Listo para usar los tuyos.")
            return
        tg._poner_charla(chat, paso="p_estilo", p=p)
        tg.enviar(chat, "¿Estilo de los dibujos?", tg._en_filas([(n, f"Pe:{i}") for i, (n, _) in enumerate(ESTILOS_IMG)]))
    elif tipo == "Pe" and paso == "p_estilo":
        nombre, estilo = ESTILOS_IMG[int(valor)]
        p["flow"] = True
        if estilo is None:
            tg._poner_charla(chat, paso="p_estilo_txt", p=p)
            tg.enviar(chat, "Escribe el estilo visual (se aplica a todas las escenas).\n"
                            "Ej.: fotografia documental, luz natural · ilustracion editorial · pintura al oleo")
            return
        p["estilo_img"], p["estilo_nombre"] = estilo, nombre
        _pedir_segundos(chat, p)
    elif tipo == "Ps" and paso == "p_segundos":
        p["segundos"] = int(valor)
        tg._poner_charla(chat, paso="p_indic", p=p)
        tg.enviar(chat, "¿Indicaciones para los dibujos? Personajes fijos, epoca, colores, cosas a evitar...\n"
                        "Escribelas, o toca Saltar.", [[("⏭ Saltar", "Pi:")]])
    elif tipo == "Pi" and paso == "p_indic":
        _confirmar(chat, p)
    elif tipo == "Pl" and paso == "p_recursos":
        if not _cuantos(p) and not p.get("urls"):
            tg.enviar(chat, "Aun no me has mandado nada: sin fotos ni videos no hay con que montar.", [[("✅ Listo", "Pl:")]])
            return
        _confirmar(chat, p)
    elif tipo == "Pc" and str(paso or "").startswith("p_"):
        tg._poner_charla(chat)
        if p.get("pid"):
            _borrar(p["pid"])
        tg.enviar(chat, "Cancelado y borrado.")
    elif tipo == "Py" and paso == "p_confirmar":
        _empezar(chat, p)
    elif tipo == "Po":
        _menu(chat, valor)
    elif tipo == "Pq":
        _mandar_revision(chat, valor)
    elif tipo == "Pk":
        _mandar_video(chat, valor)
    elif tipo == "Pt":
        _publicar(chat, valor)
    elif tipo == "Pa":      # montar
        _montar(chat, valor)
    elif tipo == "PF":      # volver a mandar a Flow las escenas que faltan
        _flow(chat, valor)
    elif tipo == "Pr":      # grabar mi voz
        tg._poner_charla(chat, paso="p_voz", pid=valor)
        tg.enviar(chat, "🎤 Mandame una nota de voz leyendo el guion tal cual (hasta 10 min). /cancelar para salir.")
    elif tipo == "PV":
        tg.enviar(chat, "¿Que voz?", tg._en_filas([(n, f"Pv:{valor}|{i}") for i, (_, n) in enumerate(tg.VOCES)]))
    elif tipo == "Pv":
        pid, _, i = valor.partition("|")
        try:
            _api().editar(pid, {"params": {"voz": {"voz": tg.VOCES[int(i)][0]}}})
        except Exception as e:  # noqa: BLE001
            tg.enviar(chat, f"❌ {_error(e)}")
            return
        _poner_meta(pid, leer=False)
        _mandar_revision(chat, pid, solo_botones=True)
    elif tipo == "Pg":      # otro guion
        try:
            _api().editar(pid := valor, {"params": {"guion": {"texto_manual": None}}})
        except Exception as e:  # noqa: BLE001
            tg.enviar(chat, f"❌ {_error(e)}")
            return
        _lanzar(chat, pid, "guion", ["guion"])
    elif tipo == "Px":
        titulo = (almacen.cargar(valor) or {}).get("titulo", valor) if _existe(valor) else valor
        tg.enviar(chat, f"¿Borrar «{titulo[:60]}»? No se puede deshacer.", [[("🗑 Si, borrar", f"PX:{valor}"), ("No", "n0:")]])
    elif tipo == "PX":
        _borrar(valor)
        tg.enviar(chat, "🗑 Borrado.")


def _crear_proyecto(chat, p):
    if p.get("pid"):
        return True
    try:
        p["pid"] = _api().crear({"titulo": p["titulo"]})["proyecto"]["id"]
        return True
    except Exception as e:  # noqa: BLE001
        tg.enviar(chat, f"❌ {_error(e)}")
        return False


def _pedir_musica(chat, p):
    canciones = tg._canciones()
    tg._poner_charla(chat, paso="p_musica", p=p, canciones=canciones)
    tg.enviar(chat, "¿Que musica?", [[("🎲 Al azar", "Pu:r"), ("🔇 Sin musica", "Pu:-")]]
              + tg._en_filas([(n.rsplit(".", 1)[0][:30], f"Pu:{i}") for i, n in enumerate(canciones)]))


def _pedir_segundos(chat, p):
    tg._poner_charla(chat, paso="p_segundos", p=p)
    tg.enviar(chat, "¿Cuanto dura cada escena? (se juntan frases hasta ese tiempo: menos = mas dibujos)",
              [[(f"{n} s", f"Ps:{n}") for n in SEGUNDOS]])


def _confirmar(chat, p):
    tg._poner_charla(chat, paso="p_confirmar", p=p)
    tg.enviar(chat, _resumen(p), [[("✅ Empezar", "Py:")], [("🗑 Cancelar", "Pc:")]])


def grabacion(chat, archivo_id, nombre="voz.ogg"):
    """Tu narracion ya grabada, antes del guion: el texto sale de ella (Whisper)."""
    c = tg._charla(chat)
    p = dict(c.get("p") or {})
    try:
        datos = _bajar(archivo_id)
        v = _api().voz_propia(p["pid"], audio=SimpleNamespace(filename=nombre, file=io.BytesIO(datos)))
    except Exception as e:  # noqa: BLE001
        tg.enviar(chat, f"❌ No pude usar la grabacion: {_error(e)}")
        return
    p["voz"], p["leer"] = v["etapas"]["voz"]["params"]["voz"], False
    p["grabada"] = True
    tg.enviar(chat, "✅ Grabacion recibida.")
    _pedir_musica(chat, p)


def _existe(pid):
    try:
        almacen.cargar(pid)
        return True
    except Exception:  # noqa: BLE001
        return False


def _borrar(pid):
    try:
        _api().borrar(pid)
    except Exception:  # noqa: BLE001
        pass
    tg._cambiar(lambda d: (d.get("proyectos", {}).pop(pid, None), d.get("pmeta", {}).pop(pid, None)))


def _empezar(chat, p):
    pid = p["pid"]
    params = {
        # con grabacion: el texto sale de ella, salvo que el material sea su guion (literal: sus palabras en los subtitulos)
        "guion": {"material": "" if p.get("grabada") and p["modo"] != "literal" else p["material"],
                  "modo": p["modo"], "duracion_s": p["duracion"]},
        "render": {"aspecto": p["formato"], "musica": p["musica"]},
    }
    if not p.get("grabada"):   # la grabada ya quedo puesta como voz al subirla
        params["voz"] = {"voz": p["voz"]}
    if p.get("urls"):
        params["recursos"] = {"urls": p["urls"]}
    if p.get("flow"):   # cada escena con su prompt; Flow deja la imagen N en recursos/images
        params["asignacion"] = {"modo": "escenas"}
        params["escenas"] = {"generar": "imagenes", "estilo": p.get("estilo_img") or "",
                             "segundos": float(p.get("segundos") or 6), "indicaciones": p.get("indicaciones") or ""}
    try:
        _api().editar(pid, {"params": params})
    except Exception as e:  # noqa: BLE001
        tg.enviar(chat, f"❌ {_error(e)}")
        return
    _poner_meta(pid, leer=bool(p.get("leer")), flow=bool(p.get("flow")))
    tg._poner_charla(chat)
    if p["voz"] == "ninguna" or p.get("grabada"):   # sin guion que revisar: directo al video
        _montar(chat, pid)
    else:
        _lanzar(chat, pid, "guion")


def _cuantos(p):
    if not p.get("pid"):
        return 0
    try:
        return len(_api().listar_subidos(p["pid"])["archivos"])
    except Exception:  # noqa: BLE001
        return 0


def _recursos_cuenta(chat, p):
    n, u = _cuantos(p), len(p.get("urls") or [])
    tg.enviar(chat, f"📎 Tengo {n} archivo(s)" + (f" y {u} enlace(s)" if u else "") + ". ¿Mas, o listo?", [[("✅ Listo", "Pl:")]])


def _resumen(p):
    voz = ("tu grabacion (ya subida)" if p.get("grabada") else "tu voz (grabas el guion)" if p.get("leer")
           else "sin voz" if p["voz"] == "ninguna" else next((n for v, n in tg.VOCES if v == p["voz"]), p["voz"]))
    musica = {"random": "al azar", "": "sin musica"}.get(p["musica"], p["musica"].rsplit(".", 1)[0])
    d = p["duracion"]
    material = p["material"] if len(p["material"]) < 300 else p["material"][:300] + "…"
    return "\n".join([
        "📋 Resumen", "",
        f"Titulo: {p['titulo']}",
        f"Material: {material}",
        "Guion: " + ("sale de tu grabacion" if p.get("grabada") and p["modo"] == "redactar"
                     else "lo redacta Claude" if p["modo"] == "redactar" else "tu texto tal cual"),
        "Duracion: la de tu grabacion" if p.get("grabada") else f"Duracion: {d // 60} min" if d >= 120 else f"Duracion: {d} s",
        f"Formato: {p['formato']}",
        f"Voz: {voz}",
        f"Musica: {musica}",
        (f"Imagenes: las dibuja Nano Banana ({p.get('estilo_nombre') or 'estilo libre'}), "
         f"una cada {p.get('segundos') or 6} s" if p.get("flow")
         else f"Fotos y videos: {_cuantos(p)}" + (f" + {len(p['urls'])} enlaces" if p.get("urls") else "")),
        *([f"Indicaciones: {p['indicaciones'][:200]}"] if p.get("indicaciones") else []),
        "", "Va directo al video (no hay guion que revisar)." if p["voz"] == "ninguna" or p.get("grabada")
        else "Primero te mando el guion para revisarlo.",
    ])


# ------------------------------------------------------------------ archivos y voz

def archivo(chat, m):
    """Foto, video o documento mandado mientras se piden los recursos."""
    c = tg._charla(chat)
    p = c.get("p") or {}
    doc = m.get("document") or {}
    if c.get("paso") == "p_grabacion" and str(doc.get("mime_type") or "").startswith(("audio/", "video/")):
        grabacion(chat, doc["file_id"], doc.get("file_name") or "voz.mp3")
        return
    if c.get("paso") != "p_recursos" or not p.get("pid"):
        tg.enviar(chat, "Ahora no espero archivos. /proyecto para hacer un video con tus fotos y videos.")
        return
    if m.get("photo"):
        f, nombre = m["photo"][-1], f"foto_{m['message_id']}.jpg"
    else:
        f = m.get("video") or m.get("document") or m.get("animation")
        nombre = (f or {}).get("file_name") or f"video_{m['message_id']}.mp4"
    if not f:
        return
    if (f.get("file_size") or 0) > MAX_ARCHIVO_MB << 20:
        tg.enviar(chat, f"«{nombre}» pasa de 20 MB: Telegram no me deja bajarlo. Subelo en la web o mandame un enlace directo.")
        return
    try:
        datos = _bajar(f["file_id"])
        r = _api().subir(p["pid"], archivos=[SimpleNamespace(filename=nombre, file=io.BytesIO(datos))], sub="")
    except Exception as e:  # noqa: BLE001
        tg.enviar(chat, f"❌ No pude guardar «{nombre}»: {_error(e)}")
        return
    if r.get("rechazados") and not r.get("guardados"):
        tg.enviar(chat, f"«{nombre}» no es una imagen ni un video.")
        return
    # varias fotos de golpe llegan como mensajes sueltos: se cuenta solo de vez en cuando
    if not m.get("media_group_id") or len(r.get("guardados") or []) > 1 or _cuantos(p) % 5 == 0:
        _recursos_cuenta(chat, p)


def _bajar(file_id):
    f = tg._llamar("getFile", file_id=file_id)
    r = requests.get(f"{tg.API}/file/bot{tg._token()}/{f['file_path']}", timeout=180)
    r.raise_for_status()
    return r.content


def voz(chat, archivo_id):
    pid = tg._charla(chat).get("pid")
    try:
        _, _, etapas = grafo.evaluar(pid)
        texto = ((etapas["guion"].get("salida") or {}).get("texto") or "").strip()
        datos = _bajar(archivo_id)
        api = _api()
        # el guion queda fijo (es lo que has leido) y la voz pasa a ser tu grabacion
        if texto:
            api.editar(pid, {"params": {"guion": {"texto_manual": texto}}})
        api.voz_propia(pid, audio=SimpleNamespace(filename="voz.ogg", file=io.BytesIO(datos)))
    except Exception as e:  # noqa: BLE001
        tg.enviar(chat, f"❌ No pude usar la grabacion: {_error(e)}")
        return
    tg._poner_charla(chat)
    _poner_meta(pid, leer=False)
    tg.enviar(chat, "✅ Grabacion recibida. Monto el video.")
    _montar(chat, pid)


def _montar(chat, pid):
    # con Nano Banana: primero voz y escenas (prompts), luego Flow dibuja y al acabar se monta
    _lanzar(chat, pid, "escenas" if _meta(pid).get("flow") else "render")


def _flow(chat, pid):
    try:
        st = _api().flow_generar(pid, {"reintentar_fallidas": True})
    except Exception as e:  # noqa: BLE001
        tg.enviar(chat, f"❌ Flow no pudo empezar: {_error(e)}", [[("🎨 Reintentar", f"PF:{pid}")]])
        return
    total = len(st.get("escenas") or [])
    m = tg.enviar(chat, f"🎨 Nano Banana dibuja {total} escenas...")

    def f(d):
        d.setdefault("pflow", {})[pid] = {"chat": str(chat), "mensaje": (m or {}).get("message_id"), "visto": ""}
    tg._cambiar(f)


def revisar_flow():
    from app.services.estudio import flow_gen
    for pid, x in list((tg._estado().get("pflow") or {}).items()):
        try:
            st = flow_gen.estado(pid, _api()._escenas(pid))
        except Exception:  # noqa: BLE001 -- borrado
            tg._cambiar(lambda e: e.get("pflow", {}).pop(pid, None))
            continue
        c = st["cuenta"]
        total = len(st["escenas"])
        if st["corriendo"]:
            linea = f"🎨 Nano Banana: {c['lista']} de {total} escenas"
            if linea != x.get("visto") and x.get("mensaje"):
                tg._editar(x["chat"], x["mensaje"], linea)
                tg._cambiar(lambda e: e["pflow"][pid].__setitem__("visto", linea))
            continue
        tg._cambiar(lambda e: e.get("pflow", {}).pop(pid, None))
        if not c["lista"]:
            tg.enviar(x["chat"], f"❌ Flow no hizo ninguna imagen: {st.get('motivo') or 'revisa la sesion de Flow en Configuracion'}",
                      [[("🎨 Reintentar", f"PF:{pid}")]])
            continue
        faltan = total - c["lista"]
        tg.enviar(x["chat"], f"🎨 {c['lista']} imagenes hechas" + (f" (faltaron {faltan}: se tapan con las vecinas)" if faltan else "")
                  + ". Monto el video.")
        _lanzar(x["chat"], pid, "render")


# ------------------------------------------------------------------ revision, video y publicar

def _mandar_revision(chat, pid, solo_botones=False):
    try:
        proyecto, _, etapas = grafo.evaluar(pid)
    except Exception as e:  # noqa: BLE001
        tg.enviar(chat, f"❌ {_error(e)}")
        return
    texto = ((etapas["guion"].get("salida") or {}).get("texto") or "").strip()
    voz = etapas["voz"]["params"].get("voz")
    cabeza = f"📝 {proyecto['titulo']}\n\n{texto[:3500]}"
    if _meta(pid).get("leer"):
        pie = "🎤 Lee este guion tal cual, de corrido, y mandamelo en una nota de voz."
        botones = [[("🎤 Grabar mi voz", f"Pr:{pid}")], [("🎙 Mejor voz de Microsoft", f"PV:{pid}")],
                   [("🔄 Otro guion", f"Pg:{pid}"), ("🗑 Descartar", f"Px:{pid}")]]
    else:
        pie = "🎙 Voz: " + next((n for v, n in tg.VOCES if v == voz), str(voz))
        botones = [[("✅ Montar", f"Pa:{pid}")], [("🎙 Otra voz", f"PV:{pid}"), ("🎤 Mi voz", f"Pr:{pid}")],
                   [("🔄 Otro guion", f"Pg:{pid}"), ("🗑 Descartar", f"Px:{pid}")]]
    tg.enviar(chat, pie if solo_botones else f"{cabeza}\n\n{pie}", botones)


def _menu(chat, pid):
    if not _existe(pid):
        tg.enviar(chat, "Ese proyecto ya no existe.")
        return
    titulo = almacen.cargar(pid)["titulo"]
    if _mp4(pid):
        filas = [[("📩 Enviar", f"Pk:{pid}"), ("📋 Titulos y descripcion", f"Pt:{pid}")], [("🗑 Borrar", f"Px:{pid}")]]
    elif grafo.trabajo(pid)[0]:
        filas = [[("🗑 Borrar", f"Px:{pid}")]]
        titulo += " (se esta haciendo)"
    else:
        filas = [[("📝 Ver guion", f"Pq:{pid}")], [("🗑 Borrar", f"Px:{pid}")]]
    tg.enviar(chat, f"«{titulo[:60]}»", filas)


def _mandar_video(chat, pid):
    ruta = _mp4(pid)
    if not ruta:
        tg.enviar(chat, "Ese proyecto aun no tiene video.")
        return
    titulo = almacen.cargar(pid)["titulo"]
    mb = os.path.getsize(ruta) / (1 << 20)
    if mb > tg.LIMITE_ENVIO_MB:
        tg.enviar(chat, f"🎞 «{titulo}» pesa {mb:.0f} MB: Telegram no deja mandar mas de 50 MB. Descargalo en la web.")
    else:
        try:
            with open(ruta, "rb") as f:
                tg._llamar("sendVideo", timeout=600, archivos={"video": (f"{pid}.mp4", f, "video/mp4")},
                           chat_id=chat, caption=f"🎬 {titulo}"[:1000], supports_streaming="true")
        except Exception as e:  # noqa: BLE001
            tg.enviar(chat, f"❌ No pude mandar el video: {e}")
            return
    tg.enviar(chat, "¿Y ahora?", [[("📋 Titulos y descripcion", f"Pt:{pid}")], [("🗑 Borrar", f"Px:{pid}")]])


def _publicar(chat, pid):
    """Titulos, descripcion y hashtags (una llamada a Claude: solo si se pide)."""
    tg.enviar(chat, "✍️ Claude escribe titulos y descripcion...")

    def hacer():
        try:
            r = _api().hacer_publicar(pid, "metadatos", {"plataforma": "youtube"})
            d = r.get("metadatos") or r
            partes = ["📋 Para publicar", ""] + [f"{i}. {t}" for i, t in enumerate(d.get("titulos") or [], 1)]
            partes += ["", d.get("descripcion") or ""]
            if d.get("hashtags"):
                partes += ["", " ".join(h if h.startswith("#") else f"#{h}" for h in d["hashtags"])]
            tg.enviar(chat, "\n".join(partes))
        except Exception as e:  # noqa: BLE001
            tg.enviar(chat, f"❌ {_error(e)}")
    threading.Thread(target=hacer, daemon=True).start()


def revisar_seguidos():
    d = tg._estado()
    for pid, x in list((d.get("proyectos") or {}).items()):
        try:
            proyecto, _, etapas = grafo.evaluar(pid)
        except Exception:  # noqa: BLE001 -- borrado desde la web
            tg._cambiar(lambda e: e.get("proyectos", {}).pop(pid, None))
            continue
        t, _ = grafo.trabajo(pid)
        if t:
            linea = f"⏳ «{proyecto['titulo'][:60]}»\n{t.get('etapa') or ''} {int(t.get('progreso') or 0)}% {t.get('mensaje') or ''}".strip()
            if linea != x.get("visto"):
                if x.get("mensaje"):
                    tg._editar(x["chat"], x["mensaje"], linea)
                tg._cambiar(lambda e: e["proyectos"][pid].__setitem__("visto", linea))
            continue
        tg._cambiar(lambda e: e.get("proyectos", {}).pop(pid, None))
        fin = etapas[x["hasta"]]["estado"]
        if x.get("mensaje"):
            tg._editar(x["chat"], x["mensaje"], f"✔ «{proyecto['titulo'][:60]}»: {fin}")
        if fin == "ok" and x["hasta"] == "render":
            _mandar_video(x["chat"], pid)
        elif fin == "ok" and x["hasta"] == "escenas":
            _flow(x["chat"], pid)
        elif fin == "ok":
            tg.enviar(x["chat"], "✋ El guion esta listo. Revisalo:")
            _mandar_revision(x["chat"], pid)
        else:
            error = next((etapas[e]["error"] for e in grafo.ETAPAS if etapas[e].get("error")), None)
            tg.enviar(x["chat"], f"❌ «{proyecto['titulo'][:60]}» se paro: {(error or fin)[:500]}")
            logger.info(f"telegram: proyecto {pid} termino en {fin}")
