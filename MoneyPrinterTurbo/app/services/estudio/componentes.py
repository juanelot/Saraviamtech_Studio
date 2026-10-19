"""
Comprobaciones rapidas de componentes externos que se rompen solos cuando el
servicio cambia (no por un cambio nuestro).

edge-tts: Microsoft cambia de vez en cuando lo que exige a los clientes y la
version instalada pasa a recibir 403. Antes, cada intento esperaba 120 s x 3
antes de fallar con un error confuso. Ahora una prueba de ~1 s antes de
sintetizar detecta el 403 y avisa de actualizar, con la version nueva de PyPI.
"""
import asyncio
import time
from importlib import metadata

import requests
from loguru import logger

from app.services import voice

PRUEBA_S = 15
VALIDA_S = 15 * 60          # un OK vale 15 min: no se prueba en cada ejecucion
_ultimo_ok = 0.0


class Desactualizado(RuntimeError):
    pass


def version_instalada(paquete):
    try:
        return metadata.version(paquete)
    except metadata.PackageNotFoundError:
        return None


def version_pypi(paquete):
    try:
        r = requests.get(f"https://pypi.org/pypi/{paquete}/json", timeout=5)
        return r.json()["info"]["version"] if r.ok else None
    except Exception:  # noqa: BLE001
        return None


def es_voz_microsoft(nombre):
    """Las voces que van por edge-tts (azure_tts_v1 en voice.tts)."""
    return not (voice.is_no_voice(nombre) or voice.is_azure_v2_voice(nombre) or voice.is_siliconflow_voice(nombre)
                or voice.is_gemini_voice(nombre) or voice.is_mimo_voice(nombre))


def _probar_edge(nombre_voz):
    import edge_tts

    async def uno():
        async for trozo in edge_tts.Communicate("ok", nombre_voz).stream():
            if trozo["type"] == "audio":
                return

    asyncio.run(asyncio.wait_for(uno(), timeout=PRUEBA_S))


def comprobar_edge_tts(nombre_voz):
    """Lanza Desactualizado si Microsoft rechaza la version instalada (403).
    Otros fallos (red lenta, voz rara) no paran nada: sigue el camino normal."""
    global _ultimo_ok
    if time.time() - _ultimo_ok < VALIDA_S:
        return
    try:
        _probar_edge(nombre_voz)
        _ultimo_ok = time.time()
    except Exception as e:  # noqa: BLE001
        texto = str(e)
        if "403" not in texto:
            logger.warning(f"prueba de edge-tts sin resultado claro: {texto[:200]}")
            return
        actual, nueva = version_instalada("edge-tts"), version_pypi("edge-tts")
        hay_nueva = nueva and nueva != actual
        raise Desactualizado(
            f"Microsoft rechazo la conexion de voz (403): la version de edge-tts instalada ({actual}) "
            f"esta desactualizada. "
            + (f"Hay una nueva ({nueva}): " if hay_nueva else "Actualizala: ")
            + "en MoneyPrinterTurbo ejecuta `uv pip install --python .venv/Scripts/python.exe -U edge-tts`, "
            "pon la version en requirements.txt y reinicia el backend (en el VPS, reconstruye la imagen)."
        ) from e
