"""
Proveedor LLM "claude_cli": usa el CLI de Claude Code en modo headless
(`claude -p`) con la sesion/suscripcion del usuario, sin API key.

Adaptado de pasos/cli_claude.py de AS Video Studio. Reglas que se conservan:

- La instruccion va SIEMPRE por stdin: un guion largo no cabe en una linea de
  comandos de Windows.
- `--effort` va SIEMPRE explicito: sin el, el CLI puede pensar minutos antes de
  escribir (medido en AS: 605 s sin flag vs 67 s con `low`).
- Se quitan del entorno del hijo las variables que sacarian la llamada de la
  suscripcion (API key, token, pasarela, Bedrock/Vertex).
- Timeout finito que mata el arbol de procesos.

Config (config.toml, seccion [app]):
    llm_provider = "claude_cli"
    claude_cli_model = "sonnet"     # haiku | sonnet | opus | id completo claude-*
    claude_cli_effort = "low"       # low | medium | high | xhigh | max
    claude_cli_timeout = 0          # segundos; 0 = automatico segun esfuerzo
    claude_cli_path = ""            # vacio = buscar `claude` en el PATH
"""
import json
import os
import re
import shutil
import subprocess

from loguru import logger

from app.config import config

MODELOS = ("haiku", "sonnet", "opus")
PATRON_MODELO_COMPLETO = re.compile(r"^claude-[a-z0-9][a-z0-9.\-]*$")
ESFUERZOS = ("low", "medium", "high", "xhigh", "max")
FACTOR_ESFUERZO = {"low": 1.0, "medium": 2.5, "high": 5.0, "xhigh": 8.0, "max": 12.0}
FACTOR_MODELO = {"haiku": 0.6, "sonnet": 1.0, "opus": 2.2}
TIEMPO_BASE_S = 300
TIEMPO_MAXIMO_S = 3600

ENTORNO_FUERA = ("CLAUDE_EFFORT", "MAX_THINKING_TOKENS")
PAGO_POR_USO = ("ANTHROPIC_API_KEY", "ANTHROPIC_AUTH_TOKEN", "ANTHROPIC_BASE_URL",
                "CLAUDE_CODE_USE_BEDROCK", "CLAUDE_CODE_USE_VERTEX")

# Solo se quiere texto: sin herramientas el CLI contesta en un turno.
HERRAMIENTAS_VETADAS = ("Bash", "Edit", "Write", "NotebookEdit", "WebFetch",
                        "WebSearch", "Task", "Agent", "Read", "Glob", "Grep")

SIN_VENTANA = {}
if os.name == "nt":
    SIN_VENTANA = {"creationflags": getattr(subprocess, "CREATE_NO_WINDOW", 0x08000000)}


class LimiteAgotado(RuntimeError):
    """La suscripcion no tiene cupo ahora mismo."""


def _modelo(valor):
    valor = (valor or "sonnet").strip()
    if valor in MODELOS or PATRON_MODELO_COMPLETO.match(valor):
        return valor
    raise ValueError(f"claude_cli_model no valido: {valor!r} (usa {', '.join(MODELOS)} o claude-*)")


def _esfuerzo(valor):
    valor = (valor or "low").strip()
    if valor in ESFUERZOS:
        return valor
    raise ValueError(f"claude_cli_effort no valido: {valor!r} (usa {', '.join(ESFUERZOS)})")


def _tiempo_max(modelo, esfuerzo):
    factor = FACTOR_ESFUERZO[esfuerzo] * FACTOR_MODELO.get(modelo, 1.0)
    return min(TIEMPO_MAXIMO_S, int(TIEMPO_BASE_S * factor))


def localizar():
    ruta = config.app.get("claude_cli_path", "") or shutil.which("claude")
    if not ruta:
        raise RuntimeError(
            "claude_cli: no se encontro el CLI `claude`. Instala Claude Code e inicia "
            "sesion (`claude` y luego /login), o pon claude_cli_path en config.toml."
        )
    return ruta


def _entorno():
    env = dict(os.environ)
    for clave in ENTORNO_FUERA + PAGO_POR_USO:
        env.pop(clave, None)
    return env


def _matar_arbol(proceso):
    try:
        if os.name == "nt":
            subprocess.run(["taskkill", "/F", "/T", "/PID", str(proceso.pid)],
                           capture_output=True, **SIN_VENTANA)
        else:
            proceso.kill()
    except Exception:  # noqa: BLE001
        pass


def ejecutar(prompt: str, modelo=None, esfuerzo=None, tiempo_max_s=None,
             sistema=None, cwd=None, permitidas=()) -> str:
    """Lanza `claude -p` y devuelve el texto de la respuesta.

    `permitidas`: herramientas que puede usar sin pedir permiso (p. ej. ("Read",)
    para que mire miniaturas dentro de `cwd`). Lo demas queda vetado.
    """
    modelo = _modelo(modelo or config.app.get("claude_cli_model", "sonnet"))
    esfuerzo = _esfuerzo(esfuerzo or config.app.get("claude_cli_effort", "low"))
    if tiempo_max_s is None:
        tiempo_max_s = int(config.app.get("claude_cli_timeout", 0) or 0)
    if not tiempo_max_s:
        tiempo_max_s = _tiempo_max(modelo, esfuerzo)
    if sistema and ("\n" in sistema or "\r" in sistema):
        # En Windows un salto de linea parte la orden de claude.cmd.
        raise ValueError("claude_cli: el prompt de sistema debe ir en una sola linea")

    orden = [localizar(), "-p",
             "--model", modelo,
             "--effort", esfuerzo,
             "--output-format", "json",
             "--strict-mcp-config"]
    if permitidas:
        orden += ["--allowedTools", ",".join(permitidas)]
    vetadas = [h for h in HERRAMIENTAS_VETADAS if h not in permitidas]
    if vetadas:
        orden += ["--disallowedTools", ",".join(vetadas)]
    if sistema:
        orden += ["--append-system-prompt", sistema]

    logger.info(f"claude_cli: modelo={modelo} esfuerzo={esfuerzo} timeout={tiempo_max_s}s")
    proceso = subprocess.Popen(
        orden, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        env=_entorno(), cwd=cwd or os.path.expanduser("~"),
        encoding="utf-8", errors="replace", **SIN_VENTANA,
    )
    try:
        salida, errores = proceso.communicate(prompt, timeout=tiempo_max_s)
    except subprocess.TimeoutExpired:
        _matar_arbol(proceso)
        proceso.communicate()
        raise TimeoutError(f"claude_cli: sin respuesta en {tiempo_max_s}s ({modelo}/{esfuerzo})")

    sobre = None
    try:
        sobre = json.loads(salida) if salida.strip() else None
    except json.JSONDecodeError:
        pass

    if isinstance(sobre, dict):
        texto = sobre.get("result") or ""
        if sobre.get("is_error") or proceso.returncode != 0:
            _lanzar_fallo(texto or errores or salida)
        if not texto.strip():
            raise ValueError("claude_cli: respuesta vacia")
        coste = sobre.get("total_cost_usd")
        logger.info(f"claude_cli: ok en {sobre.get('duration_ms', 0) / 1000:.1f}s"
                    + (f" (coste equivalente ${coste:.4f}, cubierto por la suscripcion)" if coste else ""))
        return texto

    _lanzar_fallo(errores or salida or f"codigo de salida {proceso.returncode}")


def extraer_json(texto: str):
    """Saca el primer bloque JSON (lista u objeto) de una respuesta del modelo."""
    bloque = re.search(r"```(?:json)?\s*(.*?)```", texto, re.DOTALL)
    if bloque:
        texto = bloque.group(1)
    texto = texto.strip()
    for abre, cierra in (("[", "]"), ("{", "}")):
        i, j = texto.find(abre), texto.rfind(cierra)
        if i != -1 and j > i:
            try:
                return json.loads(texto[i:j + 1])
            except json.JSONDecodeError:
                continue
    raise ValueError(f"claude_cli: la respuesta no trae JSON valido: {texto[:300]}")


def _lanzar_fallo(mensaje):
    mensaje = (mensaje or "").strip()[:500]
    bajo = mensaje.lower()
    if "limit" in bajo and ("reset" in bajo or "reached" in bajo or "usage" in bajo):
        raise LimiteAgotado(f"claude_cli: cupo de la suscripcion agotado: {mensaje}")
    if "login" in bajo or "authenticat" in bajo or "oauth" in bajo:
        raise RuntimeError(f"claude_cli: sesion no iniciada o caducada (ejecuta `claude` y /login): {mensaje}")
    raise RuntimeError(f"claude_cli: fallo: {mensaje}")
