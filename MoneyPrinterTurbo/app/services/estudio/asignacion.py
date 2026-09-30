"""
Etapa ASIGNACION: que recurso va en cada plano.

  modo "claude": Claude lee cada plano (lo que se DICE en ese momento y cuanto
                 dura) y el catalogo (descripcion de cada imagen/video) y elige.
  modo "orden":  como el modo local de siempre: en orden alfabetico, ciclando.
  modo "escenas": contenido creado A MANO (Flow, extension...) para las escenas
                 de la etapa escenas: cada escena N lleva el archivo numerado N
                 (videos/ antes que images/, o al reves con preferir="imagen").
                 Los planos pasan a ser las escenas. Sin numeros: en orden.

Encima se aplican los `fijados` de la persona ({indice_plano: id_recurso}).
La eleccion de Claude se cachea (asignacion/base.json) con la huella de SUS
entradas, asi que fijar a mano un plano no vuelve a llamar a Claude.

Videos: si un mismo video sale en varios planos, cada uso arranca donde se
quedo el anterior (no se repite siempre el mismo trozo).
"""
import hashlib
import json
import os
from collections import Counter

from loguru import logger

from app.services import claude_cli
from app.services.estudio import almacen

# OJO: no anadir claves nuevas aqui sin necesidad: entran en la firma y dejan
# obsoletos los proyectos guardados. `preferir` (modo escenas) se lee con .get().
DEFECTOS = {
    "modo": "claude",
    "criterio": "",
    "fijados": {},
    "modelo": "sonnet",
    "esfuerzo": "low",
}

TAMANO_TANDA = 50


def _clave(planos, recursos, p):
    datos = {
        "planos": [(x["texto"], round(x["fin"] - x["inicio"], 2)) for x in planos],
        "recursos": [(r["id"], r["tipo"], r.get("duracion"), r.get("descripcion"), r["nombre"]) for r in recursos],
        "criterio": p.get("criterio", ""), "modelo": p["modelo"], "esfuerzo": p["esfuerzo"],
    }
    return hashlib.sha256(json.dumps(datos, ensure_ascii=False).encode()).hexdigest()[:20]


def _prompt(tanda, recursos, alias, uso, previos, criterio, total_planos):
    cat = []
    for r in recursos:
        extra = f"VIDEO {r['duracion']:.1f}s" if r["tipo"] == "video" else "IMAGEN"
        desc = r.get("descripcion") or f"(sin descripcion; archivo: {r['nombre']})"
        cat.append(f"{alias[r['id']]} [{extra}] usos={uso[r['id']]}: {desc}")
    planos = "\n".join(f"{x['i']} ({x['fin'] - x['inicio']:.1f}s): {x['texto']}" for x in tanda)
    tope = max(2, -(-total_planos // max(1, len(recursos))) + 1)
    ant = ", ".join(f"plano {i}->{a}" for i, a in previos) or "(ninguno)"
    criterio = (criterio or "").strip() or "(ninguno)"
    return f"""Eres editor de video. Elige que recurso visual va en cada PLANO de la narracion.

CATALOGO DE RECURSOS (alias [tipo] usos_hasta_ahora: descripcion):
{chr(10).join(cat)}

PLANOS (indice (duracion): lo que se dice en ese momento):
{planos}

Planos anteriores ya asignados: {ant}

Reglas, por orden de prioridad:
1. Criterio de la persona: {criterio}
2. Elige el recurso que mejor ilustra LO QUE SE DICE en ese plano: coincidencia literal > tematica > emocion/tono.
3. Nunca el mismo recurso en dos planos seguidos (incluidos los anteriores ya asignados).
4. Reparte: prefiere recursos poco usados; ninguno deberia pasar de {tope} usos salvo que sea claramente el mejor.
5. Los VIDEOS encajan mejor en planos de accion o movimiento; si el video dura menos que el plano, se repite en bucle.

Responde SOLO con JSON, un elemento por plano de la lista:
[{{"i": <indice>, "r": "<alias>", "m": "<motivo en 3-8 palabras>"}}]"""


def _con_claude(planos, recursos, p, ctx):
    alias = {r["id"]: f"R{k + 1}" for k, r in enumerate(recursos)}
    por_alias = {v: k for k, v in alias.items()}
    uso = Counter({r["id"]: 0 for r in recursos})
    eleccion = {}
    tandas = [planos[i:i + TAMANO_TANDA] for i in range(0, len(planos), TAMANO_TANDA)]
    for n, tanda in enumerate(tandas):
        ctx.avisar(f"Claude asignando planos {tanda[0]['i']}-{tanda[-1]['i']} ({n + 1}/{len(tandas)})",
                   5 + 85 * n / len(tandas))
        previos = [(i, alias[eleccion[i][0]]) for i in sorted(eleccion)[-3:]]
        texto = claude_cli.ejecutar(
            _prompt(tanda, recursos, alias, uso, previos, p.get("criterio"), len(planos)),
            modelo=p["modelo"], esfuerzo=p["esfuerzo"])
        try:
            datos = claude_cli.extraer_json(texto)
        except ValueError as e:
            logger.warning(f"tanda {n + 1}: respuesta sin JSON, se rellena sola ({e})")
            datos = []
        validos = {x["i"] for x in tanda}
        for d in datos if isinstance(datos, list) else []:
            try:
                i = int(d.get("i"))
            except (TypeError, ValueError):
                continue
            rid = por_alias.get(str(d.get("r", "")).strip().upper())
            if i in validos and rid:
                eleccion[i] = (rid, str(d.get("m", ""))[:120])
                uso[rid] += 1
    return eleccion


def _rellenar(planos, recursos, eleccion, ordenado=False):
    """Completa los planos sin recurso: el menos usado distinto del anterior."""
    ids = [r["id"] for r in recursos]
    uso = Counter({i: 0 for i in ids})
    for rid, _ in eleccion.values():
        uso[rid] += 1
    previo = None
    for k, x in enumerate(planos):
        i = x["i"]
        if i not in eleccion:
            if ordenado:
                rid = ids[k % len(ids)]
            else:
                candidatos = [r for r in ids if r != previo] or ids
                rid = min(candidatos, key=lambda r: (uso[r], ids.index(r)))
            eleccion[i] = (rid, "en orden" if ordenado else "relleno automatico")
            uso[rid] += 1
        previo = eleccion[i][0]
    return eleccion


def _por_escenas(escenas, recursos, preferir):
    """{scene_number: (recurso, motivo)} + lista de escenas sin archivo."""
    def buscar(n, tipo, carpeta=None):
        for r in recursos:
            if r.get("escena") == n and r["tipo"] == tipo and (carpeta is None or r.get("carpeta") == carpeta):
                return r
        return None

    orden_tipos = ["video", "imagen"] if preferir == "video" else ["imagen", "video"]
    con_numero = any(r.get("escena") is not None for r in recursos)
    eleccion, faltan, previo = {}, [], None
    for k, e in enumerate(escenas):
        n = e["scene_number"]
        r = None
        if con_numero:
            for tipo in orden_tipos:
                r = buscar(n, tipo, "videos" if tipo == "video" else "images") or buscar(n, tipo)
                if r:
                    break
            motivo = f"escena {n}"
        else:
            r, motivo = recursos[k % len(recursos)], "en orden (sin numeros en los nombres)"
        if r is None:
            faltan.append(n)
            r, motivo = previo, f"escena {n} SIN ARCHIVO: se repite el anterior"
            if r is None:
                r, motivo = recursos[0], f"escena {n} SIN ARCHIVO: se usa el primero"
        eleccion[n] = (r["id"], motivo)
        previo = r
    return eleccion, faltan


def ejecutar(ctx):
    p = ctx.params
    if p["modo"] == "escenas":
        return _ejecutar_escenas(ctx)
    planos = (ctx.salidas["voz"] or {}).get("planos") or []
    recursos = (ctx.salidas["recursos"] or {}).get("recursos") or []
    if not planos:
        raise ValueError("la voz no produjo planos")
    if not recursos:
        raise ValueError("no hay recursos")
    por_id = {r["id"]: r for r in recursos}
    carpeta = ctx.dir("asignacion")

    if p["modo"] == "orden":
        eleccion = _rellenar(planos, recursos, {}, ordenado=True)
    else:
        ruta_base = os.path.join(carpeta, "base.json")
        clave = _clave(planos, recursos, p)
        base = almacen.leer_json(ruta_base, {}) or {}
        if base.get("clave") == clave:
            ctx.avisar("eleccion de Claude reutilizada (mismas entradas)", 50)
            eleccion = {int(k): tuple(v) for k, v in base["eleccion"].items()}
        else:
            eleccion = _con_claude(planos, recursos, p, ctx)
            faltan = len(planos) - len(eleccion)
            if faltan:
                logger.warning(f"Claude dejo {faltan} planos sin asignar: se rellenan")
            eleccion = _rellenar(planos, recursos, eleccion)
            almacen.escribir_json(ruta_base, {"clave": clave, "eleccion": {str(k): v for k, v in eleccion.items()}})

    fijados = {int(k): v for k, v in (p.get("fijados") or {}).items() if v in por_id}
    cursor = Counter()
    salida = []
    for x in planos:
        i = x["i"]
        rid, motivo = eleccion[i]
        fijado = i in fijados
        if fijado:
            rid, motivo = fijados[i], "fijado a mano"
        r = por_id[rid]
        dur = x["fin"] - x["inicio"]
        offset = _seguir(cursor, rid, r, dur)
        salida.append({**x, "recurso": rid, "nombre": r["nombre"], "tipo": r["tipo"],
                       "ruta": r["ruta"], "dur_recurso": r.get("duracion", 0.0),
                       "offset": round(offset, 3), "motivo": motivo, "fijado": fijado})

    almacen.escribir_json(os.path.join(carpeta, "planos.json"), salida)
    usados = len({s["recurso"] for s in salida})
    ctx.avisar(f"asignacion lista: {len(salida)} planos, {usados}/{len(recursos)} recursos usados", 100)
    return {"planos": salida, "recursos_usados": usados}


def _seguir(cursor, rid, r, dur):
    """Desde donde se corta un video que ya salio antes: sigue donde se quedo
    (un clip repartido en varios planos no vuelve a empezar). Si lo que queda no
    alcanza, toma el final del clip; ya visto entero, vuelve a empezar."""
    if r["tipo"] != "video" or r["duracion"] <= dur:
        return 0.0
    offset = 0.0 if cursor[rid] >= r["duracion"] - 0.05 else min(cursor[rid], r["duracion"] - dur)
    cursor[rid] = offset + dur
    return offset


def _ejecutar_escenas(ctx):
    p = ctx.params
    escenas = (ctx.salidas.get("escenas") or {}).get("escenas") or []
    recursos = (ctx.salidas["recursos"] or {}).get("recursos") or []
    if not escenas:
        raise ValueError("no hay escenas: ejecuta la etapa Escenas primero")
    if not recursos:
        raise ValueError("no hay contenido subido para las escenas")
    por_id = {r["id"]: r for r in recursos}
    eleccion, faltan = _por_escenas(escenas, recursos, p.get("preferir", "video"))
    fijados = {int(k): v for k, v in (p.get("fijados") or {}).items() if v in por_id}
    cursor = Counter()
    salida = []
    for e in escenas:
        i = e["scene_number"] - 1
        rid, motivo = eleccion[e["scene_number"]]
        fijado = i in fijados
        if fijado:
            rid, motivo = fijados[i], "fijado a mano"
        r = por_id[rid]
        offset = _seguir(cursor, rid, r, e["fin"] - e["inicio"])
        salida.append({"i": i, "inicio": e["inicio"], "fin": e["fin"], "texto": e["narration"],
                       "escena": e["scene_number"], "recurso": rid, "nombre": r["nombre"], "tipo": r["tipo"],
                       "ruta": r["ruta"], "dur_recurso": r.get("duracion", 0.0), "offset": round(offset, 3),
                       "motivo": motivo, "fijado": fijado})
    almacen.escribir_json(os.path.join(ctx.dir("asignacion"), "planos.json"), salida)
    if faltan:
        logger.warning(f"escenas sin archivo: {faltan[:30]}{'...' if len(faltan) > 30 else ''}")
    usados = len({x["recurso"] for x in salida})
    ctx.avisar(f"{len(salida)} escenas asignadas, {len(faltan)} sin archivo", 100)
    return {"planos": salida, "recursos_usados": usados, "faltan": faltan}
