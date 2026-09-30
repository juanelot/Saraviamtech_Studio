# MoneyPrinterTurbo — SaraviaMtech Edition

Una versión mejorada de [MoneyPrinterTurbo](https://github.com/harry0703/MoneyPrinterTurbo) con una interfaz web moderna construida desde cero en **Next.js 16 + TypeScript**.

> **Créditos:** Este proyecto está basado en [MoneyPrinterTurbo](https://github.com/harry0703/MoneyPrinterTurbo) de [@harry0703](https://github.com/harry0703). Todos los créditos del motor de generación de videos (FastAPI backend, FFmpeg pipeline, Azure TTS, Pexels/Pixabay integration) corresponden al proyecto original.

---

## ¿Qué es?

Genera videos cortos virales automáticamente con IA:

1. **Guión** — GPT-4o mini escribe el guión según tu tema
2. **Voz** — Azure TTS Edge sintetiza la narración (331+ voces, gratis)
3. **Clips** — Descarga clips de Pexels, Pixabay, o usa tus propios videos
4. **Video final** — FFmpeg ensambla, añade subtítulos quemados y música de fondo

---

## Mejoras de esta versión (SaraviaMtech UI)

| Característica | Original (Streamlit) | Esta versión (Next.js) |
|---|---|---|
| Interfaz | Streamlit básico | Dark theme moderno, animaciones |
| Voces disponibles | Manual (~80) | 331 voces Azure + 40+ adicionales |
| Logs en tiempo real | Terminal externa | Panel visual en la UI |
| Timeout FFmpeg | Sin aviso | Banner automático + 30 min de espera |
| Biblioteca de videos | No existe | Grid con player, descarga y eliminación |
| Medios locales | Solo ruta manual | Subida de archivos desde la UI |
| Caché de clips | No gestionable | Botón limpiar caché con info de tamaño |
| Fuente de clips | Pexels solamente | Pexels + Pixabay + Local |
| Preview de voz | No existe | Preview con player de audio integrado |

---

## Estructura del proyecto

```
MoneyPrinterTurbo_saraviamtech/
├── MoneyPrinterTurbo/          # Backend Python (FastAPI) — proyecto original
│   ├── app/
│   ├── storage/
│   │   ├── tasks/              # Videos generados
│   │   ├── cache_videos/       # Clips descargados de Pexels/Pixabay
│   │   └── local_videos/       # Tus videos locales
│   ├── config.toml             # Configuración principal
│   └── main.py
└── mpt-ui/                     # Frontend Next.js (esta mejora)
    ├── app/
    │   ├── page.tsx            # Root — tabs Crear / Mis videos
    │   └── api/library/        # API para gestión de biblioteca
    ├── components/
    │   ├── VideoForm.tsx        # Formulario principal
    │   ├── GenerationProgress.tsx
    │   ├── VideoResult.tsx
    │   ├── VideoLibrary.tsx     # Biblioteca de videos
    │   └── LogPanel.tsx         # Panel de logs en tiempo real
    └── lib/
        └── voices.ts            # 331 voces Azure generadas desde azure_voices.json
```

---

## Instalación

### Requisitos previos

- Python 3.10+
- Node.js 18+
- FFmpeg instalado y en PATH
- ImageMagick (para subtítulos)

### 1. Clonar el repositorio

```bash
git clone https://github.com/juanelot/MoneyPrinterTurbo_saraviamtech.git
cd MoneyPrinterTurbo_saraviamtech
```

### ⚠️ Requisito: Git LFS

Las canciones MP3 y fuentes TTF/TTC se almacenan con **Git LFS**. Asegúrate de tenerlo instalado antes de clonar:

```bash
# Instalar Git LFS (solo una vez por máquina)
git lfs install
```

Descarga en Windows: https://git-lfs.com — con LFS instalado el `git clone` descarga todo automáticamente.

### 2. Configurar el backend

```bash
cd MoneyPrinterTurbo
python -m venv .venv
.venv\Scripts\activate        # Windows
pip install -r requirements.txt
```

Edita `config.toml` y agrega tus API keys:

```toml
[app]
openai_api_key = "sk-..."          # GPT-4o mini para guiones
pexels_api_keys = ["tu-key"]       # gratis en pexels.com/api
pixabay_api_keys = ["tu-key"]      # gratis en pixabay.com/api/docs
```

Inicia el backend:

```bash
python main.py
# Corre en http://localhost:8080
```

### 3. Configurar el frontend

```bash
cd ../mpt-ui
npm install
npm run dev
# Corre en http://localhost:3000
```

---

## Uso

1. Abre `http://localhost:3000`
2. Escribe el tema del video en "Asunto"
3. Elige fuente de clips: **Pexels**, **Pixabay** o **Local**
4. Selecciona voz (filtra por idioma)
5. Haz clic en **Generar video**
6. Espera 5–15 minutos (FFmpeg ensambla el video final)
7. Descarga desde la pantalla de resultado o desde **Mis videos**

### Medios locales

Si quieres usar tus propios clips:
- Selecciona "Local (archivos propios)" como fuente
- Sube videos (MP4, MOV, AVI, FLV, MKV) o imágenes (JPG, PNG)
- **Resolución mínima: lado corto ≥ 400px** (clips verticales de IA tipo 464×832 sirven).
  Los que no cumplan se descartan con un aviso en los logs.
- Las imágenes se convierten a clips con efecto zoom (~30-60s de procesado por
  imagen — sube solo las necesarias: con clips de 4s, ~15 imágenes ≈ 1 min de video)
- Si un archivo aparece como "skip unreadable local material", está corrupto o es
  una imagen renombrada como .mp4 — re-exportarlo

### Música de fondo personalizada

En "Música de fondo" hay 3 opciones: **Sin música**, **Aleatoria** (MP3s incluidos
en `resource/songs`) y **Personalizada**:
- Al elegir "Personalizada" aparece el botón **Subir música** (MP3) y la lista de
  canciones subidas — haz clic en una para seleccionarla
- Sin canción seleccionada el video sale **sin** música
- Disponible tanto en "Crear video" como en el modo Zenn; las canciones subidas
  se comparten entre ambos
- En el VPS las canciones persisten en `/root/mpt-data/songs` (ver [DEPLOY.md](DEPLOY.md))

---

## Estudio por etapas (`estudio-ui/` + `estudio_cli.py`)

App aparte, con la marca Saraviamtech (nombre y rutas de los logos en `estudio-ui/lib/marca.ts`; los logos están en `estudio-ui/public/marca/`, el favicon en `estudio-ui/app/icon.png` y los colores en `app/globals.css`), que usa este mismo backend como motor. En lugar de ir a Pexels o generar imágenes, trabaja con **tus recursos**: imágenes y videos mezclados, subidos, en una carpeta del servidor o como URLs. **Claude CLI** hace el trabajo de texto con tu suscripción, sin API key.

```
material → guion (Claude) → voz (TTS) → escenas + prompts (Claude) ─┐   ← contenido creado por ti en Flow / extensión
                                     recursos (tus archivos) ────────┴→ ajuste (por escena, o Claude elige) → video
```

- **Por etapas y con firma.** Cada etapa guarda la firma de sus entradas (idea tomada de AS Video Studio). Si cambias algo, solo se rehace lo que dependía de eso: otra música rehace el acabado, fijar un plano a mano rehace ese clip, y editar el guion rehace la voz y lo que viene después.
- **Catálogo visual.** Claude mira una miniatura de cada recurso (en los videos, 3 fotogramas) y escribe una descripción que puedes corregir. Va por hash de contenido y se cachea, así que un archivo nunca se describe dos veces.
- **Planos.** La voz se corta en planos según sus pausas, igual que en el modo local. Claude elige qué recurso va en cada plano según lo que se dice ahí. Cualquier plano se puede fijar a mano.
- **Render rápido.** Se genera un clip por plano con ffmpeg (zoom lento en las imágenes y bucle en los videos cortos) y los clips se cachean. El acabado (subtítulos ASS, voz y música) se hace en una sola pasada de ffmpeg: ~25 s frente a ~8 min del acabado MoviePy clásico, que sigue disponible como opción.

- **Contenido creado en Flow o con la extensión, sin APIs de imagen.** En el paso **Escenas**, Claude agrupa las frases de la voz en escenas de unos 6–8 s y escribe para cada una el prompt de imagen y, si lo pides, el de video. Puedes descargar el `script.json` en el formato de la extensión "AI Content Generator", descargar `prompts.txt` o copiar los prompts uno a uno.

  Después generas el contenido tú mismo y en **Contenido** subes la carpeta de la extensión (`images/` y `videos/`), un ZIP o archivos sueltos. Cada archivo va a su escena según el número de su nombre (`1.png`, `scene_2.mp4`); si una escena tiene imagen y video, se usa el video. Al final revisas en **Ajuste** y montas el video.

  Con el CLI: `--asignacion escenas --generar imagenes_videos --hasta escenas --exportar-json ./carpeta/script.json`, y después `--proyecto <id> --contenido-dir ./carpeta`.
- **Edición editorial.** En el paso Video eliges el estilo *Clásico* o *Editorial*. El editorial aplica efectos sobrios de documental; cada uno se activa o desactiva por separado:
  - **Subtítulos palabra por palabra:** la palabra que suena se ilumina y la palabra clave de cada frase va en color.
  - **Rótulos:** cifras, fechas y nombres aparecen con una barra y un fundido.
  - **Sonido:** whoosh en los cortes, un golpe grave en las revelaciones y la música baja sola cuando habla la voz.
  - **Ritmo de entrada:** en los primeros 30 s hay cortes cada unos 3 s, alternando el encuadre de la misma imagen.
  - **Zoom** en las revelaciones.
  - **Color unificado:** cuatro tonos a elegir, con viñeta y grano fino.
  - **Gancho** sobreimpreso en los primeros 2 s.

  - **Efectos en momentos clave:** se aplican solo donde Claude marca un momento fuerte, y como mucho uno cada 20 s, para que no le quiten protagonismo al mensaje:
    - **Cita destacada:** la frase más potente aparece en grande sobre la imagen oscurecida y desenfocada.
    - **Pausa dramática:** tras un remate, la imagen se congela 1 s sin color.
    - **Destello** en las revelaciones.
    - **Blanco y negro cálido** en los tramos que narran otra época.

  Claude marca las palabras clave, los datos, las revelaciones y el gancho en una sola pasada (unos segundos). Esa pasada se guarda en caché, así que cambiar colores o volúmenes no vuelve a llamarlo. Todo se hace con ffmpeg y libass, sin Remotion.

  Puedes poner tus propios efectos de sonido en `MoneyPrinterTurbo/resource/sfx/whoosh.(wav|mp3)` y `golpe.(wav|mp3)`. Si no los hay, se generan solos.
- **Miniatura.** Es el último paso, aunque se puede abrir en cualquier momento; si ya tienes la miniatura, súbela desde el principio. Claude propone de 1 a 5 conceptos, cada uno con el texto de la miniatura y el prompt listo para Flow. Si quieres poner el texto tú, también da la versión sin texto, para Canva.

  Para proponerlos se basa en el guion, el estilo de Escenas, hasta 4 imágenes del proyecto y, si la subes, una **miniatura de referencia**, de la que copia el estilo y no el contenido. También indica qué imagen de escena conviene usar como referencia en Flow. Luego generas la miniatura, la subes, y queda como portada en Mis videos y lista para descargar. No usa APIs de imagen, solo Claude CLI (~1 min).
- **Voz clonada (opcional).** En el paso Voz puedes elegir "Voz clonada" en vez de las voces de Microsoft. La genera un servidor [Clonar-voz](https://github.com/jceronch1/Clonar-voz) (Qwen3-TTS con llama.cpp, en CPU o GPU) que puede estar en esta máquina o en otra, por ejemplo un PC con GPU. Se conecta con `estudio_voz_clonada_url` en `config.toml`. Desde el mismo panel grabas o subes 10–15 s de voz y queda en la biblioteca.

  El guion se pide por bloques de unas pocas frases que se guardan en caché. Por eso cambiar los planos o la velocidad, o reintentar tras un fallo, no vuelve a sintetizar lo que ya existe. Los tiempos de los subtítulos se reparten dentro de cada bloque por número de caracteres, con un desfase de ±0,5 s. En CPU tarda de 5 a 12 veces lo que dura el audio (medido en un i3 de 4 hilos); con GPU es casi al momento. Úsala solo con tu voz o con voces que tengan permiso.
- **Asistente** (la burbuja de abajo a la derecha): es un chat que responde con tu cuenta de Claude. Antes de cada pregunta recibe el estado del momento (proyecto abierto, etapas, errores, registro) y puede leer el código para explicar un error. No puede leer `config.toml` ni credenciales. Está en `app/services/estudio/asistente.py`.
- **Mis videos**: cada tarjeta tiene portada y las acciones Ver, Descargar, Editar, Duplicar, Renombrar y Borrar. Duplicar copia los ajustes y los recursos, pero no lo generado.

- **Prompts maestros** (menú superior). Es una biblioteca de estilos: subes cualquier prompt maestro (.docx, .txt, .md o texto pegado) y Claude lo desglosa en una ficha. La ficha recoge los pasos y lo que pregunta cada uno, lo que entrega, el formato y la duración, si trae narración, los idiomas, los bloques fijos, las reglas clave y cómo encaja en el Estudio. Se guarda en `storage/estudio/maestros/<id>/` con el texto original intacto y, si el .docx trae una imagen de ejemplo, esa imagen como portada. Puedes renombrarlo, añadir notas, poner tu propia portada, volver a desglosarlo o borrarlo.
- **Crear contenido** (botón en la ficha). Claude ejecuta el prompt maestro paso a paso, como en un chat, pero con botones: cada paso muestra sus opciones (la recomendada lleva estrella) y también puedes escribir libremente o pedir cambios. Si escribes el tema al empezar, se responde solo cuando el prompt lo pregunte. En modo **Automático** Claude elige la opción recomendada en cada paso hasta el final; se puede parar en cualquier momento. Al terminar, Claude ordena los **entregables**: el guion, las escenas con su prompt de imagen y de video, las miniaturas y los bloques. Se copian uno a uno o se descargan como `guion.txt`, prompts de imagen y de video en `.txt` (separados por línea en blanco) y `script.json` (el formato de la extensión de Flow). Cada creación queda en "Mis creaciones" de la ficha (`storage/estudio/maestros/<id>/creaciones/`). Convertir una creación en video del Estudio llegará en la siguiente fase.

Código: `MoneyPrinterTurbo/app/services/estudio/` (una etapa por archivo, el grafo está en `grafo.py`), `app/services/claude_cli.py` y `app/controllers/v1/estudio.py` (rutas `/api/v1/estudio/*`).

**Requisitos:**
- Claude Code instalado y con sesión iniciada (`claude` y después `/login`).
- `llm_provider` no hace falta cambiarlo: el Estudio siempre usa el CLI.
- Un ffmpeg con libass para el acabado rápido. Los de apt/Docker y el build de gyan.dev lo traen; si no está, se usa el clásico.

**Arrancar en local:**
```bash
cd MoneyPrinterTurbo && python main.py        # backend :8080
cd estudio-ui && npm install && npm run dev   # estudio  :3100
```

**CLI (para Hermes, n8n o cron):**
```bash
python estudio_cli.py --titulo "Mundial 2026" --material-archivo notas.txt \
    --recursos-dir ./mis_recursos --minutos 12 --out ./videos
python estudio_cli.py --titulo "X" --guion-archivo guion.txt --recursos-dir ./media   # tu guion tal cual
python estudio_cli.py --titulo "X" --material-archivo notas.txt --hasta guion         # parar para revisar en la web
python estudio_cli.py --proyecto <id> --musica ""                                      # seguir o retocar: solo rehace lo cambiado
```
Imprime `PROYECTO=<id>` al empezar y sale con código 0 si todo va bien y 1 si falla. Usa las mismas variables `MPT_API_BASE` y `MPT_BASIC_AUTH` que `zenn_cli.py`. Hay un perfil de ejemplo en `estudio_perfil.example.json`.

---

## CLI de automatización (`zenn_cli.py`)

Script de línea de comandos para generar videos **sin abrir el navegador**, ideal para
automatización, cron o que lo dispare otro agente/app (ej. **Hermes**, n8n). Usa el mismo
REST del backend, así que el resultado es idéntico al de la web. **Cubre las 3 formas de generar:**

| Modo | Qué hace | Costo |
|---|---|---|
| `--modo kie` (default) | Video estilo Zenn con imágenes generadas por IA (Kie AI) | 💰 **Gasta créditos de Kie por imagen** |
| `--modo local` | Video estilo Zenn con TUS imágenes (sube una carpeta, orden alfabético) | Gratis |
| `--modo video` | Video clásico con clips de Pexels / Pixabay / locales | Gratis |

> ⚠️ **El modo `kie` exige `--max-images N` obligatorio** (o `max_images` en el
> perfil): sin tope explícito el CLI se niega a ejecutar y falla con error, sin
> tocar la API. Es un seguro para que una automatización (agente IA, cron, n8n)
> no lance por accidente una generación sin límite que queme créditos. Si
> integras el CLI con un agente, dale la regla de nunca usar modo kie sin
> confirmación humana del tope.

### Requisitos

```bash
pip install requests        # única dependencia del CLI
```

### Configuración por entorno

```bash
# URL base de la API (default: el VPS público)
export MPT_API_BASE="https://virales.saraviamtech.com/api/mpt/v1"
# o local:  export MPT_API_BASE="http://localhost:8080/api/v1"

# Solo si activaste auth básica en Traefik
export MPT_BASIC_AUTH="usuario:password"
```

### Ejemplos

```bash
# 1) Kie AI con un guion propio y tope de imágenes (recomendado fijar max-images)
python zenn_cli.py --tema "Mundial 2026" --guion guion.txt --max-images 207 --out ./videos

# 2) Con un perfil guardado (voz, subtítulos, estilo, etc.) — ver perfil_zenn.example.json
python zenn_cli.py --perfil perfil_zenn.json --tema "Mundial 2026" --guion guion.txt

# 3) Imágenes locales: sube y ordena alfabéticamente la carpeta
python zenn_cli.py --modo local --tema "Mi video" --guion guion.txt --imagenes-dir ./mis_imagenes

# 4) Video clásico con clips de Pexels
python zenn_cli.py --modo video --tema "Datos del espacio" --fuente-clips pexels --terminos "space,stars"

# 5) Por lotes: un tema por línea, el backend genera cada guion
python zenn_cli.py --perfil perfil_zenn.json --lote temas.txt --parrafos 30 --out ./videos
```

### Perfil de configuración

Guarda tu combinación favorita (voz, subtítulos, estilo, etc.) en un JSON y reutilízala con
`--perfil`. Cualquier flag CLI **sobreescribe** lo que venga en el perfil. Plantilla completa
en [`perfil_zenn.example.json`](perfil_zenn.example.json). Cópiala a `perfil_zenn.json` y edítala.

### Controles disponibles (1:1 con la web)

`--voz`, `--voz-velocidad`, `--voz-volumen`, `--sin-voz`, `--musica` (`random`, `""` sin música,
o el nombre de un MP3 subido al servidor, ej. `micancion.mp3`), `--musica-volumen`,
`--sin-subtitulos`, `--sub-posicion` (`top|center|bottom|custom`), `--sub-posicion-pct`
(0-100, con `custom`), `--sub-fondo` / `--sub-sin-fondo` (caja/sombra detrás del texto),
`--sub-fondo-redondeado`, `--fuente`, `--tam-fuente`, `--color-texto`,
`--color-contorno`, `--grosor-contorno`, `--aspect`, `--codec`, `--tematica`, `--estilo`,
`--min-dur`, `--max-images`, `--idioma`, `--parrafos`, `--instrucciones`, `--capitulos`,
`--timeout`. Modo video además: `--fuente-clips`, `--terminos`, `--concat`, `--transicion`, `--dur-clip`.

Ver todo con `python zenn_cli.py --help`.

### Integración con Hermes (u otro agente)

El CLI imprime el progreso por stdout y termina con código `0` (éxito) o `1` (error), así que
cualquier orquestador lo invoca como un comando normal:

1. Prepara un `perfil_zenn.json` con tu configuración base.
2. Que Hermes ejecute el comando, p. ej.:
   `python zenn_cli.py --perfil perfil_zenn.json --tema "{{tema}}" --max-images 207 --out /ruta/salida`
3. El MP4 final queda en la carpeta `--out` con nombre `tema-slug-<taskid>.mp4`.
4. Para varios videos de una vez, usa `--lote temas.txt` (un tema por línea).

> El `--timeout` por defecto es 2 h (no se corta como el navegador a los 40 min). Si generas
> muchas imágenes con Kie, el render puede tardar bastante; el CLI espera hasta que termina.

---

## Despliegue en producción (VPS)

Guía completa en **[DEPLOY.md](DEPLOY.md)** (Portainer + Traefik + Docker Swarm).
Resumen: datos persistentes en `/root/mpt-data/` (`config.toml`, `storage/`,
`songs/`), imágenes construidas en el VPS, auth básica en Traefik. Para actualizar:
`git pull` + rebuild + `docker service update --force`; si cambió `docker-stack.yml`,
re-desplegar el stack.

---

## Variables de configuración importantes

| Parámetro | Descripción |
|---|---|
| `openai_api_key` | Clave de OpenAI para generación de guiones |
| `pexels_api_keys` | Array de keys de Pexels |
| `pixabay_api_keys` | Array de keys de Pixabay |
| `llm_provider` | Proveedor LLM: `openai`, `ollama`, `moonshot`, etc. |
| `openai_model_name` | Modelo a usar (default: `gpt-4o-mini`) |

---

## Licencia

El backend ([MoneyPrinterTurbo](https://github.com/harry0703/MoneyPrinterTurbo)) mantiene su licencia original MIT.  
La interfaz (`mpt-ui`) desarrollada por **SaraviaMtech** — uso libre con atribución.

---

*Desarrollado por [SaraviaMtech](https://github.com/juanelot)*
