# Plan: generar las imágenes de las escenas en Google Flow (solo local)

Fecha: 2026-10-18 · Estado: **aprobado, sin implementar** (se hace al día siguiente)

## Objetivo
Automatizar el único paso manual del modo "escenas" del Estudio:

```
HOY:   Escenas → script.json → [bajar, abrir extensión en Flow, generar, subir images/] → Contenido → Video
NUEVO: Escenas → [botón "Generar en Flow": automático, con reintentos y retomable]       → Contenido → Video
```

- **Solo imágenes** (Nano Banana 2, gratis). Videos no: en Flow gastan créditos (Veo).
- **Solo en la máquina local.** VPS, Kie, modo local y subida manual quedan **igual**.
- Debe comportarse como la extensión "AI Content Generator" (repo hans1801/vibes-content-generator).

## Comportamiento copiado de la extensión (verificado en su código)
| Qué | Extensión | Nosotros |
|---|---|---|
| Qué escena está hecha | existe `images/scene_NNNN.jpeg` | igual: **el archivo manda**, no hay estado aparte |
| Al empezar | solo las pendientes ("12 pendientes · 88 ya generadas") | igual |
| Intentos por escena | 4 (`MAX_GENERATION_ATTEMPTS`) | 4 |
| Espera por intento | hasta 2 min (80 × 1,5 s) | igual |
| Señal "generando" / "falló" | `flow-pending-tile` / `flow-error-tile` | igual (más fiable que el texto del MCP) |
| "Terminó" | 0 pendientes durante 3 s (`MEDIA_STABILIZE_MS`) | igual |
| Pausa tras escena OK | 4 s | 4 s |
| Pausa tras escena fallida | 4,5 s y sigue con la siguiente | igual |
| Fallidas | quedan sin archivo → pendientes en la próxima corrida | igual **+ repaso automático** |
| Apagar la máquina | no se pierde nada | igual (y sobrevive a reiniciar backend/Chrome) |
| Escritura | el archivo de referencia se escribe al final | `.part` + rename (atómico) |

### Mejoras sobre la extensión
1. **Repaso automático:** al terminar la vuelta, hasta 2 pasadas más solo con las fallidas.
2. **Límite de Flow:** si Flow avisa de cuota/límite → **pausa** el lote (quedan pendientes), no quema intentos.
3. **Sin bajar/subir:** las imágenes caen directo en `recursos/images/` del proyecto.

## Arquitectura

### 1. Generador Node — `tools/flow/` (nuevo)
Basado en el código de `srzGoogleFlowMCP.zip` (Playwright + Chrome dedicado por CDP), con:
- **Bugs corregidos** (vistos en la prueba del 2026-10-18):
  - `newProject`: en español el botón es "Proyecto nuevo" (el MCP busca "Nuevo proyecto") → buscar por icono `add` o ambas variantes.
  - `configure`: a veces lee el resumen antes de que aplique x1 → reintentar la verificación 2-3 veces con espera.
  - Imagen con texto incrustado → añadir "no text, no letters" al prompt.
- **Detección de la extensión:** `flow-pending-tile`, `flow-error-tile`, diff de `img[data-media-id]`.
- **Comando de lote:**
  ```
  node tools/flow/lote.js --script <escenas/script.json> --out <recursos/images> \
       --aspect 9:16 --model 2 [--solo 3,7,12]
  ```
  - Lee escenas, salta las que ya tienen `scene_NNNN.jpeg`, genera una a una con las pausas de arriba.
  - **1 imagen por escena** (x1), guardada como `scene_NNNN.jpeg` plano.
  - Progreso por stdout en líneas JSON: `{"escena":7,"estado":"ok|error|intento","intento":2,"motivo":"..."}`
  - Archivo de parada (`.detener`) o SIGTERM → termina la escena en curso o la abandona limpiamente.
  - Lock entre procesos (`lock.js` del MCP) → nunca dos lotes sobre el mismo Chrome.
- `node tools/flow/cli.js chrome` → abre el Chrome de Flow para iniciar sesión (perfil `%LOCALAPPDATA%\FlowImageChrome`, ya tiene sesión).
- `node_modules/` fuera de git (`.gitignore`); `npm install` en la máquina local.

### 2. Backend — `app/services/estudio/flow_gen.py` (nuevo)
- `iniciar(pid, opciones)`: lanza `lote.js` como subproceso en un hilo (patrón de `grafo.py`: `_vivos`, Event de cancelar), lee las líneas JSON y guarda `proyectos/<id>/flow/estado.json` (por escena: ok/error/intentos/motivo, pasada actual).
- `estado(pid)`: pendientes = escenas del script sin archivo; ok = con archivo; error = de estado.json.
- `detener(pid)`: crea `.detener` / termina el proceso. Lo pendiente queda pendiente.
- Al reiniciar backend: nada que recuperar, el estado real son los archivos.
- Endpoints nuevos en `app/controllers/v1/estudio.py`:
  - `GET  /estudio/flow` → `{habilitado, sesion_ok}`
  - `POST /estudio/flow/conectar` → abre el Chrome de Flow
  - `POST /estudio/proyectos/{pid}/flow/generar` → `{reintentar_fallidas?: bool}`
  - `POST /estudio/proyectos/{pid}/flow/detener`
  - `GET  /estudio/proyectos/{pid}/flow` → progreso por escena
- **Config** (`config.toml` / `config.example.toml`):
  ```toml
  estudio_flow_habilitado = false   # true SOLO en la máquina local
  estudio_flow_dir = ""             # ruta a tools/flow (vacío = la del repo)
  estudio_flow_modelo = "2"         # pro | 2 | lite
  estudio_flow_pasadas_extra = 2
  ```
  Con `false` (VPS) los endpoints responden 404 y la UI no muestra nada.

### 3. Estudio UI — `estudio-ui`
- En el paso **Contenido** (`components/paneles/PanelRecursos.tsx`), solo si `habilitado`:
  - Botón **"Generar en Flow (N pendientes · M listas)"**.
  - Cuadrícula de escenas ✓ / ✗ / ⏳ / ▶ (en curso) con el motivo del error al pasar el ratón.
  - **Detener** y **Continuar**; "Conectar Flow" si no hay sesión.
  - Polling cada 3 s mientras corre; al terminar refresca la lista de archivos.
- `lib/api.ts`: funciones para los 5 endpoints.

## Idioma de Flow (lo usará más gente: Flow en español, inglés u otro)
El idioma de la web de Flow sigue al de la cuenta de Google, así que **nada puede depender de textos visibles**:
- **Botones y menús por icono Material o clase CSS**, no por etiqueta: "Proyecto nuevo"/"New project" →
  botón con icono `add` en la home; subir = `upload`, renombrar = `edit`, etc. (el MCP falló justo por esto).
- **Ajustes por valor**, no por texto: radios `9:16`, `x1`; tipo imagen = primer radio del primer grupo;
  modelo por su nombre propio "Nano Banana …" (no se traduce).
- **Éxito / error por elementos**, no por mensajes: `img[data-media-id]`, `flow-pending-tile`, `flow-error-tile`.
- **Límite/cuota:** es lo único que obliga a leer texto → lista de frases en varios idiomas (es, en, pt, fr, it, de)
  en un solo archivo (`tools/flow/textos.js`) fácil de ampliar. Si no se reconoce, se trata como error normal
  (4 intentos), así que un idioma no listado nunca rompe el lote, solo no pausa a tiempo.
- **Inicio de sesión:** detectar por URL (`accounts.google.com`), no por texto.
- **Mensajes del sistema al usuario** (UI y logs del Estudio) en español, como el resto del Estudio.
- **Prueba obligatoria en los dos idiomas:** cambiar el idioma de la cuenta de Google de prueba a inglés,
  correr el lote de 5 escenas, volver a español y repetir.

## Puntos a cuidar (revisados en el código)
- **No crear subcarpetas de variantes dentro de `recursos/`**: `recursos._recorrer` es recursivo y
  `numero_escena("images/scene_0007/image_0001.jpeg")` da **1**, no 7 → asignaría mal. Por eso se guarda
  solo `images/scene_NNNN.jpeg` plano. (Si algún día se quieren variantes, fuera de `recursos/`.)
- `asignacion._por_escenas` ya busca por `escena` + carpeta `images` → **no se toca**.
- `subcarpeta_de` ya reconoce `images/` → los archivos generados se ven igual que los subidos a mano.
- El formato (9:16 / 16:9) sale del aspecto del proyecto (el mismo que usa Escenas).
- Revisar si la etapa Recursos describe con Claude (visión) estas imágenes en modo escenas; si sí, que
  no gaste tokens innecesarios (ya va cacheado por hash).
- Una sola generación a la vez en toda la máquina (Flow solo admite una acción).

## Orden de trabajo
1. `tools/flow/`: copiar MCP, corregir 3 bugs, escribir `lote.js`. Probar con un script.json de 5 escenas
   (incluye: matar a mitad y relanzar → retoma; escena con prompt inválido → 4 intentos y sigue).
2. `flow_gen.py` + endpoints + config. Probar por curl.
3. UI en Contenido. Probar de punta a punta: Escenas → Generar en Flow → Video.
4. Verificar que con `estudio_flow_habilitado=false` todo queda igual que hoy.
4b. Repetir la prueba de 5 escenas con la cuenta de Google en **inglés** y en **español**.
5. Instrucciones para la otra máquina: Node 18+, Chrome, `npm install` en `tools/flow`, `config` en true,
   "Conectar Flow" e iniciar sesión una vez.

## Datos de la prueba (2026-10-18)
- 5/5 imágenes OK, 26-36 s cada una (~32 s) → 200 escenas ≈ 2 h sin fallos.
- 768×1376 en 9:16 (1K completo). Estilo MS Paint muy fiel.
- Sesión ya iniciada en `%LOCALAPPDATA%\FlowImageChrome` en esta máquina.
