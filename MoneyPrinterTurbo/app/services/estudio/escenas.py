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
import bisect
import difflib
import hashlib
import json
import os
import re
import unicodedata

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


FORMATOS = {
    # (como se le pide a Claude, palabras que NO pueden salir en un prompt de ese formato)
    "16:9": ("16:9 landscape widescreen", ["9:16", "vertical", "portrait"]),
    "9:16": ("9:16 vertical portrait", ["16:9", "landscape", "widescreen"]),
    "1:1": ("1:1 square", ["9:16", "16:9", "vertical", "portrait", "landscape", "widescreen"]),
}
# Una imagen fija no lleva movimiento, camara ni tiempos.
PROHIBIDAS_IMAGEN = ["seconds", "camera", "motion", "push-in", "zoom"]
CONTINUIDAD = 3        # escenas ya escritas que se pasan para mantener la continuidad
REINTENTOS = 2         # rondas para rehacer las escenas que no pasan la validacion
VERSION_PROMPTS = "2"  # v2: formato explicito, imagen fija, contexto igual en todos los lotes


def _formato(aspecto):
    return FORMATOS.get(aspecto, FORMATOS["16:9"])


def _contiene(texto, termino):
    if ":" in termino:
        return termino in texto
    return re.search(rf"\b{re.escape(termino)}\b", texto, re.IGNORECASE) is not None


def problemas_prompt(prompt, aspecto):
    """Lo que falla en un image_prompt: vacio, formato contrario o movimiento."""
    if not (prompt or "").strip():
        return ["sin prompt de imagen"]
    salida = []
    malas = [t for t in _formato(aspecto)[1] if _contiene(prompt, t)]
    if malas:
        salida.append(f"formato contrario ({', '.join(malas)})")
    mov = [t for t in PROHIBIDAS_IMAGEN if _contiene(prompt, t)]
    if mov:
        salida.append(f"movimiento en una imagen fija ({', '.join(mov)})")
    return salida


def _prompt(tanda, guion, p, aspecto, con_video, total, previas=(), arreglar=None):
    estilo = (p.get("estilo") or "").strip()
    indic = (p.get("indicaciones") or "").strip() or "(none)"
    idioma = NOMBRE_IDIOMA.get(p["idioma_prompts"], p["idioma_prompts"])
    formato, prohibidas = _formato(aspecto)
    lista = "\n".join(f"{e['scene_number']} ({e['duracion']:.1f}s): {e['narration']}" for e in tanda)
    campos = '"image_prompt": "..."' + (', "video_prompt": "..."' if con_video else "")
    extra_video = (
        "\n- video_prompt: animates THAT image (image-to-video, ~8 s clip): camera movement, subject motion, "
        "atmosphere changes. One or two sentences, no cuts, no text overlays. Motion goes ONLY here." if con_video else ""
    )
    continuidad = ""
    if previas:
        continuidad = ("\n\nPREVIOUS SCENES (already written; keep characters, places and style consistent):\n"
                       + "\n".join(f"{e['scene_number']}: narration: {e['narration']}\n   image_prompt: {e['image_prompt']}"
                                    for e in previas))
    rehacer = ""
    if arreglar:
        rehacer = ("\n\nTHESE SCENES WERE REJECTED by an automatic check; rewrite them and avoid the problem:\n"
                   + "\n".join(f"- scene {n}: {', '.join(m)}" for n, m in arreglar.items()))
    regla_estilo = ("- Include the VISUAL STYLE text in every image_prompt, word for word (do not paraphrase it)."
                    if estilo else
                    "- Choose ONE coherent cinematic visual style and use the same wording in every image_prompt.")
    return f"""You are a visual director. Write prompts to CREATE the visuals of a narrated video,
one per scene, that the person will generate manually in Google Flow (or similar).

FULL SCRIPT (context: characters, places, era, tone):
<<<
{guion}
>>>

VISUAL STYLE (apply to EVERY image): {estilo or "(not given)"}
FRAME FORMAT: {formato}. Mandatory for every scene; it overrides anything else.
EXTRA INSTRUCTIONS (apply to EVERY scene): {indic}
Total scenes in the video: {total}{continuidad}

SCENES TO WRITE NOW (number (duration): narration spoken during that scene):
{lista}{rehacer}

Rules:
- Language of the prompts: {idioma}.
- image_prompt: ONE self-contained paragraph (the generator does not see other scenes) describing a
  single STILL image: subject, action frozen in that instant, setting, era, lighting, composition
  (shot type and angle), style. Repeat the SAME physical description of recurring characters/places in
  every scene where they appear, so they stay consistent.
- image_prompt is a still picture: never mention movement, time or duration (no "seconds", "camera",
  "motion", "push-in", "zoom", "pan", "animated").
{regla_estilo}
- State the frame format as "{formato}" in every image_prompt. Never write these words, in any
  sense: {", ".join(prohibidas)}.
- Illustrate what is SAID in that scene; be concrete, avoid abstract words.
- No text, letters, logos or watermarks in the image unless the scene truly needs it.{extra_video}
- Single line strings: no line breaks, no markdown, no bullet points.

Return ONLY JSON, one element per scene of the list:
[{{"scene_number": <n>, {campos}}}]"""


def _clave(escenas, guion, p, aspecto):
    datos = {"v": VERSION_PROMPTS, "n": [(e["scene_number"], e["narration"], e["duracion"]) for e in escenas],
             "guion": guion,
             "p": {k: p.get(k) for k in ("generar", "estilo", "indicaciones", "idioma_prompts", "modelo", "esfuerzo")},
             "aspecto": aspecto}
    return hashlib.sha256(json.dumps(datos, ensure_ascii=False).encode()).hexdigest()[:20]


def _pedir(tanda, guion, p, aspecto, con_video, total, previas, arreglar=None):
    texto = claude_cli.ejecutar(_prompt(tanda, guion, p, aspecto, con_video, total, previas, arreglar),
                                modelo=p["modelo"], esfuerzo=p["esfuerzo"],
                                tiempo_max_s=min(3600, 240 + 12 * len(tanda)))
    try:
        datos = claude_cli.extraer_json(texto)
    except ValueError as e:
        logger.warning(f"escenas {tanda[0]['scene_number']}-{tanda[-1]['scene_number']}: sin JSON valido ({e})")
        datos = []
    validos = {e["scene_number"] for e in tanda}
    salida = {}
    for d in datos if isinstance(datos, list) else []:
        try:
            n = int(d.get("scene_number"))
        except (TypeError, ValueError, AttributeError):
            continue
        if n in validos:
            salida[n] = {"image_prompt": " ".join(str(d.get("image_prompt", "")).split()),
                         "video_prompt": " ".join(str(d.get("video_prompt", "")).split()) if con_video else ""}
    return salida


def _con_claude(escenas, guion, p, aspecto, ctx):
    """Todos los lotes reciben el MISMO contexto (guion entero, estilo, indicaciones,
    formato, idioma) mas las ultimas escenas ya escritas. Despues se validan y las
    que fallan se rehacen (hasta REINTENTOS rondas)."""
    con_video = p["generar"] == "imagenes_videos"
    por_n = {e["scene_number"]: e for e in escenas}
    tandas = [escenas[i:i + TANDA] for i in range(0, len(escenas), TANDA)]
    resultado = {}

    def previas_a(n):
        hechas = [k for k in sorted(resultado) if k < n and resultado[k].get("image_prompt")][-CONTINUIDAD:]
        return [{**por_n[k], **resultado[k]} for k in hechas]

    for k, tanda in enumerate(tandas):
        ctx.avisar(f"Claude escribiendo prompts: escenas {tanda[0]['scene_number']}-{tanda[-1]['scene_number']}"
                   f" ({k + 1}/{len(tandas)})", 10 + 70 * k / len(tandas))
        resultado.update(_pedir(tanda, guion, p, aspecto, con_video, len(escenas),
                                previas_a(tanda[0]["scene_number"])))

    for ronda in range(REINTENTOS):
        malas = {e["scene_number"]: problemas_prompt(resultado.get(e["scene_number"], {}).get("image_prompt"), aspecto)
                 for e in escenas}
        malas = {n: m for n, m in malas.items() if m}
        if not malas:
            break
        ctx.avisar(f"rehaciendo {len(malas)} escenas que no pasaron la validacion (ronda {ronda + 1})", 82 + 6 * ronda)
        lista = [por_n[n] for n in sorted(malas)]
        for i in range(0, len(lista), TANDA):
            trozo = lista[i:i + TANDA]
            resultado.update(_pedir(trozo, guion, p, aspecto, con_video, len(escenas),
                                    previas_a(trozo[0]["scene_number"]),
                                    {e["scene_number"]: malas[e["scene_number"]] for e in trozo}))
    return resultado


def _norm(w):
    t = unicodedata.normalize("NFD", w.lower())
    t = "".join(c for c in t if unicodedata.category(c) != "Mn")
    return re.sub(r"[^\w%$€]+", "", t)


def texto_guion(ctx, voz, planos):
    """El texto ORIGINAL con su puntuacion: el de la voz propia (si lo hay), el del
    guion, o como ultimo recurso el de los planos (sin puntuacion)."""
    if (voz.get("texto") or "").strip():
        return voz["texto"].strip()
    ruta = ctx.dir("guion", "guion.txt", crear=False)
    if os.path.isfile(ruta):
        with open(ruta, encoding="utf-8") as f:
            texto = f.read().strip()
        if texto:
            return texto
    return " ".join(x["texto"] for x in planos)


def narraciones_exactas(escenas, planos, texto):
    """Pone en cada escena el trozo EXACTO del guion (con puntuacion) que se dice en
    ella. Se corta en codigo: las palabras de los planos (sin puntuacion) se casan
    con las del guion y cada frontera de escena cae en la palabra que le toca."""
    guion = texto.split()
    if not guion or not escenas:
        return
    texto_planos = {x["i"]: x["texto"] for x in planos}
    dichas, fronteras = [], []
    for e in escenas:
        fronteras.append(len(dichas))
        for i in e["planos"]:
            dichas += texto_planos.get(i, "").split()
    sm = difflib.SequenceMatcher(None, [_norm(w) for w in dichas], [_norm(w) for w in guion], autojunk=False)
    mapa = {}
    for b in sm.get_matching_blocks():
        for k in range(b.size):
            mapa[b.a + k] = b.b + k
    casadas = sorted(mapa)

    def en_guion(j):
        if j <= 0:
            return 0
        if j >= len(dichas):
            return len(guion)
        if j in mapa:
            return mapa[j]
        pos = bisect.bisect_left(casadas, j)
        antes = casadas[pos - 1] if pos > 0 else None
        despues = casadas[pos] if pos < len(casadas) else None
        if antes is not None and despues is not None:
            return round(mapa[antes] + (mapa[despues] - mapa[antes]) * (j - antes) / (despues - antes))
        if antes is not None:
            return min(len(guion), mapa[antes] + (j - antes))
        if despues is not None:
            return max(0, mapa[despues] - (despues - j))
        return round(j * len(guion) / len(dichas))

    cortes = [en_guion(j) for j in fronteras] + [len(guion)]
    cortes[0] = 0
    for k in range(1, len(cortes)):
        cortes[k] = min(len(guion), max(cortes[k], cortes[k - 1]))
    for k, e in enumerate(escenas):
        e["narration"] = " ".join(guion[cortes[k]:cortes[k + 1]])


def validar(escenas, texto, aspecto, generar, fijas):
    """Comprobaciones finales sobre lo que se va a guardar en script.json."""
    avisos = []
    nums = [e["scene_number"] for e in escenas]
    if nums != list(range(1, len(escenas) + 1)):
        avisos.append({"escena": None, "problemas": ["los numeros de escena no son consecutivos desde 1"]})
    if not fijas and " ".join(e["narration"] for e in escenas).split() != texto.split():
        avisos.append({"escena": None, "problemas": ["la narracion unida no coincide con el guion original"]})
    if any(not e["narration"].strip() for e in escenas) and not fijas:
        vacias = [e["scene_number"] for e in escenas if not e["narration"].strip()]
        avisos.append({"escena": None, "problemas": [f"escenas sin narracion: {vacias[:10]}"]})
    if generar in ("imagenes", "imagenes_videos"):
        for e in escenas:
            m = problemas_prompt(e["image_prompt"], aspecto)
            if m:
                avisos.append({"escena": e["scene_number"], "problemas": m})
    return avisos


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
    # Un solo formato para imagenes y montaje: el del paso Video (16:9 por defecto).
    aspecto = ctx.params_de("render").get("aspecto") or "16:9"
    guion = texto_guion(ctx, voz, planos)
    if not fijas:
        # La narracion es el texto EXACTO del guion (con puntuacion), cortado aqui;
        # Claude solo escribe los prompts.
        narraciones_exactas(escenas, planos, guion)

    if p["generar"] in ("imagenes", "imagenes_videos") and not fijas:
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

    avisos = validar(escenas, guion, aspecto, p["generar"], bool(fijas))
    if avisos:
        logger.warning(f"escenas: {len(avisos)} avisos de validacion: {avisos[:5]}")
    script = {"scenes": [{"scene_number": e["scene_number"], "image_prompt": e["image_prompt"],
                          "video_prompt": e["video_prompt"], "narration": e["narration"]} for e in escenas]}
    almacen.escribir_json(os.path.join(carpeta, "script.json"), script)
    con_prompt = sum(1 for e in escenas if e["image_prompt"])
    ctx.avisar(f"{len(escenas)} escenas, {con_prompt} con prompt de imagen"
               + (f", {len(avisos)} avisos de validacion" if avisos else ", validacion OK"), 100)
    return {"escenas": escenas, "total": len(escenas), "con_prompt": con_prompt,
            "generar": p["generar"], "script": "escenas/script.json", "aspecto": aspecto, "avisos": avisos}
