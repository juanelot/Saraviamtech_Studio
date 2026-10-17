"""
Escenas POR CLIP: cuando los clips ya estan hechos (p. ej. las partes de una serie
de un prompt maestro, generadas en Flow) y la voz es una sola pista de corrido.

Los nombres de los clips mandan:
  - "4.8", "4-8", "parte4_clip8"  -> parte 4, clip 8 (cada parrafo del guion es una parte)
  - "1", "scene_12"               -> una sola parte (todo el guion se reparte entre los clips)
Cada parte se reparte entre sus clips cortando entre frases y equilibrando palabras;
el texto no cambia ni una palabra. Cada escena guarda `clip` (nombre sin extension) y
la asignacion busca ese archivo por su nombre: ni numero de escena ni Claude.

Solo CALCULA: la interfaz guarda el resultado en params.escenas.fijas.
"""
import os
import re

from app.services.estudio import almacen, medios
from app.services.estudio import recursos as recursos_mod

PARTE_CLIP = re.compile(r"(\d+)\D+?(\d+)$")


def _clave(stem):
    """(parte, clip) desde el nombre; None si no lleva numero."""
    m = PARTE_CLIP.search(stem)
    if m:
        return int(m.group(1)), int(m.group(2))
    n = recursos_mod.numero_escena(stem)
    return (1, n) if n is not None else None


def _clips(pid):
    """[(parte, clip, stem)] de lo subido, sin repetir stem, en orden."""
    vistos, salida = set(), []
    for _origen, nombre, ruta in recursos_mod._recorrer(almacen.dir_proyecto(pid, "recursos"), "subido"):
        stem = os.path.splitext(os.path.basename(nombre))[0]
        clave = _clave(stem)
        if clave and stem not in vistos and medios.tipo_de(ruta):
            vistos.add(stem)
            salida.append((*clave, stem))
    return sorted(salida)


def _frases(texto):
    return [f for f in re.split(r"(?<=[.?!…])\s+", texto.strip()) if f]


def repartir(texto, n):
    """Texto -> n trozos contiguos lo mas parejos posible en palabras, cortando entre
    frases (si hay menos frases que clips, entre palabras)."""
    piezas = _frases(texto)
    if len(piezas) < n:
        piezas = texto.split()
    if len(piezas) < n:
        raise ValueError(f"no hay texto suficiente para {n} clips")
    w = [len(x.split()) for x in piezas]
    acum = [0]
    for x in w:
        acum.append(acum[-1] + x)
    obj = acum[-1] / n
    m, inf = len(piezas), float("inf")
    coste = [[inf] * (n + 1) for _ in range(m + 1)]
    corte = [[0] * (n + 1) for _ in range(m + 1)]
    coste[0][0] = 0.0
    for i in range(1, m + 1):
        for k in range(1, min(n, i) + 1):
            for j in range(k - 1, i):
                c = coste[j][k - 1] + (acum[i] - acum[j] - obj) ** 2
                if c < coste[i][k]:
                    coste[i][k], corte[i][k] = c, j
    trozos, i = [], m
    for k in range(n, 0, -1):
        j = corte[i][k]
        trozos.append(" ".join(piezas[j:i]))
        i = j
    return trozos[::-1]


def calcular(pid, texto):
    texto = (texto or "").strip()
    if not texto:
        raise ValueError("no hay guion: escribelo en el paso Guion o pegalo aqui")
    clips = _clips(pid)
    if not clips:
        raise ValueError("no hay clips con numero en el nombre (sube 1.1, 1.2... o 1, 2, 3... en Contenido)")
    partes = sorted({c[0] for c in clips})
    parrafos = [x.strip() for x in re.split(r"\n\s*\n", texto) if x.strip()]
    avisos = []
    if len(partes) == 1:
        bloques = {partes[0]: " ".join(parrafos)}
    elif len(partes) == len(parrafos):
        bloques = dict(zip(partes, parrafos))
    else:
        raise ValueError(f"los clips tienen {len(partes)} partes ({', '.join(map(str, partes))}) pero el guion "
                         f"tiene {len(parrafos)} parrafos: deja una linea en blanco entre parte y parte")
    for parte in partes:
        nums = [c[1] for c in clips if c[0] == parte]
        huecos = sorted(set(range(1, max(nums) + 1)) - set(nums))
        if huecos:
            avisos.append(f"parte {parte}: faltan los clips {', '.join(map(str, huecos))}")
    fijas = []
    for parte in partes:
        suyos = [c for c in clips if c[0] == parte]
        for (_p, _c, stem), trozo in zip(suyos, repartir(bloques[parte], len(suyos))):
            fijas.append({"n": len(fijas) + 1, "narracion": trozo, "clip": stem, "imagen": None, "video": ""})
    return {"fijas": fijas, "partes": len(partes), "clips": len(fijas), "avisos": avisos}
