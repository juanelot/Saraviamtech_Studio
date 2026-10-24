"""
Herramientas para publicar un video ya montado (tarjeta "Publicar" del paso Video):

  metadatos  titulos, descripcion y hashtags para YouTube, TikTok o Instagram.
  capitulos  capitulos de YouTube (0:00 ...) con los tiempos del video final.
  traducir   los subtitulos en otro idioma (SRT para subir a la plataforma).
  gancho     nota de los primeros segundos, que funciona y que no, y ganchos
             alternativos que caben en el primer plano (se pueden regrabar ahi).

Todo trabaja con los subtitulos EN TIEMPO DEL VIDEO: las frases corregidas en el
editor (subs_texto) y colocadas donde estan sus trozos (subs_tramos). Lo que sale
se guarda en render/publicar.json para no volver a pedirlo.
"""
import json
import os
import re

from app.services import claude_cli
from app.services.estudio import acabado, almacen, capas, grafo, guion, retoques

MODELO, ESFUERZO = "sonnet", "low"
PLATAFORMAS = {"youtube": "YouTube", "tiktok": "TikTok", "instagram": "Instagram Reels"}
IDIOMAS = {"es": "espanol", "en": "ingles", "pt": "portugues", "fr": "frances", "it": "italiano", "de": "aleman"}
TANDA = 60          # frases por llamada al traducir
CAPITULO_MIN_S = 10  # YouTube pide capitulos de 10 s o mas, al menos 3 y el primero en 0:00
GANCHO_S = 6.0


def _datos(pid):
    proyecto = almacen.cargar(pid)
    estado = almacen.cargar_estado(pid)
    salidas = {e: (estado["etapas"].get(e) or {}).get("salida") or {} for e in grafo.ETAPAS}
    return proyecto, salidas


def _ruta(pid):
    return almacen.dir_proyecto(pid, "render", "publicar.json")


def guardado(pid):
    return almacen.leer_json(_ruta(pid), {}) or {}


def _guardar(pid, clave, valor):
    datos = guardado(pid)
    datos[clave] = valor
    almacen.dir_proyecto(pid, "render", crear=True)
    almacen.escribir_json(_ruta(pid), datos)
    return valor


def subtitulos_del_video(pid):
    """[(inicio, fin, texto)] tal como salen en el video montado."""
    proyecto, salidas = _datos(pid)
    voz = salidas["voz"]
    if not voz.get("duracion"):
        raise ValueError("todavia no hay voz")
    sin_voz = bool(voz.get("sin_voz"))
    srt = almacen.dir_proyecto(pid, "render", "voz_clips.srt") if sin_voz else almacen.dir_proyecto(pid, voz.get("srt") or "")
    if not os.path.isfile(srt):
        raise ValueError("no hay subtitulos (sin voz, monta el video primero)")
    p = grafo.params_efectivos(proyecto, "render")
    lineas = acabado.lineas_srt(srt)
    if not sin_voz:
        lineas = acabado.con_cambios(lineas, p.get("subs_texto"))
    col = capas.colocacion(p, [], float(voz["duracion"]), sin_voz)
    salida = []
    for a, b, t in lineas:
        if not t:
            continue
        for x, y, en in col["subs"]:
            ini, fin = max(a, x), min(b, y)
            if fin - ini >= 0.05:
                salida.append((round(ini - x + en, 3), round(fin - x + en, 3), t))
    return sorted(salida)


def _t(s, ms=True):
    h, m, seg = int(s // 3600), int(s % 3600 // 60), s % 60
    return f"{h:02d}:{m:02d}:{seg:06.3f}".replace(".", ",") if ms else (f"{h}:{m:02d}:{int(seg):02d}" if h else f"{m}:{int(seg):02d}")


def srt(lineas):
    return "\n".join(f"{n}\n{_t(a)} --> {_t(b)}\n{t}\n" for n, (a, b, t) in enumerate(lineas, start=1))


def _objeto(texto):
    """El primer objeto JSON de la respuesta (extraer_json prefiere listas: aqui se quiere el objeto entero)."""
    bloque = re.search(r"```(?:json)?\s*(.*?)```", texto, re.DOTALL)
    texto = (bloque.group(1) if bloque else texto).strip()
    i, j = texto.find("{"), texto.rfind("}")
    if i != -1 and j > i:
        try:
            return json.loads(texto[i:j + 1])
        except json.JSONDecodeError:
            pass
    raise RuntimeError(f"Claude no devolvio un JSON valido: {texto[:200]}")


def _idioma(proyecto):
    return guion.NOMBRE_IDIOMA.get(str(grafo.params_efectivos(proyecto, "guion").get("idioma") or "es").split("-")[0], "espanol")


def _texto(salidas, lineas):
    return (salidas["guion"].get("texto") or " ".join(t for _a, _b, t in lineas)).strip()[:6000]


def metadatos(pid, plataforma="youtube"):
    proyecto, salidas = _datos(pid)
    lineas = subtitulos_del_video(pid)
    nombre = PLATAFORMAS.get(plataforma, "YouTube")
    dur = (salidas["render"].get("duracion") or (lineas[-1][1] if lineas else 0))
    youtube = plataforma == "youtube"
    prompt = (
        f"Eres experto en crecimiento de canales de {nombre}. Para este video de {dur:.0f} s escribe, en "
        f"{_idioma(proyecto)}, SOLO para {nombre}:\n"
        f"- 3 titulos que den ganas de verlo, sin clickbait falso "
        f"({'hasta 70 caracteres' if youtube else 'cortos, hasta 50 caracteres'});\n"
        f"- la descripcion lista para pegar "
        f"({'2-3 parrafos cortos y una llamada a la accion' if youtube else '1-2 frases y una llamada a la accion'});\n"
        "- 5-12 hashtags (sin espacios, con #);\n"
        + ("- 10-15 etiquetas (tags) sin #.\n" if youtube else "- etiquetas: lista vacia.\n") +
        f"Titulo de trabajo: {proyecto.get('titulo', '')}\n"
        f"Lo que se dice:\n\"\"\"{_texto(salidas, lineas)}\"\"\"\n"
        'Responde SOLO con JSON: {"titulos": [...], "descripcion": "...", "hashtags": [...], "etiquetas": [...]}'
    )
    d = _objeto(claude_cli.ejecutar(prompt, modelo=MODELO, esfuerzo=ESFUERZO, tiempo_max_s=180))
    limpio = {
        "plataforma": plataforma,
        "titulos": [str(x).strip() for x in d.get("titulos") or [] if str(x).strip()][:3],
        "descripcion": str(d.get("descripcion") or "").strip(),
        "hashtags": ["#" + str(x).strip().lstrip("#").replace(" ", "") for x in d.get("hashtags") or [] if str(x).strip()][:12],
        "etiquetas": [str(x).strip() for x in d.get("etiquetas") or [] if str(x).strip()][:15] if plataforma == "youtube" else [],
    }
    if not limpio["titulos"]:
        raise RuntimeError("Claude no propuso titulos")
    return _guardar(pid, "metadatos", limpio)


def capitulos(pid):
    proyecto, salidas = _datos(pid)
    lineas = subtitulos_del_video(pid)
    dur = lineas[-1][1] if lineas else 0
    if dur < CAPITULO_MIN_S * 3:
        raise ValueError(f"el video es muy corto para capitulos (YouTube pide 3 de al menos {CAPITULO_MIN_S} s)")
    numeradas = "\n".join(f"[{n}] {_t(a, ms=False)} {t}" for n, (a, _b, t) in enumerate(lineas))
    maximo = max(3, min(12, int(dur // 45) + 2))
    prompt = (
        f"Divide este video de {dur:.0f} s en capitulos de YouTube (entre 3 y {maximo}), en {_idioma(proyecto)}.\n"
        "Cada capitulo empieza en una de estas frases numeradas; el primero es la [0]. Titulos cortos (2-6 palabras), "
        "que digan de que va esa parte.\n"
        f"{numeradas[:12000]}\n"
        'Responde SOLO con una lista JSON: [{"frase": 0, "titulo": "..."}, ...]'
    )
    lista = claude_cli.extraer_json(claude_cli.ejecutar(prompt, modelo=MODELO, esfuerzo=ESFUERZO, tiempo_max_s=180))
    caps = []
    for x in lista if isinstance(lista, list) else []:
        try:
            n = int(x.get("frase"))
        except (TypeError, ValueError, AttributeError):
            continue
        if 0 <= n < len(lineas) and str(x.get("titulo") or "").strip():
            caps.append([0.0 if not caps and n == 0 else lineas[n][0], str(x["titulo"]).strip()])
    caps.sort()
    if caps:
        caps[0][0] = 0.0
    # Reglas de YouTube: separados 10 s o mas (y el ultimo con 10 s hasta el final).
    salida = []
    for t, titulo in caps:
        if not salida or (t - salida[-1][0] >= CAPITULO_MIN_S and dur - t >= CAPITULO_MIN_S):
            salida.append([round(t, 1), titulo])
    if len(salida) < 3:
        raise RuntimeError("no salieron 3 capitulos validos (prueba otra vez)")
    texto = "\n".join(f"{_t(t, ms=False)} {titulo}" for t, titulo in salida)
    return _guardar(pid, "capitulos", {"lista": salida, "texto": texto})


def traducir(pid, idioma):
    if idioma not in IDIOMAS:
        raise ValueError("idioma no soportado")
    _datos(pid)
    lineas = subtitulos_del_video(pid)
    textos = []
    for k in range(0, len(lineas), TANDA):
        tanda = [t for _a, _b, t in lineas[k:k + TANDA]]
        prompt = (
            f"Traduce al {IDIOMAS[idioma]} estos subtitulos, uno por uno, natural y breve (para leer en pantalla). "
            f"Devuelve SOLO una lista JSON con {len(tanda)} textos en el mismo orden.\n{json.dumps(tanda, ensure_ascii=False)}"
        )
        res = claude_cli.extraer_json(claude_cli.ejecutar(prompt, modelo=MODELO, esfuerzo=ESFUERZO, tiempo_max_s=240))
        if not isinstance(res, list) or len(res) != len(tanda):
            raise RuntimeError("la traduccion no trajo una frase por subtitulo (prueba otra vez)")
        textos += [" ".join(str(x).split()) for x in res]
    traducidas = [(a, b, t) for (a, b, _o), t in zip(lineas, textos)]
    destino = almacen.dir_proyecto(pid, "render", "publicar", crear=True)
    with open(os.path.join(destino, f"subtitulos_{idioma}.srt"), "w", encoding="utf-8") as f:
        f.write(srt(traducidas))
    hechas = sorted(set(guardado(pid).get("traducciones") or []) | {idioma})
    _guardar(pid, "traducciones", hechas)
    return {"idioma": idioma, "frases": len(traducidas), "traducciones": hechas}


def srt_de(pid, idioma=""):
    """El SRT del video (original, o una traduccion ya hecha)."""
    if not idioma:
        return srt(subtitulos_del_video(pid))
    if idioma not in IDIOMAS:
        raise ValueError("idioma no soportado")
    ruta = almacen.dir_proyecto(pid, "render", "publicar", f"subtitulos_{idioma}.srt")
    if not os.path.isfile(ruta):
        raise FileNotFoundError("esa traduccion aun no esta hecha")
    with open(ruta, encoding="utf-8") as f:
        return f.read()


def gancho(pid, plataforma="youtube"):
    proyecto, salidas = _datos(pid)
    lineas = subtitulos_del_video(pid)
    inicio = " ".join(t for a, _b, t in lineas if a < GANCHO_S) or (lineas[0][2] if lineas else "")
    planos = salidas["asignacion"].get("planos") or salidas["voz"].get("planos") or []
    primero = planos[0] if planos else None
    caben = retoques.palabras_que_caben(proyecto, primero["fin"] - primero["inicio"]) if primero else 12
    prompt = (
        f"Eres editor de videos virales de {PLATAFORMAS.get(plataforma, 'YouTube')}. Juzga el GANCHO (los primeros "
        f"{GANCHO_S:.0f} s) de este video, en {_idioma(proyecto)}.\n"
        f"Primeros segundos: \"{inicio}\"\n"
        f"Primer plano dice: \"{(primero or {}).get('texto', '')}\"\n"
        f"Resto del video (contexto): \"\"\"{_texto(salidas, lineas)[:2500]}\"\"\"\n"
        "Da una nota de 1 a 10 (retencion esperada), 1-3 cosas que funcionan, 1-3 que fallan, y 3 ganchos "
        f"alternativos para decir en el primer plano (como mucho {caben} palabras cada uno, que enganchen con lo que sigue).\n"
        'Responde SOLO con JSON: {"nota": 7, "bien": [...], "mal": [...], "alternativas": [...]}'
    )
    d = _objeto(claude_cli.ejecutar(prompt, modelo=MODELO, esfuerzo=ESFUERZO, tiempo_max_s=180))
    try:
        nota = max(1, min(10, int(round(float(d.get("nota"))))))
    except (TypeError, ValueError):
        nota = None
    limpio = {
        "plataforma": plataforma, "nota": nota,
        "bien": [str(x).strip() for x in d.get("bien") or [] if str(x).strip()][:3],
        "mal": [str(x).strip() for x in d.get("mal") or [] if str(x).strip()][:3],
        "alternativas": [" ".join(str(x).split()) for x in d.get("alternativas") or [] if str(x).strip()][:3],
        "plano": {"desde": primero["inicio"], "hasta": primero["fin"], "texto": primero.get("texto", "")} if primero else None,
        "palabras": caben,
    }
    return _guardar(pid, "gancho", limpio)
