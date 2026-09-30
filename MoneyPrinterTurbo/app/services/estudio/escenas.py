"""
Etapa ESCENAS: el guion ya locutado, cortado en escenas con su tiempo real, y
(si se pide) los prompts de IMAGEN y de VIDEO que escribe Claude para cada una.

Para que sirve: la persona crea el contenido A MANO con la herramienta que
quiera (Google Flow, Vibes, la extension "AI Content Generator"...) y despues lo
sube. Nada de APIs de imagen: el Estudio solo usa el CLI de Claude.

Salidas:
  - escenas: [{scene_number, inicio, fin, duracion, planos, narration,
               image_prompt, video_prompt}]
  - escenas/script.json en el formato EXACTO de la extension:
        {"scenes": [{"scene_number", "image_prompt", "video_prompt", "narration"}]}

Agrupacion: planos consecutivos de la voz hasta llegar a `segundos` (un clip de
Flow dura 8 s). Una escena nunca parte un plano, asi la imagen cambia justo
cuando cambia la frase. `segundos` = 0 -> una escena por plano.

Escenas FIJAS (`fijas`, se lee con .get; lo pone "Crear video" de un prompt
maestro): las escenas y sus prompts vienen hechos. Solo se calcula cuando empieza
y acaba cada una sobre la voz: por palabras si todas traen su narracion, o
repartiendo por su duracion si no.

Prompts: `generar` = "no" (solo agrupa, sin Claude) | "imagenes" |
"imagenes_videos". La respuesta de Claude se cachea con la huella de SUS
entradas (escenas/base.json): corregir un prompt a mano (`ediciones`) no vuelve
a llamar a Claude.
"""
import hashlib
import json
import os

from loguru import logger

from app.services import claude_cli
from app.services.estudio import almacen

DEFECTOS = {
    "segundos": 6.0,
    "generar": "imagenes",
    "estilo": "",
    "indicaciones": "",
    "idioma_prompts": "en",
    "ediciones": {},
    "modelo": "sonnet",
    "esfuerzo": "low",
}

TANDA = 40
NOMBRE_IDIOMA = {"en": "English", "es": "Spanish", "pt": "Portuguese"}


def huella(ctx):
    # El formato del video cambia como se encuadra la imagen: entra en la firma.
    return {"aspecto": ctx.params_de("render").get("aspecto")}


def agrupar(planos, segundos):
    if not planos:
        return []
    grupos, actual = [], []
    for x in planos:
        actual.append(x)
        if segundos <= 0 or (actual[-1]["fin"] - actual[0]["inicio"]) >= segundos:
            grupos.append(actual)
            actual = []
    if actual:
        if grupos and (actual[-1]["fin"] - actual[0]["inicio"]) < segundos / 2:
            grupos[-1].extend(actual)
        else:
            grupos.append(actual)
    escenas = []
    for n, g in enumerate(grupos, start=1):
        escenas.append({
            "scene_number": n,
            "inicio": g[0]["inicio"],
            "fin": g[-1]["fin"],
            "duracion": round(g[-1]["fin"] - g[0]["inicio"], 2),
            "planos": [x["i"] for x in g],
            "narration": " ".join(x["texto"] for x in g).strip(),
            "image_prompt": "",
            "video_prompt": "",
        })
    return escenas


def _tiempos_palabras(ctx, planos):
    """[(inicio, fin)] de cada palabra dicha: los de edge-tts si estan, si no se
    reparten las palabras de cada plano a partes iguales."""
    datos = almacen.leer_json(ctx.dir("voz", "palabras.json", crear=False))
    if datos:
        return [(float(a), float(b)) for a, b, _t in datos]
    tiempos = []
    for x in planos:
        n = max(1, len(x["texto"].split()))
        paso = (x["fin"] - x["inicio"]) / n
        tiempos += [(x["inicio"] + k * paso, x["inicio"] + (k + 1) * paso) for k in range(n)]
    return tiempos


def fijas_en_tiempo(fijas, planos, duracion, tiempos):
    n = len(fijas)
    cortes = [0.0]
    if all((f.get("narracion") or "").strip() for f in fijas) and len(tiempos) > n:
        pesos = [max(1, len(f["narracion"].split())) for f in fijas]
        total, acum = sum(pesos), 0
        for k in range(n - 1):
            acum += pesos[k]
            # Mismas palabras que la voz: corte exacto; si no, proporcional.
            j = acum if total == len(tiempos) else round(acum / total * len(tiempos))
            j = min(len(tiempos) - 1, max(1, j))
            cortes.append((tiempos[j - 1][1] + tiempos[j][0]) / 2)
    else:
        pesos = [float(f.get("duracion_s") or 0) or 1.0 for f in fijas]
        total = sum(pesos)
        cortes += [duracion * sum(pesos[:k + 1]) / total for k in range(n - 1)]
    cortes.append(duracion)
    minimo = min(0.5, duracion / max(1, n) / 2)
    for k in range(1, len(cortes)):  # siempre crecientes, ninguna escena vacia
        cortes[k] = max(cortes[k], cortes[k - 1] + minimo)
    cortes[-1] = max(cortes[-1], duracion)
    escenas = []
    for k, f in enumerate(fijas):
        a, b = round(cortes[k], 3), round(cortes[k + 1], 3)
        escenas.append({
            "scene_number": k + 1, "inicio": a, "fin": b, "duracion": round(b - a, 2),
            "planos": [x["i"] for x in planos if x["inicio"] < b and x["fin"] > a],
            "narration": (f.get("narracion") or "").strip() or " ".join(
                x["texto"] for x in planos if a <= (x["inicio"] + x["fin"]) / 2 < b).strip(),
            "image_prompt": " ".join(str(f.get("imagen") or "").split()),
            "video_prompt": " ".join(str(f.get("video") or "").split()),
        })
    return escenas


def _prompt(tanda, guion, p, aspecto, con_video, total):
    estilo = (p.get("estilo") or "").strip() or "(elige un estilo visual coherente y cinematografico para el tema)"
    indic = (p.get("indicaciones") or "").strip() or "(ninguna)"
    idioma = NOMBRE_IDIOMA.get(p["idioma_prompts"], p["idioma_prompts"])
    formato = {"9:16": "vertical 9:16", "16:9": "horizontal 16:9", "1:1": "square 1:1"}.get(aspecto, aspecto)
    lista = "\n".join(f"{e['scene_number']} ({e['duracion']:.1f}s): {e['narration']}" for e in tanda)
    campos = '"image_prompt": "..."' + (', "video_prompt": "..."' if con_video else "")
    extra_video = (
        "\n- video_prompt: animates THAT image (image-to-video, ~8 s clip): camera movement, subject motion, "
        "atmosphere changes. One or two sentences, no cuts, no text overlays." if con_video else ""
    )
    return f"""You are a visual director. Write prompts to CREATE the visuals of a narrated video,
one per scene, that the person will generate manually in Google Flow (or similar).

FULL SCRIPT (context: characters, places, era, tone):
<<<
{guion}
>>>

VISUAL STYLE (apply to EVERY image): {estilo}
FRAME FORMAT: {formato}
EXTRA INSTRUCTIONS: {indic}
Total scenes in the video: {total}

SCENES (number (duration): narration spoken during that scene):
{lista}

Rules:
- Language of the prompts: {idioma}.
- image_prompt: ONE self-contained paragraph (the generator does not see other scenes): subject,
  action, setting, era, lighting, composition and camera framing, style. Repeat the SAME physical
  description of recurring characters/places in every scene where they appear, so they stay consistent.
- Illustrate what is SAID in that scene; be concrete, avoid abstract words.
- No text, letters, logos or watermarks in the image unless the scene truly needs it.{extra_video}
- Single line strings: no line breaks, no markdown, no bullet points.

Return ONLY JSON, one element per scene of the list:
[{{"scene_number": <n>, {campos}}}]"""


def _clave(escenas, guion, p, aspecto):
    datos = {"n": [(e["scene_number"], e["narration"], e["duracion"]) for e in escenas], "guion": guion,
             "p": {k: p.get(k) for k in ("generar", "estilo", "indicaciones", "idioma_prompts", "modelo", "esfuerzo")},
             "aspecto": aspecto}
    return hashlib.sha256(json.dumps(datos, ensure_ascii=False).encode()).hexdigest()[:20]


def _con_claude(escenas, guion, p, aspecto, ctx):
    con_video = p["generar"] == "imagenes_videos"
    tandas = [escenas[i:i + TANDA] for i in range(0, len(escenas), TANDA)]
    resultado = {}
    for k, tanda in enumerate(tandas):
        ctx.avisar(f"Claude escribiendo prompts: escenas {tanda[0]['scene_number']}-{tanda[-1]['scene_number']}"
                   f" ({k + 1}/{len(tandas)})", 10 + 80 * k / len(tandas))
        texto = claude_cli.ejecutar(_prompt(tanda, guion, p, aspecto, con_video, len(escenas)),
                                    modelo=p["modelo"], esfuerzo=p["esfuerzo"],
                                    tiempo_max_s=min(3600, 240 + 12 * len(tanda)))
        try:
            datos = claude_cli.extraer_json(texto)
        except ValueError as e:
            logger.warning(f"tanda {k + 1}: sin JSON valido ({e})")
            datos = []
        for d in datos if isinstance(datos, list) else []:
            try:
                n = int(d.get("scene_number"))
            except (TypeError, ValueError):
                continue
            resultado[n] = {"image_prompt": " ".join(str(d.get("image_prompt", "")).split()),
                            "video_prompt": " ".join(str(d.get("video_prompt", "")).split()) if con_video else ""}
    return resultado


def ejecutar(ctx):
    p = ctx.params
    voz = ctx.salidas["voz"] or {}
    planos = voz.get("planos") or []
    if not planos:
        raise ValueError("la voz no produjo planos")
    fijas = p.get("fijas") or []
    if fijas:
        escenas = fijas_en_tiempo(fijas, planos, float(voz.get("duracion") or planos[-1]["fin"]),
                                  _tiempos_palabras(ctx, planos))
    else:
        escenas = agrupar(planos, float(p["segundos"] or 0))
    carpeta = ctx.dir("escenas")
    aspecto = ctx.params_de("render").get("aspecto", "9:16")

    if p["generar"] in ("imagenes", "imagenes_videos") and not fijas:
        guion = " ".join(x["texto"] for x in planos)
        ruta_base = os.path.join(carpeta, "base.json")
        clave = _clave(escenas, guion, p, aspecto)
        base = almacen.leer_json(ruta_base, {}) or {}
        if base.get("clave") == clave:
            ctx.avisar("prompts de Claude reutilizados (mismas entradas)", 50)
            prompts = {int(k): v for k, v in base["prompts"].items()}
        else:
            prompts = _con_claude(escenas, guion, p, aspecto, ctx)
            almacen.escribir_json(ruta_base, {"clave": clave, "prompts": {str(k): v for k, v in prompts.items()}})
        faltan = [e["scene_number"] for e in escenas if not prompts.get(e["scene_number"], {}).get("image_prompt")]
        if faltan:
            logger.warning(f"escenas sin prompt de Claude: {faltan[:20]}{'...' if len(faltan) > 20 else ''}")
        for e in escenas:
            e.update(prompts.get(e["scene_number"], {}))

    ediciones = p.get("ediciones") or {}
    for e in escenas:
        ed = ediciones.get(str(e["scene_number"])) or {}
        for campo in ("image_prompt", "video_prompt"):
            if isinstance(ed.get(campo), str) and ed[campo].strip():
                e[campo] = " ".join(ed[campo].split())
                e[f"{campo}_editado"] = True

    script = {"scenes": [{"scene_number": e["scene_number"], "image_prompt": e["image_prompt"],
                          "video_prompt": e["video_prompt"], "narration": e["narration"]} for e in escenas]}
    almacen.escribir_json(os.path.join(carpeta, "script.json"), script)
    con_prompt = sum(1 for e in escenas if e["image_prompt"])
    ctx.avisar(f"{len(escenas)} escenas, {con_prompt} con prompt de imagen", 100)
    return {"escenas": escenas, "total": len(escenas), "con_prompt": con_prompt,
            "generar": p["generar"], "script": "escenas/script.json"}
