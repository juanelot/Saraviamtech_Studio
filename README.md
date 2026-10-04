# Saraviamtech Studio

Estudio de creación de video con IA desarrollado por **[Saraviamtech](https://github.com/juanelot)**.
Va del tema o el guion al video final montado, con voz, escenas y prompts para Google Flow, subtítulos animados, edición con efectos y miniatura.

Claude hace todo el trabajo de texto e imagen a través de **Claude CLI**, con tu suscripción de Claude y sin API key. El montaje se hace con ffmpeg en tu máquina o en tu VPS.

---

## Índice

1. [Cómo se trabaja: los pasos](#cómo-se-trabaja-los-pasos)
2. [Funciones](#funciones)
3. [Conexión con Claude CLI (local y VPS)](#conexión-con-claude-cli)
4. [Instalación local](#instalación-local)
5. [Despliegue en VPS](#despliegue-en-vps)
6. [Automatización por terminal](#automatización-por-terminal)
7. [Estructura del proyecto](#estructura-del-proyecto)

---

## Cómo se trabaja: los pasos

Cada video es un **proyecto** que avanza por pasos. Puedes ir en orden o volver a cualquier paso: solo se rehace lo que depende de lo que cambiaste.

| Paso | Qué haces | Quién trabaja |
|---|---|---|
| **Material** | Pegas el tema, notas o fuentes; eliges la duración (hasta 3 h) y el idioma. | Tú |
| **Guion** | Claude redacta la locución, o pegas tu guion tal cual. | Claude CLI |
| **Voz** | Voces de Microsoft, voz clonada o tu propio audio ("Mi audio"). | TTS / Whisper |
| **Escenas** | Eliges el formato (16:9, 9:16 o 1:1) y el estilo; Claude corta el guion en escenas y escribe el prompt de imagen (y de video) de cada una. | Claude CLI |
| **Contenido** | Subes lo que generaste en Flow, la carpeta de la extensión, un ZIP o tus propios recursos. | Tú |
| **Ajuste** | Revisas qué imagen o clip va en cada plano y fijas a mano lo que quieras. | Claude CLI / tú |
| **Video** | Eliges el estilo de edición (Clásico, Editorial o Intenso) y la música, y montas el video. | ffmpeg |
| **Miniatura** | Claude propone conceptos y prompts para la miniatura; subes la final. | Claude CLI |

```
material → guion → voz → escenas + prompts ─┐   ← contenido creado por ti en Flow / extensión
                    recursos (tus archivos) ─┴→ ajuste → video → miniatura
```

**Por etapas y con firma.** Cada etapa guarda la firma de sus entradas. Por ejemplo, otra música solo rehace el acabado, fijar un plano rehace ese clip y editar el guion rehace la voz y lo que viene después. Las respuestas de Claude se guardan en caché, así que repetir un paso sin cambios no lo vuelve a llamar.

---

## Funciones

### Guion
- Claude lo redacta a partir de tu material, con la duración pedida (de segundos a 3 horas). Si sale corto, hace una segunda pasada para ampliarlo.
- También puedes pegar tu propio guion y se usa tal cual.

### Voz
- **Microsoft:** más de 300 voces neuronales en muchos idiomas, con el tiempo exacto de cada palabra.
- **Voz clonada:** el Estudio se conecta a un servidor [Clonar-voz](https://github.com/jceronch1/Clonar-voz) (Qwen3-TTS) que puede estar en esta máquina o en otra con GPU, configurado en `estudio_voz_clonada_url`. Desde el panel grabas o subes 10–15 s de voz y queda en la biblioteca.
- **Mi audio:** subes una narración ya grabada (tu voz, o la que hiciste con Clonar-voz) en WAV, MP3, M4A, OGG o FLAC, y se sincroniza sola.
  - Whisper saca el tiempo de cada palabra; si el guion coincide con lo que se oye, los subtítulos usan el texto del guion.
  - Tarda unos 8 s por minuto de audio en CPU (14,5 min en menos de 2 min).
- La narración se corta en **planos** según sus pausas; cada plano lleva una imagen o clip.

### Escenas y prompts para Flow
- **Formato:** se elige aquí y es el mismo para las imágenes y para el video final (16:9 por defecto). Se le pasa a Claude en todos los lotes, sin excepción.
- Claude agrupa las frases en escenas de la duración que elijas y escribe para cada una:
  - un **prompt de imagen**, que describe una imagen fija, sin movimiento, cámara ni tiempos;
  - y, si lo pides, un **prompt de video** (image-to-video), que es donde va el movimiento.
- Todos los lotes reciben el mismo contexto: guion completo, estilo visual, indicaciones (personajes fijos, época…), formato e idioma, más las últimas escenas ya escritas para mantener la continuidad.
- **La narración de cada escena es el texto exacto del guion, con su puntuación.** Se corta en código; Claude no la reescribe.
- **Validación automática** antes de guardar:
  - el formato es correcto (en 16:9 ningún prompt dice "9:16", "vertical" ni "portrait", y al revés);
  - la narración unida es idéntica al guion;
  - las imágenes no describen movimiento;
  - las escenas son consecutivas.

  Las escenas que fallan se rehacen solas; si alguna sigue fallando, aparece un aviso con su número.
- Puedes descargar `script.json` (formato de la extensión "AI Content Generator") o `prompts.txt`, copiar los prompts y corregir cualquiera a mano.

### Contenido y ajuste
- Subes la carpeta de la extensión (`images/` y `videos/`), un ZIP o archivos sueltos. Cada archivo va a su escena por el número de su nombre (`1.png`, `scene_2.mp4`); si una escena tiene imagen y video, se usa el video.
- **Con tus propios recursos** (sin escenas), Claude mira una miniatura de cada imagen o video, lo describe y elige qué recurso va en cada plano. Cualquier plano se puede fijar a mano.
- El botón **último fotograma** saca el último cuadro de un clip para encadenar segmentos en Flow.

### Video: montaje y estilos de edición
El montaje se hace con ffmpeg: un clip por plano, en caché, y el acabado (voz, música y subtítulos) en una sola pasada. Hay tres estilos:

- **Clásico:** subtítulos por frase, sin efectos.
- **Editorial:** efectos sobrios de documental, cada uno activable por separado:
  - subtítulos palabra por palabra con la palabra clave en color;
  - rótulos de cifras, fechas y nombres;
  - whoosh en los cortes, golpe grave en las revelaciones y música que baja sola bajo la voz;
  - ritmo de entrada y zoom en las revelaciones;
  - color unificado (natural, cálido, cine o frío) y gancho en los primeros 2 s;
  - momentos clave, como mucho uno cada 20 s: cita destacada, pausa dramática, destello y blanco y negro para el pasado.
- **Intenso:** el estilo para redes, lleno de efectos. Usa lo mismo que el editorial con más densidad y añade:
  - subtítulos en mayúsculas en los que crece la palabra que suena;
  - la palabra clave gigante con temblor y desfase de color en las revelaciones;
  - flash en los cambios de imagen;
  - barra de progreso;
  - franjas de cine en las citas;
  - un "pop" en los rótulos y una subida de tensión antes de cada revelación.

Claude marca las palabras clave, los datos y los momentos fuertes en una sola pasada y siempre escribe esos textos en el idioma de la narración. Puedes poner tus propios efectos de sonido en `MoneyPrinterTurbo/resource/sfx/` (`whoosh`, `golpe`); si no los hay, se generan solos.

### Miniatura
- Claude propone de 1 a 5 conceptos, cada uno con su texto y el prompt para Flow, con y sin texto (para Canva).
- Se basa en el guion, el estilo, las imágenes del proyecto y, si la subes, una miniatura de referencia (copia el estilo, no el contenido).
- La miniatura final queda como portada en Mis videos.

### Prompts maestros, creaciones y series
- **Biblioteca de prompts maestros** (menú superior): subes un prompt maestro (.docx, .txt, .md o texto) y Claude lo desglosa en una ficha con sus pasos, preguntas, entregables, formato y reglas.
- **Crear contenido:** Claude ejecuta el maestro paso a paso con botones, o en modo automático. Al final ordena los entregables: guion, escenas con sus prompts, miniaturas y `script.json`.
- **Hojas de referencia** de personajes y lugares, **series** con biblia compartida y episodios.
- **Crear video:** convierte una creación en un proyecto del Estudio ya relleno, con cuatro opciones de narración: su guion, guion demostración, guion libre o sin voz.

### Asistente y Mis videos
- **Asistente** (la burbuja de abajo a la derecha): un chat con tu cuenta de Claude que ve el estado del proyecto y puede leer el código para explicar un error. No puede leer `config.toml` ni credenciales.
- **Mis videos:** cada tarjeta tiene portada y las acciones Ver, Descargar, Editar, Duplicar, Renombrar y Borrar.

---

## Conexión con Claude CLI

### Cómo funciona

El Estudio **no usa la API de Anthropic ni una API key**. Cada vez que necesita a Claude (guion, escenas, catálogo visual, asignación, edición, miniatura, prompts maestros, asistente), el backend lanza el programa **Claude Code** en modo no interactivo:

```
claude -p --model <haiku|sonnet|opus> --effort <low|medium|high> --output-format json
```

- La instrucción va por la entrada estándar y la respuesta vuelve en JSON.
- Usa la **sesión de tu cuenta de Claude** (Pro o Max) guardada en la máquina donde corre el backend, así que el consumo cuenta contra tu suscripción.
- Para que nunca salga de la suscripción, el backend quita del proceso hijo `ANTHROPIC_API_KEY`, `ANTHROPIC_AUTH_TOKEN`, `ANTHROPIC_BASE_URL` y las variables de Bedrock/Vertex. Aunque tengas una API key en el sistema, no se usa.
- Por seguridad se lanza sin MCP (`--strict-mcp-config`) y con las herramientas desactivadas. Solo se permite `Read`, dentro de la carpeta del proyecto, cuando Claude tiene que mirar imágenes.
- El modelo y el esfuerzo se eligen en cada paso de la interfaz. `low` es lo más rápido; `medium` y `high` piensan más y tardan más.

Código: `MoneyPrinterTurbo/app/services/claude_cli.py`.

### En local (Windows, macOS o Linux)

1. **Instala Claude Code** en la misma máquina donde corre el backend.

   ```powershell
   # Windows (PowerShell)
   irm https://claude.ai/install.ps1 | iex
   ```
   ```bash
   # macOS / Linux
   curl -fsSL https://claude.ai/install.sh | bash
   ```
   También sirve `npm install -g @anthropic-ai/claude-code`.

2. **Inicia sesión** con tu cuenta de Claude: ejecuta `claude`, escribe `/login`, elige *Claude account (Pro/Max)* y completa el login en el navegador. La sesión queda guardada en tu usuario (`%USERPROFILE%\.claude` en Windows, `~/.claude` en macOS/Linux).

3. **Comprueba que responde** sin abrir el modo interactivo:

   ```bash
   claude -p "responde solo: ok" --model haiku
   ```
   Si contesta `ok`, el Estudio ya puede usarlo.

4. **Arranca el backend con el mismo usuario** con el que hiciste el login. El backend busca `claude` en el PATH. Si lo arrancas desde otro sitio (un servicio, una tarea programada o un PATH distinto) y no lo encuentra, pon la ruta completa en `config.toml`:

   ```toml
   [app]
   claude_cli_path = "C:/Users/<tu-usuario>/.local/bin/claude.exe"   # Windows (instalador nativo)
   # claude_cli_path = "/home/<usuario>/.local/bin/claude"            # Linux
   ```

### En el VPS (Docker Swarm)

La imagen del backend (`MoneyPrinterTurbo/Dockerfile`) ya instala Claude Code. Solo falta darle una sesión, que se guarda fuera del contenedor para que no se pierda al actualizar.

1. **Volumen de sesión.** Ya está en `docker-stack.yml`, en el servicio `api`:

   ```yaml
   volumes:
     - /root/mpt-data/claude:/root/.claude
   environment:
     - CLAUDE_CONFIG_DIR=/root/.claude
   ```
   Crea la carpeta una vez: `mkdir -p /root/mpt-data/claude`.

2. **Inicia sesión**, una sola vez. Elige una de estas dos formas:

   - **A. Login dentro del contenedor:**
     ```bash
     docker exec -it $(docker ps -qf name=mpt_api) claude
     # dentro: /login → elige "Claude account" → abre la URL en tu navegador,
     # autoriza y pega el código que te da. Sal con /exit.
     ```
     La sesión queda en `/root/mpt-data/claude` y sobrevive a reinicios y actualizaciones.

   - **B. Token de larga duración**, sin login interactivo:
     ```bash
     # En tu PC (con sesión iniciada):
     claude setup-token
     # Copia el token (sk-ant-oat01-...)
     ```
     En Portainer, añade al servicio `api` la variable `CLAUDE_CODE_OAUTH_TOKEN=sk-ant-oat01-...` y vuelve a desplegar el stack. Trata ese token como una contraseña.

3. **Comprueba** desde el VPS:

   ```bash
   docker exec -it $(docker ps -qf name=mpt_api) claude -p "responde solo: ok" --model haiku
   ```

### Ajustes en `config.toml`

```toml
[app]
claude_cli_model = "sonnet"   # por defecto cuando un paso no indica modelo: haiku | sonnet | opus
claude_cli_effort = "low"     # low | medium | high | xhigh | max
claude_cli_timeout = 0        # segundos; 0 = automático según modelo y esfuerzo
claude_cli_path = ""          # vacío = buscar `claude` en el PATH
```

### Problemas frecuentes

| Mensaje | Causa | Solución |
|---|---|---|
| `no se encontro el CLI claude` | Claude Code no está instalado o no está en el PATH del backend | Instálalo o pon `claude_cli_path` |
| `Not logged in` / `Please run /login` | No hay sesión, o expiró | Repite el login (local: `claude` → `/login`; VPS: forma A o B) |
| `cupo de la suscripcion agotado` | Llegaste al límite de uso de tu plan | Espera a que se renueve y vuelve a lanzar el paso. Las etapas ya terminadas no se repiten |
| `sin respuesta en N s` | Tarea muy larga con esfuerzo alto | Baja el esfuerzo a `low` o `medium`, o sube `claude_cli_timeout` |
| La sesión desaparece al actualizar el VPS | Falta el volumen `/root/mpt-data/claude` | Revisa el volumen y `CLAUDE_CONFIG_DIR` en `docker-stack.yml` |

---

## Instalación local

### Requisitos
- Python 3.10 o superior, y Node.js 18 o superior.
- **ffmpeg con libass** en el PATH. El build de gyan.dev en Windows y el de apt o Docker en Linux lo traen.
- **Claude Code** con sesión iniciada (ver [Conexión con Claude CLI](#conexión-con-claude-cli)).
- **Git LFS**, porque la música y las fuentes van por LFS: `git lfs install` antes de clonar.

### Pasos

```bash
git clone https://github.com/juanelot/Saraviamtech_Studio.git
cd Saraviamtech_Studio

# Backend (motor + API del Estudio) → http://localhost:8080
cd MoneyPrinterTurbo
python -m venv .venv
.venv\Scripts\activate            # Windows  (macOS/Linux: source .venv/bin/activate)
pip install -r requirements.txt
cp config.example.toml config.toml
python main.py

# Estudio (otra terminal) → http://localhost:3100
cd estudio-ui
npm install
npm run dev
```

Opciones del Estudio en `config.toml` (`[app]`):

```toml
estudio_carpetas_permitidas = []   # carpetas del servidor que el Estudio puede leer como recursos
estudio_voz_clonada_url = ""       # URL del servidor Clonar-voz (vacío = solo voces de Microsoft)
```

La primera vez que uses **Mi audio**, Whisper descarga su modelo (unos 150 MB). Hace falta internet solo esa vez.

> El backend no recarga el código solo: después de actualizar, reinicia `python main.py`.

---

## Despliegue en VPS

La guía completa está en **[DEPLOY.md](DEPLOY.md)** (Portainer + Traefik + Docker Swarm). Resumen del Estudio:

```bash
mkdir -p /root/mpt-data/claude /root/mpt-data/recursos
docker build -t mpt-api:latest ./MoneyPrinterTurbo
docker build -t estudio-ui:latest --build-arg MPT_API_URL=http://api:8080 ./estudio-ui
docker stack deploy -c docker-stack.yml mpt
```

- **Dominio:** `estudio.saraviamtech.com` (label `Host(...)` del servicio `estudio`), con auth básica de Traefik.
- **Sesión de Claude:** ver [En el VPS](#en-el-vps-docker-swarm).
- **Datos persistentes:** proyectos en `/root/mpt-data/storage/estudio/`, recursos del servidor en `/root/mpt-data/recursos` (dentro del contenedor, `/recursos`).
- **Actualizar:** `git pull`, reconstruir las dos imágenes y luego `docker service update --force mpt_api` y `docker service update --force mpt_estudio`.

---

## Automatización por terminal

Dos CLIs para que Hermes, n8n o un cron trabajen sin abrir el navegador. Usan la API del Estudio:

```bash
# Contra el VPS (por defecto): https://estudio.saraviamtech.com/api/motor
export MPT_BASIC_AUTH="usuario:password"          # la auth básica de Traefik
# En local:
export MPT_API_BASE="http://localhost:8080/api/v1"
```

**`estudio_cli.py`** crea o continúa proyectos:

```bash
python estudio_cli.py --titulo "Rockefeller" --material-archivo notas.txt --minutos 12 \
    --recursos-dir ./mis_recursos --formato 16:9 --out ./videos
python estudio_cli.py --titulo "X" --guion-archivo guion.txt --asignacion escenas \
    --generar imagenes --hasta escenas --exportar-json ./flow/script.json
python estudio_cli.py --proyecto <id> --contenido-dir ./flow --out ./videos   # sube lo de Flow y monta
```

Imprime `PROYECTO=<id>` al empezar y sale con código 0 si todo va bien y 1 si falla. Hay un perfil de ejemplo en `estudio_perfil.example.json`.

**`maestros_cli.py`** trabaja con los prompts maestros:

```bash
python maestros_cli.py listar
python maestros_cli.py crear --maestro "paper craft" --tema "un faro en una isla" --sin-paradas --out ./flow/faro
python maestros_cli.py video --maestro "paper craft" --creacion <id> --narracion demostracion
```

Sale con código 0 si está listo, 1 si hay un error y 2 si el flujo espera una respuesta (contéstala con `responder`).

---

## Estructura del proyecto

```
Saraviamtech_Studio/
├── estudio-ui/                     # Interfaz del Estudio (Next.js 16, puerto 3100)
│   ├── app/                        # Páginas: inicio, proyecto (/p/<id>), maestros
│   ├── components/paneles/         # Un panel por paso (Guion, Voz, Escenas, Video…)
│   └── lib/                        # API, marca (marca.ts), voces
├── MoneyPrinterTurbo/              # Backend (FastAPI, puerto 8080): motor de video + API
│   ├── app/services/estudio/       # Una etapa por archivo; el grafo de etapas en grafo.py
│   ├── app/services/claude_cli.py  # Conexión con Claude CLI
│   ├── app/controllers/v1/estudio.py   # Rutas /api/v1/estudio/*
│   ├── storage/estudio/            # Proyectos, maestros, catálogo
│   └── config.toml
├── estudio_cli.py · maestros_cli.py    # Automatización por terminal
├── docker-stack.yml · DEPLOY.md        # Despliegue en VPS
```

---

## Licencia

© Saraviamtech. Todos los derechos reservados sobre el Estudio, sus interfaces y la marca.
Incluye componentes de código abierto bajo licencia MIT; sus avisos están en `MoneyPrinterTurbo/LICENSE`.

---

*Desarrollado por [Saraviamtech](https://github.com/juanelot)*
