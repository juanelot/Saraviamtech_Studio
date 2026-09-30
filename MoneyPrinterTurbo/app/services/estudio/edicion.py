"""
Edicion EDITORIAL: efectos sobrios que suben la retencion sin parecer TikTok.

Etapa 1 (esta):
  - Subtitulos PALABRA A PALABRA: 3-5 palabras en pantalla; la que suena se
    ilumina (las demas un poco apagadas) y UNA palabra clave por frase va en el
    color de resalte.
  - ROTULOS: cifras, fechas y nombres en pantalla con una barra de color, entran
    y salen con fundido (estilo documental).
  - SONIDO: whoosh suave en los cambios de plano, golpe grave en las
    revelaciones y la musica baja sola bajo la voz (ducking, en acabado.py).

Claude decide DONDE (palabras clave, rotulos, revelaciones, gancho) en una
pasada sobre las lineas de subtitulo; el resultado se cachea en render/marcas.json
por contenido, asi que cambiar colores o volumenes no vuelve a llamarlo.

Tiempos de palabra: voz/palabras.json (voces de Microsoft, exactos). Si no
existe (voz clonada o voces antiguas) se reparten dentro de cada linea por
numero de caracteres.

Las opciones NO estan en render.DEFECTOS (moverian la firma de todos los
proyectos): se leen con .get y valores por defecto de OPCIONES.
"""
import hashlib
import json
import os
import re
import subprocess
import unicodedata
import wave

import numpy as np
from loguru import logger

from app.services import claude_cli
from app.services.estudio import acabado, almacen, medios
from app.utils import utils

VERSION = "1"
VERSION_SFX = "2"   # cambiarla regenera los efectos generados
OPCIONES = {
    "edicion": "clasico",        # clasico | editorial
    "ed_palabras": True,
    "ed_rotulos": True,
    "ed_sonido": True,
    "palabras_max": 4,
    "color_resalte": "#FFD447",
    "sfx_volumen": 1.0,
    "ed_modelo": "sonnet",
    "ed_esfuerzo": "low",
    # etapa 2
    "ed_ritmo": True,             # primeros segundos con subcortes cada ~3 s
    "ed_zoom": True,              # acercamiento en las revelaciones
    "ed_color": True,
    "ed_look": "natural",         # natural | calido | cine | frio
    "ed_gancho": True,
    "gancho_texto": "",           # vacio = el que propone Claude
}
RITMO_HASTA_S = 30.0   # tramo inicial con cortes mas rapidos
RITMO_PIEZA_S = 3.0
PIEZA_MIN_S = 1.2
ENCUADRE_ALT = 1.12    # encuadre mas cerrado de los subcortes de ritmo
ENCUADRE_REVELACION = 1.16

# Ajuste de color comun + vineta leve + grano fino (temporal) para que imagenes de
# distintas fuentes parezcan de la misma pelicula.
LOOKS = {
    "natural": "eq=contrast=1.06:saturation=1.08:gamma=0.98",
    "calido": "colorbalance=rm=0.04:gm=0.01:bm=-0.05:rh=0.03:bh=-0.03,eq=contrast=1.06:saturation=1.05",
    "cine": "colorbalance=rs=-0.05:bs=0.05:rh=0.05:bh=-0.05,eq=contrast=1.08:saturation=1.03",
    "frio": "colorbalance=rm=-0.03:bm=0.05,eq=contrast=1.05:saturation=0.95",
}
TANDA = 220           # lineas de subtitulo por llamada a Claude
SR = 44100            # pista de efectos
ESPACIO_ROTULOS = 9.0  # segundos minimos entre rotulos
ESPACIO_WHOOSH = 2.2


def opciones(p):
    return {k: p.get(k, v) for k, v in OPCIONES.items()}


def activa(p):
    return p.get("edicion", "clasico") == "editorial"


# ------------------------------------------------------------------ texto

def _norm(t):
    t = unicodedata.normalize("NFD", t.lower())
    t = "".join(c for c in t if unicodedata.category(c) != "Mn")
    return re.sub(r"[^\w%$€]+", "", t)


def _t(seg):
    m, s = divmod(int(seg), 60)
    return f"{m}:{s:02d}"


# ------------------------------------------------------------------ tiempos de palabra

def palabras_por_linea(lineas, ruta_palabras):
    """Por cada linea de subtitulo: [(inicio, fin, palabra_mostrada)].

    Se muestran las palabras del SRT (con puntuacion y mayusculas del guion). Los
    tiempos salen de las palabras habladas dentro de la linea si coinciden en
    numero; si no (p. ej. "1870" dicho como "mil ochocientos setenta"), se
    reparten por caracteres dentro del tramo hablado."""
    habladas = []
    if ruta_palabras and os.path.isfile(ruta_palabras):
        try:
            with open(ruta_palabras, encoding="utf-8") as f:
                habladas = [tuple(x) for x in json.load(f)]
        except (OSError, ValueError):
            habladas = []
    salida, k = [], 0
    for a, b, texto in lineas:
        mostradas = texto.split()
        if not mostradas:
            salida.append([])
            continue
        propias = []
        while k < len(habladas) and habladas[k][0] < a - 0.05:
            k += 1
        j = k
        while j < len(habladas) and habladas[j][0] < b - 0.02:
            propias.append(habladas[j])
            j += 1
        k = j
        if propias and len(propias) == len(mostradas):
            salida.append([(pa, pb, m) for (pa, pb, _h), m in zip(propias, mostradas)])
            continue
        ini = propias[0][0] if propias else a
        fin = propias[-1][1] if propias else b
        pesos = [len(m) + 1 for m in mostradas]
        total, cursor, filas = sum(pesos), ini, []
        for m, pz in zip(mostradas, pesos):
            d = (fin - ini) * pz / total
            filas.append((cursor, cursor + d, m))
            cursor += d
        salida.append(filas)
    return salida


def _trozos(filas, maximo):
    """Parte una linea en grupos de hasta `maximo` palabras, cortando tras
    puntuacion y sin dejar un grupo final de una sola palabra."""
    grupos, actual = [], []
    for i, f in enumerate(filas):
        actual.append(i)
        if len(actual) >= maximo or re.search(r"[,.;:!?…]$", f[2]):
            grupos.append(actual)
            actual = []
    if actual:
        if len(actual) == 1 and grupos and len(grupos[-1]) <= maximo:
            grupos[-1].extend(actual)
        else:
            grupos.append(actual)
    return grupos


# ------------------------------------------------------------------ marcas (Claude)

PROMPT = """Eres editor de video documental. Vas a marcar, con criterio SOBRIO, donde
reforzar visualmente esta narracion. Idioma de la narracion: el de las lineas.

LINEAS (indice [minuto:segundo] texto):
{lineas}

Devuelve SOLO JSON:
{{"resaltar": [{{"i": 3, "texto": "monopolio"}}],
  "rotulos": [{{"i": 5, "titulo": "1870", "detalle": "Nace la Standard Oil"}}],
  "revelaciones": [12, 40],
  "gancho": "Nadie te conto esto"}}

REGLAS
- resaltar: como mucho UNA palabra (o nombre de 2-3 palabras) por linea, y solo en
  la mitad de las lineas aprox. La que carga el sentido: cifra, nombre propio,
  concepto fuerte. Copiala EXACTA como aparece en la linea.
- rotulos: solo datos concretos que conviene ver escritos: fechas, cifras, nombres de
  personas, empresas o lugares (la primera vez que salen). "titulo" de 1-4 palabras
  con el dato; "detalle" de 0-6 palabras de contexto. Como mucho uno cada 20 segundos.
- revelaciones: indices de las lineas con un giro, dato sorprendente o momento clave.
  Uno cada 30-45 segundos como mucho.
- gancho: {regla_gancho}
- No inventes datos que no esten en las lineas."""


def _pedir_marcas(lineas, desde, opts, primera):
    texto = "\n".join(f"{desde + i} [{_t(a)}] {t}" for i, (a, _b, t) in enumerate(lineas))
    prompt = PROMPT.format(
        lineas=texto,
        regla_gancho=("frase de 2-5 palabras para los primeros 2 segundos, en el idioma de la "
                      "narracion, que despierte curiosidad sin mentir." if primera else 'deja "".'))
    salida = claude_cli.ejecutar(prompt, modelo=opts["ed_modelo"], esfuerzo=opts["ed_esfuerzo"],
                                 tiempo_max_s=min(1800, 180 + 2 * len(lineas)))
    i, j = salida.find("{"), salida.rfind("}")
    datos = json.loads(salida[i:j + 1]) if i != -1 and j > i else {}
    return datos if isinstance(datos, dict) else {}


def marcas(carpeta_render, lineas, opts, avisar):
    """Marcas cacheadas por contenido de las lineas + version + modelo."""
    clave = hashlib.sha256(json.dumps([VERSION, opts["ed_modelo"], opts["ed_esfuerzo"],
                                       [t for _a, _b, t in lineas]], ensure_ascii=False)
                           .encode("utf-8")).hexdigest()[:20]
    ruta = os.path.join(carpeta_render, "marcas.json")
    previo = almacen.leer_json(ruta, {}) or {}
    if previo.get("clave") == clave:
        return previo["datos"]
    datos = {"resaltar": [], "rotulos": [], "revelaciones": [], "gancho": ""}
    tandas = [lineas[k:k + TANDA] for k in range(0, len(lineas), TANDA)]
    bien = 0
    for n, tanda in enumerate(tandas):
        avisar(f"edicion: Claude marca claves y rotulos ({n + 1}/{len(tandas)})")
        try:
            d = _pedir_marcas(tanda, n * TANDA, opts, n == 0)
        except Exception as e:  # noqa: BLE001 -- sin marcas el video sale igual
            logger.warning(f"edicion: tanda {n + 1} sin marcas ({e})")
            continue
        bien += 1
        for campo in ("resaltar", "rotulos", "revelaciones"):
            if isinstance(d.get(campo), list):
                datos[campo] += d[campo]
        if n == 0 and isinstance(d.get("gancho"), str):
            datos["gancho"] = d["gancho"].strip()[:60]
    if bien:  # si Claude fallo en todo, no se cachea: se reintenta en el proximo render
        almacen.escribir_json(ruta, {"clave": clave, "datos": datos})
    return datos


# ------------------------------------------------------------------ ASS

def _color(hexa, alfa=0):
    return acabado._color_ass(hexa, alfa)


def _resaltados(marcas_, por_linea):
    """{linea: set(indices de palabra)} con las palabras clave encontradas."""
    salida = {}
    for m in marcas_.get("resaltar") or []:
        try:
            i = int(m.get("i"))
        except (TypeError, ValueError, AttributeError):
            continue
        if not 0 <= i < len(por_linea):
            continue
        buscada = [_norm(x) for x in str(m.get("texto", "")).split() if _norm(x)]
        palabras = [_norm(f[2]) for f in por_linea[i]]
        for k in range(len(palabras) - len(buscada) + 1):
            if buscada and palabras[k:k + len(buscada)] == buscada:
                salida.setdefault(i, set()).update(range(k, k + len(buscada)))
                break
    return salida


def _eventos_palabras(por_linea, claves, opts, prefijo):
    resalte = _color(opts["color_resalte"])
    maximo = max(2, min(7, int(opts["palabras_max"] or 4)))
    eventos, cajas = [], []
    for i, filas in enumerate(por_linea):
        grupos = _trozos(filas, maximo)
        for g, idx in enumerate(grupos):
            fin_grupo = filas[idx[-1]][1]
            siguiente = filas[grupos[g + 1][0]][0] if g + 1 < len(grupos) else None
            if siguiente is None and i + 1 < len(por_linea) and por_linea[i + 1]:
                siguiente = por_linea[i + 1][0][0]
            fin_grupo = min(fin_grupo + 0.3, siguiente) if siguiente else fin_grupo + 0.3
            cajas.append((filas[idx[0]][0], fin_grupo,
                          f"{prefijo}{' '.join(acabado.limpio(filas[kk][2]) for kk in idx)}"))
            for pos, k in enumerate(idx):
                ini = filas[k][0]
                fin = filas[idx[pos + 1]][0] if pos + 1 < len(idx) else fin_grupo
                if fin - ini < 0.02:
                    continue
                trozos = []
                for kk in idx:
                    t = acabado.limpio(filas[kk][2])
                    color = f"\\1c{resalte}" if kk in claves.get(i, ()) else ""
                    alfa = "\\1a&H00&" if kk == k else "\\1a&H45&"
                    trozos.append(f"{{{alfa}{color}}}{t}{{\\r}}")
                eventos.append((ini, fin, f"{prefijo}{' '.join(trozos)}"))
    return eventos, cajas


def _estilo_derivado(estilo, nombre, **cambios):
    """Copia la linea `Style: Default,...` con otro nombre y campos cambiados."""
    campos = ["Name", "Fontname", "Fontsize", "PrimaryColour", "SecondaryColour", "OutlineColour",
              "BackColour", "Bold", "Italic", "Underline", "StrikeOut", "ScaleX", "ScaleY", "Spacing",
              "Angle", "BorderStyle", "Outline", "Shadow", "Alignment", "MarginL", "MarginR", "MarginV",
              "Encoding"]
    valores = estilo.split(":", 1)[1].strip().split(",")
    valores[0] = nombre
    for k, v in cambios.items():
        valores[campos.index(k)] = str(v)
    return "Style: " + ",".join(valores)


def _eventos_rotulos(lineas, marcas_, opts, p, w, h):
    tam = int(p["tam_fuente"])
    t1, t2 = int(tam * 0.9), int(tam * 0.55)
    arriba = p["sub_posicion"] in ("bottom",) or (p["sub_posicion"] == "custom" and float(p["sub_posicion_pct"]) > 50)
    x = int(w * 0.07)
    y = int(h * 0.09) if arriba else int(h * 0.70)
    alto = int(t1 * 1.15 + t2 * 1.3)
    barra = _color(opts["color_resalte"])
    salida, ultimo = [], -1e9
    rotulos = []
    for r in marcas_.get("rotulos") or []:
        try:
            i = int(r.get("i"))
        except (TypeError, ValueError, AttributeError):
            continue
        if 0 <= i < len(lineas) and str(r.get("titulo", "")).strip():
            rotulos.append((lineas[i][0], str(r["titulo"]).strip()[:40], str(r.get("detalle") or "").strip()[:60]))
    for ini, titulo, detalle in sorted(rotulos):
        if ini - ultimo < ESPACIO_ROTULOS:
            continue
        fin = ini + 3.6
        ultimo = fin
        fad = "\\fad(220,300)"
        salida.append((1, ini, fin, "Rotulo",
                       f"{{\\an7\\pos({x},{y}){fad}\\p1\\bord0\\shad0\\1c{barra}}}m 0 0 l 7 0 7 {alto} 0 {alto}{{\\p0}}"))
        mov = f"\\move({x + 4},{y},{x + 22},{y},0,260)"
        salida.append((2, ini, fin, "Rotulo", f"{{\\an7{mov}{fad}}}{acabado.limpio(titulo)}"))
        if detalle:
            mov2 = f"\\move({x + 4},{y + int(t1 * 1.15)},{x + 22},{y + int(t1 * 1.15)},0,260)"
            salida.append((2, ini + 0.12, fin, "RotuloDetalle", f"{{\\an7{mov2}{fad}}}{acabado.limpio(detalle)}"))
    estilos = [
        f"Style: Rotulo,{acabado.familia_fuente(p['fuente'])},{t1},&H00FFFFFF,&H000000FF,&H00101010,"
        f"&H96000000,-1,0,0,0,100,100,0,0,1,2,3,7,0,0,0,1",
        f"Style: RotuloDetalle,{acabado.familia_fuente(p['fuente'])},{t2},&H00E8E8E8,&H000000FF,&H00101010,"
        f"&H96000000,0,0,0,0,100,100,0,0,1,1.5,2,7,0,0,0,1",
    ]
    return salida, estilos


def texto_gancho(marcas_, opts):
    if not opts["ed_gancho"]:
        return ""
    return (str(opts.get("gancho_texto") or "").strip() or str(marcas_.get("gancho") or "").strip())[:60]


def escribir_ass(destino, lineas, por_linea, marcas_, opts, p, w, h):
    estilo, prefijo = acabado.estilo_base(p, w, h)
    estilos, eventos = [estilo], []
    if p.get("subtitulos", True):
        if opts["ed_palabras"]:
            claves = _resaltados(marcas_, por_linea)
            palabras, cajas = _eventos_palabras(por_linea, claves, opts, prefijo)
            if p.get("sub_fondo"):
                # Una caja por grupo (capa 0, texto invisible) y las palabras encima sin
                # caja: si no, cada palabra con otro estilo dibuja su propia caja.
                estilos += [_estilo_derivado(estilo, "Caja", PrimaryColour="&HFF000000"),
                            _estilo_derivado(estilo, "Palabra", BorderStyle=1, Outline=0, Shadow=0)]
                eventos += [(0, a, b, "Caja", t) for a, b, t in cajas]
                eventos += [(1, a, b, "Palabra", t) for a, b, t in palabras]
            else:
                eventos += [(0, a, b, "Default", t) for a, b, t in palabras]
        else:
            eventos += [(0, a, b, "Default", f"{prefijo}{acabado.limpio(t)}") for a, b, t in lineas]
    if opts["ed_rotulos"]:
        ev, st = _eventos_rotulos(lineas, marcas_, opts, p, w, h)
        eventos += ev
        estilos += st
    gancho = texto_gancho(marcas_, opts)
    if gancho:
        tam = int(p["tam_fuente"])
        vertical = h > w
        estilos.append(
            f"Style: Gancho,{acabado.familia_fuente(p['fuente'])},{int(tam * (1.25 if vertical else 1.45))},"
            f"&H00FFFFFF,&H000000FF,&H00101010,&H96000000,-1,0,0,0,100,100,1,0,1,3,3,8,"
            f"{int(w * 0.08)},{int(w * 0.08)},{int(h * (0.2 if vertical else 0.14))},1")
        eventos.append((3, 0.15, 2.6, "Gancho",
                        "{\\fad(250,400)\\fscx94\\fscy94\\t(0,450,\\fscx100\\fscy100)}"
                        + acabado.limpio(gancho.upper())))
    filas = [f"Dialogue: {capa},{acabado._t_ass(a)},{acabado._t_ass(b)},{est},,0,0,0,,{txt}"
             for capa, a, b, est, txt in sorted(eventos, key=lambda e: (e[1], e[0]))]
    with open(destino, "w", encoding="utf-8") as f:
        f.write(acabado.cabecera(w, h, estilos) + "\n".join(filas) + "\n")
    return len(filas)


# ------------------------------------------------------------------ sonido

SONIDOS = {
    # Generados con ffmpeg si no hay uno propio en resource/sfx/<nombre>.(wav|mp3)
    "whoosh": ["-f", "lavfi", "-i", "anoisesrc=d=0.7:c=pink:a=0.6:r=44100",
               "-af", "highpass=f=350,lowpass=f=5000,afade=t=in:d=0.38:curve=exp,"
                      "afade=t=out:st=0.38:d=0.32:curve=exp,volume=0.7"],
    "golpe": ["-f", "lavfi", "-i", "sine=f=52:d=1.8:r=44100",
              "-f", "lavfi", "-i", "anoisesrc=d=0.09:c=brown:a=0.7:r=44100",
              "-filter_complex", "[0:a]afade=t=out:st=0.05:d=1.75:curve=exp,volume=0.9[s];"
                                 "[1:a]lowpass=f=900,afade=t=out:d=0.09[n];"
                                 "[s][n]amix=inputs=2:normalize=0,volume=0.75"],
}


def _sonido(nombre):
    """Muestras mono float32 a 44.1 kHz del efecto (cacheadas en el catalogo)."""
    cache = os.path.join(almacen.dir_catalogo("sfx"), f"{nombre}-{VERSION_SFX}.wav")
    if not os.path.isfile(cache):
        carpeta = os.path.join(utils.root_dir(), "resource", "sfx")
        propio = next((os.path.join(carpeta, nombre + e) for e in (".wav", ".mp3")
                       if os.path.isfile(os.path.join(carpeta, nombre + e))), None)
        ff = medios.ffmpeg()
        if propio:
            args = [ff, "-hide_banner", "-loglevel", "error", "-y", "-i", propio]
        else:
            args = [ff, "-hide_banner", "-loglevel", "error", "-y"] + SONIDOS[nombre]
        r = medios.correr(args + ["-ac", "1", "-ar", str(SR), "-c:a", "pcm_s16le", cache], timeout=60)
        if r.returncode != 0:
            raise RuntimeError(f"no se pudo crear el efecto {nombre}: {r.stderr[-200:]}")
    with wave.open(cache, "rb") as w:
        datos = np.frombuffer(w.readframes(w.getnframes()), dtype=np.int16)
    return datos.astype(np.float32) / 32768.0


def pista_sfx(destino, duracion, eventos):
    """Escribe un WAV mono con los efectos colocados; se genera por grupos que se
    solapan para no tener toda la pista en memoria (videos de horas)."""
    muestras = {n: _sonido(n) for n in {e[1] for e in eventos}}
    eventos = sorted((max(0.0, t), n) for t, n in eventos if t < duracion)
    total = int(duracion * SR)
    with wave.open(destino, "wb") as out:
        out.setnchannels(1)
        out.setsampwidth(2)
        out.setframerate(SR)
        pos, k = 0, 0
        while k < len(eventos):
            ini = int(eventos[k][0] * SR)
            grupo, fin = [], ini
            while k < len(eventos) and int(eventos[k][0] * SR) <= fin:
                a = int(eventos[k][0] * SR)
                grupo.append((a, muestras[eventos[k][1]]))
                fin = max(fin, a + len(grupo[-1][1]))
                k += 1
            fin = min(fin, total)
            if ini > pos:
                out.writeframes(np.zeros(ini - pos, dtype=np.int16).tobytes())
            buf = np.zeros(max(0, fin - ini), dtype=np.float32)
            for a, s in grupo:
                trozo = s[:max(0, fin - a)]
                buf[a - ini:a - ini + len(trozo)] += trozo
            out.writeframes((np.clip(buf, -1, 1) * 32767).astype(np.int16).tobytes())
            pos = fin
        if total > pos:
            out.writeframes(np.zeros(total - pos, dtype=np.int16).tobytes())


# ------------------------------------------------------------------ todo junto

def filtro_color(opts):
    if not opts["ed_color"]:
        return None
    base = LOOKS.get(opts["ed_look"], LOOKS["natural"])
    return f"{base},vignette=angle=PI/5,noise=alls=3:allf=t"  # grano fino: mas fuerte duplica el peso del MP4


def lineas_y_marcas(ctx, voz, p):
    """(lineas del SRT, marcas de Claude). Las marcas se cachean: llamarlo dos
    veces en el mismo render no repite la llamada."""
    opts = opciones(p)
    srt = ctx.dir(voz["srt"], crear=False)
    lineas = acabado.lineas_srt(srt) if os.path.isfile(srt) else []
    vacio = {"resaltar": [], "rotulos": [], "revelaciones": [], "gancho": ""}
    if not lineas:
        return lineas, vacio
    return lineas, marcas(ctx.dir("render"), lineas, opts, lambda m: ctx.avisar(m, 3))


def subcortes(planos, lineas, marcas_, opts):
    """Parte los planos en PIEZAS (mismo recurso, otro encuadre) para dar ritmo:
      - ritmo: en los primeros RITMO_HASTA_S, planos largos en piezas de ~3 s
        alternando encuadre normal y cerrado;
      - zoom: en cada revelacion, lo que sigue entra mas cerca (punch-in).
    Cada pieza: dict del plano + inicio/fin propios, "encuadre" y "desde" (segundos
    desde el inicio del plano, para el offset de los videos)."""
    revel = sorted(lineas[i][0] for i in (marcas_.get("revelaciones") or [])
                   if isinstance(i, int) and 0 <= i < len(lineas)) if opts["ed_zoom"] else []
    piezas = []
    for x in planos:
        a, b = float(x["inicio"]), float(x["fin"])
        cortes = [(a, 1.0)]
        if opts["ed_ritmo"] and a < RITMO_HASTA_S and b - a > RITMO_PIEZA_S + 0.4:
            n = int(-(-(b - a) // RITMO_PIEZA_S))
            paso = (b - a) / n
            # Solo se corta dentro del tramo inicial; la ultima pieza sigue hasta el final del plano.
            cortes = [(a + k * paso, 1.0 if k % 2 == 0 else ENCUADRE_ALT) for k in range(n)
                      if k == 0 or a + k * paso < RITMO_HASTA_S]
        for t in revel:
            if a + PIEZA_MIN_S <= t <= b - PIEZA_MIN_S:
                previo = max(c for c in cortes if c[0] <= t)
                cortes = [c for c in cortes if abs(c[0] - t) >= PIEZA_MIN_S or c[0] == a]
                cortes.append((t, max(ENCUADRE_REVELACION, previo[1] + 0.06)))
        cortes.sort()
        for k, (ini, enc) in enumerate(cortes):
            fin = cortes[k + 1][0] if k + 1 < len(cortes) else b
            if fin - ini < 0.05:
                continue
            piezas.append({**x, "inicio": ini, "fin": fin, "encuadre": round(enc, 3),
                           "desde": round(ini - a, 3), "pieza": k})
    return piezas


def preparar(ctx, voz, planos, p, w, h, duracion):
    """Deja listos render/subtitulos.ass y render/sfx.wav. Devuelve
    {"ass": ruta|None, "sfx": ruta|None, "ducking": bool, "resumen": str}."""
    opts = opciones(p)
    carpeta = ctx.dir("render")
    lineas, marcas_ = lineas_y_marcas(ctx, voz, p)
    por_linea = palabras_por_linea(lineas, ctx.dir("voz", "palabras.json", crear=False))

    ass = None
    if (p.get("subtitulos", True) and lineas) or opts["ed_rotulos"] or texto_gancho(marcas_, opts):
        ass = os.path.join(carpeta, "subtitulos.ass")
        escribir_ass(ass, lineas, por_linea, marcas_, opts, p, w, h)

    sfx = None
    if opts["ed_sonido"]:
        eventos, ultimo = [], -1e9
        for a, b in zip(planos, planos[1:]):
            corte = float(b["inicio"])
            if b.get("recurso") != a.get("recurso") and corte - ultimo >= ESPACIO_WHOOSH:
                eventos.append((corte - 0.4, "whoosh"))
                ultimo = corte
        for i in marcas_.get("revelaciones") or []:
            if isinstance(i, int) and 0 <= i < len(lineas):
                eventos.append((lineas[i][0] - 0.05, "golpe"))
        if eventos:
            sfx = os.path.join(carpeta, "sfx.wav")
            pista_sfx(sfx, duracion, eventos)

    n_claves = sum(len(v) for v in _resaltados(marcas_, por_linea).values()) if lineas else 0
    gancho = texto_gancho(marcas_, opts)
    resumen = (f"edicion editorial: {n_claves} palabras clave, {len(marcas_.get('rotulos') or [])} rotulos, "
               f"{len(marcas_.get('revelaciones') or [])} revelaciones"
               + (f", gancho «{gancho}»" if gancho else ""))
    return {"ass": ass, "sfx": sfx, "ducking": bool(opts["ed_sonido"]), "resumen": resumen,
            "gancho": marcas_.get("gancho", ""), "color": filtro_color(opts)}
