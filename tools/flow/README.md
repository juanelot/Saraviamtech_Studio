# Generador de Google Flow (solo local)

Genera en Google Flow (Nano Banana, gratis) la imagen de cada escena del Estudio y la deja en
`recursos/images/scene_NNNN.<ext>` del proyecto. Basado en srzGoogleFlowMCP. No va en el VPS.

## Instalar en una máquina
1. Node 18+ y Google Chrome.
2. `npm install` en esta carpeta.
3. En `MoneyPrinterTurbo/config.toml`: `estudio_flow_habilitado = true`.
4. Reiniciar el backend. En el Estudio, paso **Contenido** → **Conectar Flow** → iniciar sesión
   con la cuenta de Google en el Chrome que se abre (perfil `%LOCALAPPDATA%\FlowImageChrome`). Solo una vez.

## Uso directo (sin el Estudio)
```
node lote.js --script script.json --out carpeta/images --aspect 9:16 --model 2 [--solo 3,7] [--pasadas-extra 2] [--detener ruta/.detener]
node cli.js chrome    # abrir el Chrome de Flow
node cli.js sesion    # {"chrome","sesion","ocupado"}
```
Salta las escenas que ya tienen imagen; 4 intentos por escena; repasa las fallidas al final;
se pausa si Flow avisa de límite (frases en `textos.js`). Crear el archivo de `--detener` para
parar tras la imagen en curso.
