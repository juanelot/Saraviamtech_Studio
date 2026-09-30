#!/usr/bin/env python3
"""
CLI de PROMPTS MAESTROS del Estudio (para Hermes, n8n, cron).

Ejecuta un prompt maestro con Claude (modo automatico: elige la opcion
recomendada en cada paso), espera los entregables y los guarda en disco:
guion, prompts de imagen/video, script.json (extension de Flow), hojas de
referencia. Tambien series (biblia + episodios) y "crear video".

Subcomandos:
  listar                                   maestros y sus series
  crear     --maestro X --tema "..."       nueva creacion (o --serie S: nuevo episodio)
  responder --maestro X --creacion C --texto "..."   contestar cuando el flujo se para
  estado    --maestro X --creacion C       ver en que va (y volver a guardar entregables)
  serie     --maestro X --creacion C       convertir una creacion en serie (espera la biblia)
  video     --maestro X --creacion C --narracion demostracion   proyecto del Estudio
  ultimo-fotograma clip.mp4                PNG del ultimo fotograma (segmentos encadenados)

--maestro acepta el id o parte del nombre ("paper craft").

Ejemplos:
  python maestros_cli.py listar
  python maestros_cli.py crear --maestro "paper craft" --tema "un faro en una isla" --sin-paradas --out ./flow/faro
  python maestros_cli.py crear --maestro "collage" --serie 2eada1f133bb --tema "Area 51"
  python maestros_cli.py video --maestro "paper craft" --creacion <id> --narracion sin_voz
  #   luego se sube lo creado en Flow y se monta con estudio_cli.py:
  python estudio_cli.py --proyecto <PROYECTO> --contenido-dir ./flow/faro --out ./videos

Salida: imprime CREACION=<id>, SERIE=<id>, PROYECTO=<id> para retomarlos.
Codigos: 0 listo, 1 error, 2 el flujo espera una respuesta (se imprimen la
pregunta y las opciones: contestar con `responder`).

Variables de entorno (las de estudio_cli.py): MPT_API_BASE, MPT_BASIC_AUTH.
Local: MPT_API_BASE=http://localhost:8080/api/v1
"""

import argparse
import json
import sys
import time
from pathlib import Path

import requests

from estudio_cli import DEFAULT_API_BASE, Api

ESPERA_MAX_S = 3 * 3600
SIN_PARADAS = "contestar solo las pausas de una unica opcion (\"escribe next cuando tengas las imagenes\")"


def log(msg):
    print(f"[{time.strftime('%H:%M:%S')}] {msg}", flush=True)


class ApiMaestros(Api):
    def _r(self, metodo, ruta, **kw):
        # Las esperas duran horas: un corte suelto de red (conexion reiniciada) no
        # debe tumbar el CLI. Solo se reintentan lecturas (GET), que no repiten nada.
        for intento in range(6):
            try:
                return super()._r(metodo, ruta, **kw)
            except requests.ConnectionError as e:
                if metodo != "GET" or intento == 5:
                    raise RuntimeError(f"{metodo} {ruta}: sin conexion ({e})") from e
                time.sleep(3 * (intento + 1))

    def maestros(self):
        return self._r("GET", "/maestros").json()["maestros"]

    def creacion(self, mid, cid):
        return self._r("GET", f"/maestros/{mid}/creaciones/{cid}").json()


def buscar_maestro(api, texto):
    lista = api.maestros()
    for m in lista:
        if m["id"] == texto:
            return m
    t = texto.lower()
    hits = [m for m in lista if t in m["nombre"].lower()]
    if len(hits) == 1:
        return hits[0]
    if not hits:
        raise RuntimeError(f'ningun prompt maestro coincide con "{texto}" (usa `listar`)')
    raise RuntimeError(f'"{texto}" coincide con varios: ' + ", ".join(f'{m["nombre"]} ({m["id"]})' for m in hits))


def esperar_creacion(api, mid, cid, timeout):
    """Hasta que Claude deja de pensar. Devuelve la creacion."""
    t0, ultimo = time.time(), -1
    while True:
        c = api.creacion(mid, cid)
        if len(c["turnos"]) != ultimo:
            ultimo = len(c["turnos"])
            t = c["turnos"][-1] if c["turnos"] else None
            if t:
                quien = "auto" if t.get("auto") else ("Claude" if t["rol"] == "claude" else "tu")
                log(f"{quien}: {' '.join(t['texto'].split())[:160]}")
        if not c["pensando"]:
            return c
        if time.time() - t0 > timeout:
            raise RuntimeError(f"tiempo agotado ({timeout} s) esperando a Claude")
        time.sleep(5)


def _escribir(ruta: Path, texto):
    ruta.parent.mkdir(parents=True, exist_ok=True)
    ruta.write_text(texto, encoding="utf-8")
    log(f"guardado {ruta}")


def guardar_entregables(e, out: Path):
    out.mkdir(parents=True, exist_ok=True)
    _escribir(out / "entregables.json", json.dumps(e, ensure_ascii=False, indent=2))
    if e.get("guion"):
        _escribir(out / "guion.txt", e["guion"])
    imagenes = [s["imagen"] for s in e["escenas"] if s.get("imagen")]
    videos = [s["video"] for s in e["escenas"] if s.get("video")]
    if imagenes:
        _escribir(out / "prompts-imagen.txt", "\n\n".join(imagenes))
    if videos:
        _escribir(out / "prompts-video.txt", "\n\n".join(videos))
    if e["escenas"]:
        script = {"scenes": [{"scene_number": s["n"], "image_prompt": s.get("imagen") or "",
                              "video_prompt": s.get("video") or "", "narration": s.get("narracion") or ""}
                             for s in e["escenas"]]}
        _escribir(out / "script.json", json.dumps(script, ensure_ascii=False, indent=2))
    refs = e.get("referencias") or []
    if refs:
        _escribir(out / "referencias.txt", "\n\n".join(
            f"## {r['nombre']} ({r['tipo']}){' -> ' + r['archivo'] if r.get('archivo') else ''}"
            f"{' [imagen ya subida]' if r.get('imagen') else ''}\n{r.get('prompt') or ''}" for r in refs))
    encadenadas = [s["n"] for s in e["escenas"] if s.get("continua")]
    if encadenadas:
        log(f"escenas que empiezan con el ultimo fotograma de la anterior: {encadenadas} "
            "(usa `ultimo-fotograma clip.mp4`)")


def terminar(api, mid, c, out, timeout, forzar=False):
    """Tras un turno: flujo terminado -> entregables a disco (0); parado -> pregunta (2).
    `forzar`: ordenarlos ya aunque Claude no marcara el flujo como terminado."""
    if c.get("error"):
        log(f"aviso: {c['error']}")
    ultimo = next((t for t in reversed(c["turnos"]) if t["rol"] == "claude"), None)
    app = (ultimo or {}).get("app") or {}
    if forzar:
        log("ordenando los entregables…")
        api._r("POST", f"/maestros/{mid}/creaciones/{c['id']}/entregables")
        # "pensando" se activa al pedirlos y se apaga al terminar (evita leer los anteriores).
        c = esperar_creacion(api, mid, c["id"], timeout)
    elif app.get("tipo") != "fin":
        if c.get("error") and (not c["turnos"] or c["turnos"][-1]["rol"] == "persona"):
            return 1
        print("\n--- EL FLUJO ESPERA UNA RESPUESTA ---")
        print((ultimo or {}).get("texto", "")[-3000:])
        if app.get("opciones"):
            print("\nOPCIONES: " + " | ".join(app["opciones"]))
        print(f"\nContesta con: python maestros_cli.py responder --maestro {mid} --creacion {c['id']} --texto \"...\"")
        print(f"Si ya entrego todo: python maestros_cli.py estado --maestro {mid} --creacion {c['id']} --entregables")
        return 2
    t0 = time.time()
    while c.get("entregables_estado") != "listo":
        if c.get("entregables_estado") == "error":
            raise RuntimeError(f"no se pudieron ordenar los entregables: {c.get('entregables_error')}")
        if time.time() - t0 > timeout:
            raise RuntimeError("tiempo agotado esperando los entregables")
        if c.get("entregables_estado") is None and not c["pensando"]:
            api._r("POST", f"/maestros/{mid}/creaciones/{c['id']}/entregables")
        time.sleep(5)
        c = api.creacion(mid, c["id"])
    e = c["entregables"]
    log(f"entregables: {len(e['escenas'])} escenas, {len(e.get('referencias') or [])} referencias, "
        f"{len(e['miniaturas'])} miniaturas")
    guardar_entregables(e, Path(out))
    return 0


def seguir(api, mid, cid, c, a):
    """terminar() y, con --sin-paradas, contestar solo las pausas de UNA opcion
    (p. ej. "escribe next cuando tengas las imagenes")."""
    out = a.out or f"./maestros/{cid}"
    for _ in range(40):
        rc = terminar(api, mid, c, out, a.timeout)
        ultimo = next((t for t in reversed(c["turnos"]) if t["rol"] == "claude"), None)
        opciones = ((ultimo or {}).get("app") or {}).get("opciones") or []
        if rc != 2 or not getattr(a, "sin_paradas", False) or len(opciones) != 1:
            return rc
        log(f"--sin-paradas: contesto {opciones[0]!r}")
        api._r("POST", f"/maestros/{mid}/creaciones/{cid}/mensaje", json={"texto": opciones[0]})
        c = esperar_creacion(api, mid, cid, a.timeout)
    return rc


def cmd_listar(api, a):
    for m in api.maestros():
        print(f"{m['id']}  {m['nombre']}")
        for s in api._r("GET", f"/maestros/{m['id']}/series").json()["series"]:
            print(f"    serie {s['id']}  {s['titulo']}  ({s['episodios']} episodios)")
    return 0


def cmd_crear(api, a):
    m = buscar_maestro(api, a.maestro)
    datos = {"tema": a.tema or "", "modo": "guiado" if a.guiado else "auto", "modelo": a.modelo}
    if a.serie:
        c = api._r("POST", f"/maestros/{m['id']}/series/{a.serie}/episodios", json=datos).json()
    else:
        c = api._r("POST", f"/maestros/{m['id']}/creaciones", json=datos).json()
    print(f"CREACION={c['id']}", flush=True)
    log(f"{m['nombre']}: {c['titulo']}" + (f" (episodio {c.get('episodio')})" if a.serie else ""))
    c = esperar_creacion(api, m["id"], c["id"], a.timeout)
    return seguir(api, m["id"], c["id"], c, a)


def cmd_responder(api, a):
    m = buscar_maestro(api, a.maestro)
    api._r("POST", f"/maestros/{m['id']}/creaciones/{a.creacion}/mensaje", json={"texto": a.texto})
    if not a.guiado:
        api._r("PATCH", f"/maestros/{m['id']}/creaciones/{a.creacion}", json={"modo": "auto"})
    c = esperar_creacion(api, m["id"], a.creacion, a.timeout)
    return seguir(api, m["id"], a.creacion, c, a)


def cmd_estado(api, a):
    m = buscar_maestro(api, a.maestro)
    c = api.creacion(m["id"], a.creacion)
    info = c.get("serie_info")
    log(f"{c['titulo']} · {len(c['turnos'])} turnos · modo {c['modo']}"
        + (f" · episodio {info['episodio']} de {info['titulo']} ({info['id']})" if info else "")
        + (" · pensando" if c["pensando"] else ""))
    for p in c.get("proyectos") or []:
        print(f"PROYECTO={p['id']}  ({p['narracion']})")
    if c["pensando"]:
        return 0
    if a.entregables:
        return terminar(api, m["id"], c, a.out or f"./maestros/{a.creacion}", a.timeout, forzar=True)
    return seguir(api, m["id"], a.creacion, c, a)


def cmd_serie(api, a):
    m = buscar_maestro(api, a.maestro)
    s = api._r("POST", f"/maestros/{m['id']}/series", json={"desde": a.creacion}).json()
    print(f"SERIE={s['id']}", flush=True)
    log("Claude esta escribiendo la biblia…")
    t0 = time.time()
    while s["preparando"]:
        if time.time() - t0 > a.timeout:
            raise RuntimeError("tiempo agotado esperando la biblia")
        time.sleep(5)
        s = api._r("GET", f"/maestros/{m['id']}/series/{s['id']}").json()
    if s.get("error"):
        raise RuntimeError(f"no se pudo escribir la biblia: {s['error']}")
    log(f"serie lista: {s['titulo']}")
    if a.out:
        _escribir(Path(a.out) / "biblia.md", s["biblia"])
    print(f"Siguiente episodio: python maestros_cli.py crear --maestro {m['id']} --serie {s['id']} --tema \"...\"")
    return 0


def cmd_video(api, a):
    m = buscar_maestro(api, a.maestro)
    datos = {"narracion": a.narracion, **({"aspecto": a.formato} if a.formato else {}),
             **({"titulo": a.titulo} if a.titulo else {}), **({"voz": a.voz} if a.voz else {})}
    r = api._r("POST", f"/maestros/{m['id']}/creaciones/{a.creacion}/video", json=datos, timeout=900).json()
    pid = r["proyecto"]["id"]
    print(f"PROYECTO={pid}", flush=True)
    log(f"proyecto creado: {r['proyecto']['titulo']}")
    print("Sube lo creado en Flow (un archivo por escena, con su numero en el nombre) y monta el video:\n"
          f"  python estudio_cli.py --proyecto {pid} --contenido-dir <carpeta> --out ./videos")
    return 0


def cmd_ultimo(api, a):
    clip = Path(a.clip)
    with open(clip, "rb") as f:
        r = api._r("POST", "/herramientas/ultimo-fotograma", files={"archivo": (clip.name, f)}, timeout=600)
    destino = Path(a.out) if a.out else clip.with_name(clip.stem + "-ultimo-fotograma.png")
    destino.parent.mkdir(parents=True, exist_ok=True)
    destino.write_bytes(r.content)
    log(f"guardado {destino}")
    return 0


def main():
    ap = argparse.ArgumentParser(description="Prompts maestros del Estudio por terminal",
                                 formatter_class=argparse.RawDescriptionHelpFormatter, epilog=__doc__)
    ap.add_argument("--api", default=DEFAULT_API_BASE, help="URL base API v1 (o MPT_API_BASE)")
    ap.add_argument("--timeout", type=int, default=ESPERA_MAX_S, help="espera maxima en segundos (default 3 h)")
    sub = ap.add_subparsers(dest="cmd", required=True)

    sub.add_parser("listar", help="maestros y sus series")

    p = sub.add_parser("crear", help="nueva creacion o episodio (modo automatico)")
    p.add_argument("--maestro", required=True)
    p.add_argument("--tema", help="tema o idea; se contesta cuando el flujo lo pida")
    p.add_argument("--serie", help="id de serie: crea el siguiente episodio")
    p.add_argument("--modelo", default="sonnet", choices=["sonnet", "opus"])
    p.add_argument("--guiado", action="store_true", help="no avanzar solo: parar en cada pregunta")
    p.add_argument("--sin-paradas", action="store_true", help=SIN_PARADAS)
    p.add_argument("--out", help="carpeta para los entregables (default ./maestros/<creacion>)")

    p = sub.add_parser("responder", help="contestar cuando el flujo se para")
    p.add_argument("--maestro", required=True)
    p.add_argument("--creacion", required=True)
    p.add_argument("--texto", required=True)
    p.add_argument("--guiado", action="store_true", help="no volver a modo automatico")
    p.add_argument("--sin-paradas", action="store_true", help=SIN_PARADAS)
    p.add_argument("--out")

    p = sub.add_parser("estado", help="estado de una creacion (y guardar entregables)")
    p.add_argument("--maestro", required=True)
    p.add_argument("--creacion", required=True)
    p.add_argument("--sin-paradas", action="store_true", help=SIN_PARADAS)
    p.add_argument("--entregables", action="store_true",
                   help="ordenar y guardar los entregables ya (aunque el flujo no se marcara como terminado)")
    p.add_argument("--out")

    p = sub.add_parser("serie", help="convertir una creacion en serie")
    p.add_argument("--maestro", required=True)
    p.add_argument("--creacion", required=True)
    p.add_argument("--out", help="guardar aqui biblia.md")

    p = sub.add_parser("video", help="crear el proyecto del Estudio con una creacion")
    p.add_argument("--maestro", required=True)
    p.add_argument("--creacion", required=True)
    p.add_argument("--narracion", required=True, choices=["propia", "demostracion", "libre", "sin_voz"])
    p.add_argument("--formato", choices=["9:16", "16:9", "1:1"])
    p.add_argument("--voz", help="p. ej. es-MX-JorgeNeural-Male")
    p.add_argument("--titulo")

    p = sub.add_parser("ultimo-fotograma", help="PNG del ultimo fotograma de un clip")
    p.add_argument("clip")
    p.add_argument("--out", help="ruta del PNG (default: junto al clip)")

    a = ap.parse_args()
    # La consola de Windows no es UTF-8: sin esto los acentos de Claude salen rotos.
    for flujo in (sys.stdout, sys.stderr):
        if hasattr(flujo, "reconfigure"):
            flujo.reconfigure(encoding="utf-8", errors="replace")
    api = ApiMaestros(a.api)
    comandos = {"listar": cmd_listar, "crear": cmd_crear, "responder": cmd_responder, "estado": cmd_estado,
                "serie": cmd_serie, "video": cmd_video, "ultimo-fotograma": cmd_ultimo}
    try:
        sys.exit(comandos[a.cmd](api, a))
    except (RuntimeError, OSError) as e:
        log(f"ERROR: {e}")
        sys.exit(1)
    except KeyboardInterrupt:
        log("interrumpido (la creacion sigue en el servidor)")
        sys.exit(1)


if __name__ == "__main__":
    main()
