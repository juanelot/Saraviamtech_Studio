"""
MINIATURA del video (fuera del grafo de etapas: no invalida nada).

Claude propone conceptos de miniatura con el prompt listo para Flow (u otra
herramienta), a partir de:
  - la produccion: titulo, guion, estilo visual de Escenas;
  - una miniatura de REFERENCIA que suba la persona (Claude la mira y copia el
    estilo: composicion, colores, tipo de texto, no el contenido);
  - algunas imagenes del proyecto (Contenido), para mantener personajes y estetica.

La persona genera la imagen a mano y sube la FINAL: pasa a ser la portada del
proyecto y se descarga desde aqui. Se puede subir en cualquier momento (tambien
al principio, si ya la tiene).

Carpeta: proyectos/<id>/miniatura/{estado.json, referencia.*, final.*, vistas/}
"""
import json
import os
import shutil
import threading
import time

from loguru import logger
from PIL import Image

from app.services import claude_cli
from app.services.estudio import almacen, grafo

EXTENSIONES = {"JPEG": ".jpg", "PNG": ".png", "WEBP": ".webp"}
MAX_VISTAS = 4
_en_curso = set()
_candado = threading.Lock()

DEFECTOS = {
    "indicaciones": "",
    "texto_en_imagen": True,   # Flow / Nano Banana escriben bien texto corto
    "cantidad": 3,
    "modelo": "sonnet",
    "esfuerzo": "low",
}


def _dir(pid, *partes):
    return almacen.dir_proyecto(pid, "miniatura", *partes, crear=True)


def _archivo(pid, tipo):
    """Ruta del archivo `referencia` o `final` si existe."""
    base = _dir(pid)
    for ext in EXTENSIONES.values():
        ruta = os.path.join(base, tipo + ext)
        if os.path.isfile(ruta):
            return ruta
    return None


def estado(pid):
    datos = almacen.leer_json(os.path.join(_dir(pid), "estado.json"), {}) or {}
    rel = lambda r: f"miniatura/{os.path.basename(r)}" if r else None  # noqa: E731
    ref, fin = _archivo(pid, "referencia"), _archivo(pid, "final")
    return {
        "params": {**DEFECTOS, **(datos.get("params") or {})},
        "conceptos": datos.get("conceptos") or [],
        "analisis_referencia": datos.get("analisis_referencia") or "",
        "error": datos.get("error"),
        "generado": datos.get("generado"),
        "generando": pid in _en_curso,
        "referencia": rel(ref),
        "final": rel(fin),
        "version": int(max(os.path.getmtime(r) for r in (ref, fin) if r)) if (ref or fin) else None,
    }


def guardar_archivo(pid, tipo, datos: bytes):
    if tipo not in ("referencia", "final"):
        raise ValueError("tipo debe ser referencia o final")
    tmp = os.path.join(_dir(pid), f".{tipo}.subida")
    with open(tmp, "wb") as f:
        f.write(datos)
    try:
        with Image.open(tmp) as im:
            fmt = im.format
            im.verify()
    except Exception:  # noqa: BLE001
        os.remove(tmp)
        raise ValueError("no es una imagen valida (usa JPG, PNG o WEBP)")
    if fmt not in EXTENSIONES:
        os.remove(tmp)
        raise ValueError("formato no admitido (usa JPG, PNG o WEBP)")
    quitar_archivo(pid, tipo)
    os.replace(tmp, os.path.join(_dir(pid), tipo + EXTENSIONES[fmt]))


def quitar_archivo(pid, tipo):
    while (r := _archivo(pid, tipo)):
        os.remove(r)


# ------------------------------------------------------------------ contexto

def _contexto(pid):
    proyecto = almacen.cargar(pid)
    etapas = almacen.cargar_estado(pid).get("etapas", {})
    salida = lambda e: (etapas.get(e) or {}).get("salida") or {}  # noqa: E731
    guion = grafo.params_efectivos(proyecto, "guion")
    escenas_p = grafo.params_efectivos(proyecto, "escenas")
    render_p = grafo.params_efectivos(proyecto, "render")
    texto = (salida("guion").get("texto") or guion.get("texto_manual") or guion.get("material") or "").strip()
    if len(texto) > 6000:  # gancho + desarrollo + cierre: lo que mas pesa en una miniatura
        texto = texto[:4200] + "\n[...]\n" + texto[-1200:]
    return {
        "titulo": proyecto.get("titulo", ""),
        "idioma": guion.get("idioma", "es"),
        "guion": texto,
        "estilo": (escenas_p.get("estilo") or "").strip(),
        "indicaciones_escenas": (escenas_p.get("indicaciones") or "").strip(),
        "prompts_escenas": [e.get("image_prompt") for e in (salida("escenas").get("escenas") or [])
                            if e.get("image_prompt")][:4],
        "aspecto": render_p.get("aspecto", "9:16"),
        "recursos": salida("recursos").get("recursos") or [],
    }


def _preparar_vistas(pid, recursos):
    """Copia unas pocas miniaturas del catalogo (imagenes primero, repartidas por
    escenas) a miniatura/vistas/ para que Claude las mire."""
    carpeta = _dir(pid, "vistas")
    for f in os.listdir(carpeta):
        os.remove(os.path.join(carpeta, f))
    imagenes = [r for r in recursos if r.get("tipo") == "imagen"] or list(recursos)
    if not imagenes:
        return []
    paso = max(1, len(imagenes) // MAX_VISTAS)
    elegidas, nombres = imagenes[::paso][:MAX_VISTAS], []
    for r in elegidas:
        origen = os.path.join(almacen.dir_catalogo("miniaturas"), f"{r.get('miniatura') or r.get('id')}.jpg")
        if not os.path.isfile(origen):
            continue
        nombre = f"escena_{r['escena']}.jpg" if r.get("escena") is not None else f"recurso_{len(nombres) + 1}.jpg"
        shutil.copyfile(origen, os.path.join(carpeta, nombre))
        nombres.append(f"vistas/{nombre}")
    return nombres


PROMPT = """Eres director de arte de miniaturas de YouTube con mucho CTR. Propon {cantidad} conceptos
de miniatura para este video. La imagen la generara la persona a mano en Google Flow (Imagen /
Nano Banana) u otra herramienta: tu solo escribes los prompts.

VIDEO
- Titulo: {titulo}
- Idioma del publico: {idioma}
- Formato del video: {formato}
- Estilo visual de las escenas: {estilo}
{extra_escenas}
GUION (resumen de lo que se cuenta):
\"\"\"{guion}\"\"\"
{bloque_ref}{bloque_vistas}
INDICACIONES DE LA PERSONA: {indicaciones}

REGLAS DE UNA BUENA MINIATURA
- UN sujeto principal grande y claro (idealmente una cara con emocion fuerte, o un objeto iconico),
  maximo 3 elementos. Se tiene que entender en 1 segundo y a tamano movil.
- Contraste alto, colores saturados y complementarios, fondo simple o desenfocado.
- Genera curiosidad: promete algo que el titulo no dice del todo; no repitas el titulo.
- Texto: {regla_texto}
- Coherente con el contenido real del video (nada de clickbait falso).
- Relacion de aspecto {relacion}; deja el sujeto en un tercio y el texto en el espacio libre.

Los prompts en INGLES, detallados (sujeto, expresion, plano, luz, color, fondo, estilo, relacion de
aspecto). {texto_prompt}

Responde SOLO con JSON:
{{"analisis_referencia": "{pista_analisis}",
  "conceptos": [{{
    "nombre": "2-4 palabras",
    "idea": "por que funciona, 1-2 frases en espanol",
    "texto": "texto de la miniatura en el idioma del publico (2-4 palabras, o vacio)",
    "prompt": "prompt EN completo{sufijo_prompt}",
    "prompt_sin_texto": "el mismo prompt EN sin texto, dejando espacio limpio para ponerlo despues en Canva/Photoshop",
    "referencia_escena": numero de escena cuya imagen conviene usar como referencia en Flow, o null
  }}]}}"""


def _objeto_json(texto):
    """El objeto {..} de la respuesta (extraer_json prefiere listas y se quedaria
    con la lista de conceptos de dentro)."""
    i, j = texto.find("{"), texto.rfind("}")
    if i != -1 and j > i:
        try:
            return json.loads(texto[i:j + 1])
        except json.JSONDecodeError:
            pass
    datos = claude_cli.extraer_json(texto)
    return {"conceptos": datos} if isinstance(datos, list) else datos


def generar(pid, params=None):
    params = {**DEFECTOS, **(params or {})}
    with _candado:
        if pid in _en_curso:
            raise RuntimeError("ya se estan generando conceptos")
        _en_curso.add(pid)
    ruta = os.path.join(_dir(pid), "estado.json")
    previo = almacen.leer_json(ruta, {}) or {}
    almacen.escribir_json(ruta, {**previo, "params": params, "error": None})
    threading.Thread(target=_trabajo, args=(pid, params), daemon=True).start()


def _trabajo(pid, params):
    ruta = os.path.join(_dir(pid), "estado.json")
    try:
        c = _contexto(pid)
        ref = _archivo(pid, "referencia")
        vistas = _preparar_vistas(pid, c["recursos"])
        vertical = c["aspecto"] in ("9:16", "4:5")
        con_texto = bool(params.get("texto_en_imagen"))
        cantidad = max(1, min(5, int(params.get("cantidad") or 3)))

        bloque_ref = ""
        if ref:
            bloque_ref = (f"\nMINIATURA DE REFERENCIA: mira el archivo `{os.path.basename(ref)}` (herramienta Read). "
                          "Copia su ESTILO (composicion, encuadre, paleta, tipo y posicion del texto, energia), "
                          "no su contenido ni sus personas.\n")
        bloque_vistas = ""
        if vistas:
            bloque_vistas = ("\nIMAGENES DEL PROYECTO (mira con Read): " + ", ".join(f"`{v}`" for v in vistas) +
                             ". Mantén sus personajes, epoca y estetica para que la miniatura sea coherente "
                             "con el video. Si una sirve de referencia visual en Flow, indica su escena.\n")
        prompt = PROMPT.format(
            cantidad=cantidad, titulo=c["titulo"] or "(sin titulo)", idioma=c["idioma"],
            formato=("vertical 9:16 (Shorts/Reels/TikTok)" if vertical else "horizontal 16:9 (YouTube)"),
            estilo=c["estilo"] or "(sin definir: propon uno acorde al tema)",
            extra_escenas=(f"- Indicaciones de las escenas: {c['indicaciones_escenas']}\n" if c["indicaciones_escenas"] else "")
            + ("- Ejemplos de prompts de escena: " + " | ".join(c["prompts_escenas"]) + "\n" if c["prompts_escenas"] else ""),
            guion=c["guion"] or "(todavia no hay guion: basate en el titulo)",
            bloque_ref=bloque_ref, bloque_vistas=bloque_vistas,
            indicaciones=(params.get("indicaciones") or "").strip() or "(ninguna)",
            regla_texto=("2-4 palabras GRANDES, gruesas, muy legibles, con contorno o sombra; nunca una frase larga."
                         if con_texto else "sin texto en la imagen; deja un espacio limpio donde ira despues."),
            relacion="9:16 vertical (1080x1920)" if vertical else "16:9 horizontal (1280x720)",
            texto_prompt=('En "prompt" incluye el texto exacto entre comillas y como debe verse '
                          '(tipografia, color, contorno, posicion).' if con_texto else
                          'En "prompt" no pidas texto: deja espacio libre.'),
            sufijo_prompt=" con el texto exacto entre comillas" if con_texto else "",
            pista_analisis=("que tiene la referencia que conviene copiar, 1-2 frases" if ref else ""),
        )
        texto = claude_cli.ejecutar(prompt, modelo=params.get("modelo"), esfuerzo=params.get("esfuerzo"),
                                    tiempo_max_s=600, cwd=_dir(pid), permitidas=("Read",))
        datos = _objeto_json(texto)
        if not isinstance(datos, dict) or not isinstance(datos.get("conceptos"), list):
            raise ValueError("Claude no devolvio conceptos validos")
        conceptos = []
        for x in datos["conceptos"][:cantidad]:
            if not isinstance(x, dict) or not str(x.get("prompt", "")).strip():
                continue
            esc = x.get("referencia_escena")
            conceptos.append({
                "nombre": str(x.get("nombre", "")).strip()[:60],
                "idea": str(x.get("idea", "")).strip(),
                "texto": str(x.get("texto", "")).strip()[:80],
                "prompt": str(x.get("prompt", "")).strip(),
                "prompt_sin_texto": str(x.get("prompt_sin_texto", "")).strip(),
                "referencia_escena": esc if isinstance(esc, int) else None,
            })
        if not conceptos:
            raise ValueError("Claude no devolvio conceptos validos")
        almacen.escribir_json(ruta, {"params": params, "conceptos": conceptos, "error": None,
                                     "analisis_referencia": str(datos.get("analisis_referencia") or "").strip(),
                                     "generado": time.time()})
    except Exception as e:  # noqa: BLE001
        logger.exception(f"miniatura {pid}")
        previo = almacen.leer_json(ruta, {}) or {}
        almacen.escribir_json(ruta, {**previo, "params": params, "error": str(e)[:400]})
    finally:
        _en_curso.discard(pid)
