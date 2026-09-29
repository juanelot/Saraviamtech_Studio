"""
Etapa GUION: del material de la persona a un texto de locucion.

Tres modos:
  redactar  Claude (CLI, suscripcion) redacta a partir del material, con la
            duracion objetivo convertida a presupuesto de palabras.
  literal   el material ES el guion: se usa tal cual (limpiado).
  (manual)  si la persona edito el guion generado, `texto_manual` manda y no se
            llama a nadie. Regenerar = vaciar `texto_manual`.
"""
import os
import re

from app.services import claude_cli

DEFECTOS = {
    "material": "",
    "instrucciones": "",
    "duracion_s": 60,
    "idioma": "es",
    "modo": "redactar",
    "texto_manual": "",
    "modelo": "sonnet",
    "esfuerzo": "low",
}

# Palabras por segundo de una locucion normal (TTS a velocidad 1.0).
PALABRAS_POR_SEGUNDO = {"es": 2.5, "en": 2.6, "pt": 2.4, "fr": 2.5, "it": 2.5, "de": 2.2}

NOMBRE_IDIOMA = {"es": "espanol", "en": "ingles", "pt": "portugues", "fr": "frances",
                 "it": "italiano", "de": "aleman"}


DURACION_MAXIMA_S = 3 * 3600  # 3 horas


def tiempo_claude(duracion_s):
    """Techo de espera para Claude: crece con la duracion (guiones largos tardan)."""
    return int(min(3600, 300 + duracion_s * 0.6))


def presupuesto(duracion_s, idioma):
    pps = PALABRAS_POR_SEGUNDO.get(idioma, 2.5)
    return max(15, int(duracion_s * pps))


def limpiar(texto: str) -> str:
    texto = texto.replace("\r\n", "\n")
    texto = re.sub(r"[ \t]+", " ", texto)
    texto = re.sub(r"\n{3,}", "\n\n", texto)
    return texto.strip()


def _prompt(p):
    palabras = presupuesto(int(p["duracion_s"]), p["idioma"])
    idioma = NOMBRE_IDIOMA.get(p["idioma"], p["idioma"])
    instrucciones = (p.get("instrucciones") or "").strip() or "(ninguna)"
    return f"""Eres guionista de videos narrados para redes sociales.
Escribe el texto de LOCUCION de un video a partir del MATERIAL de abajo.

Reglas:
- Idioma: {idioma}.
- Extension: unas {palabras} palabras (entre {int(palabras * 0.85)} y {int(palabras * 1.15)}). Es para unos {p['duracion_s']} segundos de voz.
- Usa solo hechos del material; no inventes cifras ni nombres.
- Primera frase con gancho; nada de "hola", "bienvenidos" ni "en este video".
- Frases cortas y claras, pensadas para oirse. Parrafos separados por una linea en blanco.
- Solo el texto que se lee en voz alta: sin titulos, sin markdown, sin emojis, sin indicaciones de escena ni "narrador:".

Indicaciones de la persona: {instrucciones}

MATERIAL:
<<<
{p['material'].strip()}
>>>

Responde SOLO con el guion."""


def _prompt_ampliar(p, texto, objetivo):
    idioma = NOMBRE_IDIOMA.get(p["idioma"], p["idioma"])
    return f"""Este guion de locucion en {idioma} tiene {len(texto.split())} palabras y necesita unas {objetivo}.
Amplialo hasta esa extension desarrollando mas cada idea con hechos del MATERIAL
(contexto, ejemplos, consecuencias). Manten el tono, el orden y el gancho inicial;
no repitas frases ni rellenes con muletillas. Mismas reglas: solo texto para leer
en voz alta, sin titulos ni markdown, parrafos separados por linea en blanco.

MATERIAL:
<<<
{p['material'].strip()}
>>>

GUION ACTUAL:
<<<
{texto}
>>>

Responde SOLO con el guion completo ampliado."""


def ejecutar(ctx):
    p = ctx.params
    dir_salida = ctx.dir("guion")
    if (p.get("texto_manual") or "").strip():
        texto, origen = limpiar(p["texto_manual"]), "manual"
    elif p["modo"] == "literal":
        if not p["material"].strip():
            raise ValueError("el material esta vacio")
        texto, origen = limpiar(p["material"]), "literal"
    else:
        if not p["material"].strip():
            raise ValueError("el material esta vacio: escribe o pega de que trata el video")
        duracion = max(10, min(int(p["duracion_s"]), DURACION_MAXIMA_S))
        objetivo = presupuesto(duracion, p["idioma"])
        espera = tiempo_claude(duracion)
        ctx.avisar(f"Claude ({p['modelo']}/{p['esfuerzo']}) redactando ~{objetivo} palabras", 10)
        texto = claude_cli.ejecutar(_prompt({**p, "duracion_s": duracion}), modelo=p["modelo"],
                                    esfuerzo=p["esfuerzo"], tiempo_max_s=espera)
        texto = limpiar(re.sub(r"^```\w*|```$", "", texto.strip()))
        # En guiones largos Claude suele quedarse corto: una pasada para ampliar.
        palabras = len(texto.split())
        if palabras < objetivo * 0.75:
            ctx.avisar(f"guion corto ({palabras}/{objetivo} palabras): Claude lo amplia", 55)
            texto = limpiar(claude_cli.ejecutar(
                _prompt_ampliar(p, texto, objetivo), modelo=p["modelo"],
                esfuerzo=p["esfuerzo"], tiempo_max_s=espera))
        origen = "claude"

    with open(os.path.join(dir_salida, "guion.txt"), "w", encoding="utf-8") as f:
        f.write(texto)
    palabras = len(texto.split())
    pps = PALABRAS_POR_SEGUNDO.get(p["idioma"], 2.5)
    ctx.avisar(f"guion listo: {palabras} palabras", 100)
    return {"texto": texto, "origen": origen, "palabras": palabras,
            "duracion_estimada_s": round(palabras / pps)}
