"""
HOJAS DE REFERENCIA de una creacion: imagenes que la persona crea PRIMERO (Flow,
Nano Banana...) para que personajes, vehiculos, objetos y lugares salgan iguales
en todas las escenas; luego las adjunta como ingrediente en cada clip.

Los prompts vienen en los entregables (`referencias`), porque los escribio el
prompt maestro, o los propone Claude a partir de las escenas. La imagen que sube
la persona se guarda por CLAVE (el nombre en minusculas y sin signos), asi que
sobrevive a "Actualizar" los entregables mientras el nombre no cambie.

    storage/estudio/maestros/<mid>/creaciones/<cid>/ref/<clave>.<ext>   creacion suelta
    storage/estudio/maestros/<mid>/series/<sid>/ref/<clave>.<ext>       episodios de una serie (compartidas)
"""
import io
import os
import re
import unicodedata

from PIL import Image

from app.services import claude_cli
from app.services.estudio import maestros

TIPOS = ("personaje", "vehiculo", "objeto", "lugar", "estilo", "otro")
EXT = (".png", ".jpg", ".jpeg", ".webp")
MAX_REFERENCIAS = 12


class ErrorReferencia(ValueError):
    pass


def clave(nombre):
    t = unicodedata.normalize("NFD", str(nombre or "")).encode("ascii", "ignore").decode().lower()
    return re.sub(r"[^a-z0-9]+", "-", t).strip("-")[:40] or "referencia"


def dir_ref(mid, cid=None, sid=None):
    """Carpeta de imagenes: la de la serie si la creacion es un episodio."""
    if sid:
        return os.path.join(maestros._dir(mid), "series", sid, "ref")
    return os.path.join(maestros._dir(mid), "creaciones", cid, "ref")


def ruta_imagen(carpeta, k):
    for ext in EXT:
        ruta = os.path.join(carpeta, k + ext)
        if os.path.isfile(ruta):
            return ruta
    return None


def con_imagenes(carpeta, refs):
    """Marca en cada referencia si ya tiene imagen subida (`imagen`: nombre de archivo o None)."""
    for r in refs:
        ruta = ruta_imagen(carpeta, clave(r["nombre"]))
        r["clave"] = clave(r["nombre"])
        r["imagen"] = os.path.basename(ruta) if ruta else None
    return refs


def guardar_imagen(carpeta, nombre, datos: bytes):
    try:
        im = Image.open(io.BytesIO(datos))
        im.verify()
        fmt = (Image.open(io.BytesIO(datos)).format or "").lower()
    except Exception as e:  # noqa: BLE001
        raise ErrorReferencia("no es una imagen valida") from e
    ext = {"png": ".png", "jpeg": ".jpg", "webp": ".webp"}.get(fmt)
    if not ext:
        raise ErrorReferencia("usa PNG, JPG o WEBP")
    k = clave(nombre)
    quitar_imagen(carpeta, k)
    os.makedirs(carpeta, exist_ok=True)
    with open(os.path.join(carpeta, k + ext), "wb") as f:
        f.write(datos)


def quitar_imagen(carpeta, k):
    while True:
        ruta = ruta_imagen(carpeta, k)
        if not ruta:
            return
        os.remove(ruta)


def limpiar(lista):
    salida, vistas = [], set()
    for r in lista or []:
        if not isinstance(r, dict):
            continue
        nombre = str(r.get("nombre") or "").strip()[:60]
        prompt = str(r.get("prompt") or "").strip()
        if not nombre or clave(nombre) in vistas:
            continue
        vistas.add(clave(nombre))
        salida.append({
            "nombre": nombre,
            "tipo": r.get("tipo") if r.get("tipo") in TIPOS else "otro",
            "prompt": prompt or None,
            "archivo": str(r.get("archivo")).strip()[:80] if r.get("archivo") else None,
            "origen": "claude" if r.get("origen") == "claude" else "maestro",
        })
    return salida[:MAX_REFERENCIAS]


PROMPT_PROPONER = """Estas son las escenas de un video corto: prompts para herramientas de imagen/video
(Google Flow, Veo, Nano Banana). Para que lo que se REPITE salga igual en todas las escenas,
propone HOJAS DE REFERENCIA: una imagen por sujeto que la persona creara primero y luego
adjuntara como ingrediente en cada clip.

Reglas:
- Solo sujetos que salen en 2 o mas escenas, o el protagonista. Maximo {maximo}. Si no hay
  nada que repetir, responde [].
- Una hoja por sujeto: nunca una persona y un vehiculo en la misma imagen.
- Personaje: de cuerpo entero, de frente, perfil y espalda, manos visibles y vacias, fondo
  neutro gris claro, luz de estudio uniforme. Vehiculo/objeto: vistas frontal, lateral y
  trasera sobre fondo neutro. Lugar: plano general limpio, sin personas.
- Describe al sujeto con los rasgos EXACTOS que ya usan los prompts (ropa, colores,
  materiales, edad, marcas de desgaste). No inventes rasgos que los contradigan.
- Estilo visual igual al de las escenas. Sin texto, sin logos, sin marcas de agua.
- Prompts en {idioma}. Nombres cortos en espanol (ej. "protagonista", "moto roja").
- NO repitas estas, ya existen: {existentes}

ESCENAS:
{escenas}

Responde SOLO con JSON: [{{"nombre": "...", "tipo": "personaje|vehiculo|objeto|lugar|estilo|otro",
"prompt": "prompt completo de la hoja", "escenas": [numeros de escena donde aparece]}}]"""


def proponer(escenas, existentes, idioma, modelo="sonnet"):
    """Claude propone hojas de referencia a partir de los prompts de las escenas.
    Devuelve (referencias nuevas, {n_escena: [nombres]})."""
    texto = "\n\n".join(f"Escena {s['n']}:\n" + "\n".join(
        x for x in (f"IMAGEN: {s['imagen'][:1500]}" if s.get("imagen") else "",
                    f"VIDEO: {s['video'][:1500]}" if s.get("video") else "") if x)
        for s in escenas if s.get("imagen") or s.get("video"))
    if not texto:
        raise ErrorReferencia("las escenas no traen prompts de imagen ni de video")
    prompt = PROMPT_PROPONER.format(
        maximo=6, idioma={"es": "espanol", "en": "ingles"}.get(idioma, idioma or "ingles"),
        existentes=", ".join(existentes) or "(ninguna)", escenas=texto[:60000])
    datos = claude_cli.extraer_json(claude_cli.ejecutar(prompt, modelo=modelo, esfuerzo="low", tiempo_max_s=900))
    if not isinstance(datos, list):
        raise ErrorReferencia("Claude no devolvio una lista de referencias; intentalo otra vez")
    nuevas = limpiar([{**d, "origen": "claude"} for d in datos if isinstance(d, dict)])
    usos = {}
    for d in datos:
        if not isinstance(d, dict) or not str(d.get("nombre") or "").strip():
            continue
        for n in d.get("escenas") or []:
            if str(n).isdigit():
                usos.setdefault(int(n), []).append(str(d["nombre"]).strip()[:60])
    return nuevas, usos
