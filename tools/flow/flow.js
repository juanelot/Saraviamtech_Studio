// Maneja la web de Google Flow en el Chrome dedicado para generar UNA imagen por llamada.
// Basado en srzGoogleFlowMCP (src/flow.js), con:
//   - "Proyecto nuevo" por el icono `add` (el MCP buscaba el texto "Nuevo proyecto").
//   - configure() reintenta la verificacion: el resumen a veces tarda en mostrar x1.
//   - exito / fallo por elementos (img[data-media-id], flow-pending-tile, flow-error-tile),
//     como la extension "AI Content Generator", no por mensajes traducidos.
// Nada depende del idioma de la web salvo el aviso de cuota/limite (textos.js).
import crypto from 'node:crypto';
import path from 'node:path';
import { chromium } from 'playwright-core';
import { CDP_PORT, FLOW_URL, ensureChrome } from './chrome.js';
import { esLimite } from './textos.js';

export const MODELS = {
  'pro': 'Nano Banana Pro',
  '2': 'Nano Banana 2.1',
  'lite': 'Nano Banana 2 Lite',
};
export const ASPECTS = ['16:9', '4:3', '1:1', '3:4', '9:16'];

const SELECT_ALL = process.platform === 'darwin' ? 'Meta+A' : 'Control+A';
const huella = (buf) => crypto.createHash('sha1').update(buf).digest('hex');
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

// Errores que no se arreglan reintentando la misma escena: paran el lote.
export class SinSesion extends Error {}
export class Limite extends Error {}
// "Detectamos actividad inusual": Google frena las peticiones seguidas; se espera un rato y se reintenta.
export class Inusual extends Error {}
const esInusual = (t) => /actividad inusual|unusual activity/i.test(t || '');

export async function conectar() {
  await ensureChrome();
  const browser = await chromium.connectOverCDP(`http://127.0.0.1:${CDP_PORT}`);
  const context = browser.contexts()[0];
  const page = context.pages().find((p) => p.url().startsWith(FLOW_URL)) || await context.newPage();
  return { browser, context, page };
}

function exigirSesion(page) {
  if (/accounts\.google\.com/.test(page.url())) {
    throw new SinSesion('No hay sesion de Google en el Chrome de Flow: pulsa "Conectar Flow" e inicia sesion.');
  }
}

// Botones y menus por su icono Material, que no se traduce.
const icon = (page, name) => page.locator('mat-icon', { hasText: new RegExp(`^\\s*${name}\\s*$`) });

// ¿Hay sesion? Abre la home y mira si aparece el boton de proyecto nuevo.
export async function comprobarSesion(page) {
  await page.goto(FLOW_URL, { waitUntil: 'domcontentloaded' });
  const nuevo = page.getByRole('button').filter({ has: icon(page, 'add') });
  for (let i = 0; i < 20; i++) {
    if (/accounts\.google\.com/.test(page.url())) return false;
    if (await nuevo.first().isVisible().catch(() => false)) return true;
    await page.waitForTimeout(750);
  }
  return false;
}

export async function nuevoProyecto(page) {
  await page.goto(FLOW_URL, { waitUntil: 'domcontentloaded' });
  exigirSesion(page);
  const nuevo = page.getByRole('button').filter({ has: icon(page, 'add') }).last();
  try {
    await nuevo.click({ timeout: 20000 });
  } catch {
    exigirSesion(page);
    // con sesion pero Flow lento o con un aviso encima: fallo normal (se reintenta), no "sin sesion"
    throw new Error('No aparece el boton de proyecto nuevo en Flow (¿pagina lenta?).');
  }
  await page.waitForURL(/\/project\/[0-9a-f-]{36}/, { timeout: 30000 });
  return page.url().match(/\/project\/([0-9a-f-]{36})/)[1];
}

export async function abrirProyecto(page, projectId) {
  const url = `${FLOW_URL}project/${projectId}`;
  if (!page.url().startsWith(url)) await page.goto(url, { waitUntil: 'domcontentloaded' });
  exigirSesion(page);
  await page.locator('div.ProseMirror').waitFor({ state: 'visible', timeout: 30000 });
  await cerrarMenus(page);
}

// Un menu abierto deja un fondo invisible que se traga todos los clics.
async function cerrarMenus(page) {
  const abierto = async () => (await page.locator('button.asset-item').first().isVisible().catch(() => false))
    || (await page.locator('.cdk-overlay-backdrop-showing, .cdk-overlay-container [role=menu]').count()) > 0;
  for (let i = 0; i < 5 && (await abierto()); i++) {
    await page.keyboard.press('Escape');
    await page.waitForTimeout(500);
  }
}

// "🍌 Nano Banana 2 Lite\ncrop_square\nx1" -> "Nano Banana 2 Lite"
function modelName(text) {
  return (text.match(/Nano Banana[^\n]*/) || [''])[0].trim();
}

const ICONO_ASPECTO = { '16:9': 'crop_16_9', '9:16': 'crop_9_16', '1:1': 'crop_square', '4:3': 'crop_landscape', '3:4': 'crop_portrait' };

function ajustesOk(resumen, { aspect, model }) {
  if (modelName(resumen) !== model || !/(^|\s)x1(\s|$)/.test(resumen)) return false;
  const ic = ICONO_ASPECTO[aspect];
  return !ic || !/crop_/.test(resumen) || resumen.includes(ic);
}

// Imagen, formato, x1 y modelo. Si ya estan puestos no toca nada.
export async function configurar(page, { aspect, model }) {
  model = MODELS[String(model).toLowerCase()] || model;
  const trigger = page.locator('button.settings-trigger-button');
  if (ajustesOk(await trigger.innerText().catch(() => ''), { aspect, model })) return;

  const agent = page.locator('flow-agent-mode-toggle-chip button');
  if (await agent.count() && (await agent.getAttribute('aria-pressed')) === 'true') await agent.click();

  for (let vuelta = 0; vuelta < 3; vuelta++) {
    const panel = page.locator('flow-prompt-box-settings');
    for (let i = 0; i < 4 && !(await panel.isVisible()); i++) {
      await trigger.click();
      await panel.waitFor({ state: 'visible', timeout: 2500 }).catch(() => {});
    }
    if (!(await panel.isVisible())) throw new Error('No se pudo abrir el panel de ajustes de Flow');

    await panel.getByRole('radiogroup').first().getByRole('radio').first().click(); // imagen (no video)
    await panel.getByRole('radio', { name: aspect, exact: true }).click();
    await panel.getByRole('radio', { name: 'x1', exact: true }).click();
    const modelBtn = panel.getByRole('button').filter({ hasText: 'Nano Banana' });
    if (modelName(await modelBtn.innerText()) !== model) {
      await modelBtn.click();
      await page.getByRole('menuitem').filter({ hasText: new RegExp(`${model.replace(/[.]/g, '\\.')}\\s*$`) }).click();
    }
    for (let i = 0; i < 4 && (await panel.isVisible()); i++) {
      await page.keyboard.press('Escape');
      await panel.waitFor({ state: 'hidden', timeout: 1500 }).catch(() => {});
    }
    // El resumen tarda un poco en reflejar los cambios: se mira varias veces.
    for (let i = 0; i < 4; i++) {
      await page.waitForTimeout(700);
      if (ajustesOk(await trigger.innerText().catch(() => ''), { aspect, model })) return;
    }
  }
  throw new Error(`Los ajustes de Flow no se aplicaron (muestra "${(await trigger.innerText()).replace(/\s+/g, ' ')}")`);
}

// ---------- estado de la cuadricula ----------

function cuadricula(page) {
  return page.evaluate(() => ({
    ids: [...document.querySelectorAll('img[data-media-id]')].map((i) => i.dataset.mediaId),
    pendientes: document.querySelectorAll('flow-pending-tile').length,
    errores: document.querySelectorAll('flow-error-tile').length,
    // Texto de las teselas de error y de los avisos (snackbar/banner) para detectar la cuota.
    textoErrores: [...document.querySelectorAll('flow-error-tile')].map((e) => e.innerText).join(' | '),
    avisos: [...document.querySelectorAll('[role=alert], [role=status], .mat-mdc-snack-bar-container, simple-snack-bar, flow-banner')]
      .map((e) => e.innerText).join(' | '),
  }));
}

// Sube cada imagen por "+ > Cargar contenido multimedia" y la agrega a la instruccion
// como ingrediente (chip encima del cuadro).
async function ponerReferencias(page, rutas) {
  const chips = page.locator('flow-ingredient-chip');
  for (const ruta of rutas) {
    const antes = await chips.count();
    const cargar = page.getByRole('button', { name: /Cargar contenido multimedia|Subir archivos multimedia|Upload media/i });
    if (!(await cargar.isVisible().catch(() => false))) {
      await page.locator('flow-add-menu button.add-menu-trigger').click();
      await cargar.waitFor({ state: 'visible', timeout: 10000 });
    }
    const [fc] = await Promise.all([page.waitForEvent('filechooser', { timeout: 10000 }), cargar.click()]);
    await fc.setFiles(ruta);
    // Tras subir queda seleccionada en el panel con el boton "Agregar a la instruccion".
    const agregar = page.getByRole('button', { name: /Agregar a la instrucci|A[ñn]adir a (la )?petici|Add to prompt/i });
    await agregar.waitFor({ state: 'visible', timeout: 60000 });
    await agregar.click();
    for (let i = 0; i < 40 && (await chips.count()) <= antes; i++) await page.waitForTimeout(500);
    if ((await chips.count()) <= antes) throw new Error(`Flow no agrego la imagen de referencia ${path.basename(ruta)}`);
    // el chip muestra la imagen cuando termina de subir
    await page.waitForFunction(() => ![...document.querySelectorAll('flow-ingredient-chip [aria-busy=true]')].length, null, { timeout: 60000 }).catch(() => {});
  }
}

async function escribirPrompt(page, texto, referencias = []) {
  await cerrarMenus(page);
  const clear = page.locator('div.top-right-actions button.clear-button');
  if (await clear.isVisible().catch(() => false)) {
    await clear.click();
    await page.waitForTimeout(800);
  }
  if (referencias.length) {
    await ponerReferencias(page, referencias);
    await cerrarMenus(page);
  }
  const editor = page.locator('div.ProseMirror');
  await editor.click();
  await page.keyboard.press(SELECT_ALL);
  await page.keyboard.press('Backspace');
  // insertText nunca abre el selector de "@"; una sola linea: Enter enviaria.
  await page.keyboard.insertText(texto.replace(/\s+/g, ' ').trim());
}

/**
 * Lanza UNA generacion y espera su imagen como la extension: hasta 80 x 1,5 s,
 * y "termino" = hay imagen nueva y 0 teselas pendientes durante 3 s.
 * referencias: rutas de imagenes que van como ingredientes (p. ej. foto -> caricatura).
 * Devuelve { buffer, tipo }. Lanza Limite, SinSesion o Error (fallo del intento).
 */
export async function generarUna(page, context, prompt, { sondeos = 80, cadaMs = 1500, estableMs = 3000, referencias = [] } = {}) {
  exigirSesion(page);
  await escribirPrompt(page, prompt, referencias);
  // despues de escribir: las referencias subidas tambien salen en la cuadricula
  await page.waitForTimeout(referencias.length ? 1500 : 0);
  const antes = await cuadricula(page);
  const vistos = new Set(antes.ids);
  // Las referencias nunca son el resultado. Si la misma foto se vuelve a subir, Flow reutiliza la anterior (el chip
  // lleva su id: /image/<id>) y ademas saca en la cuadricula una COPIA nueva, que llega antes que el dibujo: se
  // descartan por sus bytes, iguales a los de la referencia.
  const huellas = new Set();
  for (const src of await page.locator('flow-ingredient-chip img').evaluateAll((ims) => ims.map((i) => i.src))) {
    const m = src.match(/\/image\/([0-9a-f-]{36})/);
    if (m) vistos.add(m[1]);
    const r = await context.request.get(src).catch(() => null);
    if (r?.ok()) huellas.add(huella(await r.body()));
  }
  const submit = page.locator('flow-generate-icon-button button[type=submit]');
  await page.waitForFunction((el) => !el.disabled, await submit.elementHandle(), { timeout: 10000 });
  await submit.click();

  const nuevos = [];   // ids nuevos por orden de llegada
  let estableDesde = 0;
  for (let i = 0; i < sondeos; i++) {
    await page.waitForTimeout(cadaMs);
    exigirSesion(page);
    const ahora = await cuadricula(page);
    const avisoNuevo = ahora.avisos !== antes.avisos ? ahora.avisos : '';
    if (esLimite(avisoNuevo) || esLimite(ahora.textoErrores)) {
      throw new Limite(`Flow avisa de limite/cuota: ${(avisoNuevo || ahora.textoErrores).replace(/\s+/g, ' ').slice(0, 200)}`);
    }
    if (ahora.errores > antes.errores && !ahora.pendientes) {
      const motivo = ahora.textoErrores.replace(/\s+/g, ' ').trim().slice(0, 200);
      throw new Error(`Flow no pudo generar la imagen${motivo ? `: ${motivo}` : ''}`);
    }
    for (const id of ahora.ids) if (!vistos.has(id) && !nuevos.includes(id)) nuevos.push(id);
    if (nuevos.length && !ahora.pendientes) {
      estableDesde = estableDesde || Date.now();
      if (Date.now() - estableDesde >= estableMs) break;
    } else {
      estableDesde = 0;
    }
  }
  // la ultima en llegar que no sea copia de una referencia
  for (const id of nuevos.reverse()) {
    const src = await page.locator(`img[data-media-id="${id}"]`).first().getAttribute('src');
    const res = await context.request.get(src);
    if (!res.ok()) throw new Error(`Fallo la descarga (${res.status()}) de la imagen ${id}`);
    const buffer = await res.body();
    if (huellas.has(huella(buffer))) continue;
    const ct = res.headers()['content-type'] || '';
    const tipo = ct.includes('png') ? 'png' : ct.includes('webp') ? 'webp' : 'jpeg';
    return { buffer, tipo, mediaId: id };
  }
  throw new Error(`No aparecio ninguna imagen nueva en ${Math.round((sondeos * cadaMs) / 1000)} s`);
}

// ---------- video (Veo) ----------

export const VIDEO_MODELS = { 'lite': 'Veo 3.1 - Lite', 'fast': 'Veo 3.1 - Fast', 'quality': 'Veo 3.1 - Quality' };
export const COSTE_VIDEO = 10;   // creditos de un clip de Veo 3.1 Lite (lo dice Flow al elegirlo)

// Creditos que le quedan a la cuenta y su correo, del menu de la cuenta (arriba a la derecha).
// "40 créditos de Google Flow" / "40 Google Flow credits". Devuelve {creditos: n|null, email}.
export async function creditos(page) {
  const boton = page.locator('.header-user-button').first();
  await boton.waitFor({ state: 'visible', timeout: 20000 });
  await boton.click();
  let texto = '';
  for (let i = 0; i < 12; i++) {
    await page.waitForTimeout(500);
    texto = await page.evaluate(() => [...document.querySelectorAll('.cdk-overlay-container')].map((e) => e.innerText).join(' '));
    if (/\d+\s*(cr[eé]ditos|credits|puntos|points)/i.test(texto)) break;
  }
  await page.keyboard.press('Escape');
  await cerrarMenus(page);
  const m = texto.match(/(\d[\d.,]*)\s*(cr[eé]ditos|credits|puntos|points)/i);
  const email = (texto.match(/[\w.+-]+@[\w-]+\.[\w.]+/) || [null])[0];
  return { creditos: m ? Number(m[1].replace(/[.,]/g, '')) : null, email };
}

function ajustesVideoOk(resumen, aspect) {
  return /^\s*V[ií]deo(\s|·|$)/i.test(resumen)   // "Vídeo" en cuentas de España && /(^|\s)x1(\s|$)/.test(resumen) && resumen.includes(ICONO_ASPECTO[aspect] || '');
}

// Video, Fotogramas (cuadro inicial), formato, x1 y modelo de Veo.
export async function configurarVideo(page, { aspect, model = 'lite' }) {
  model = VIDEO_MODELS[String(model).toLowerCase()] || model;
  const trigger = page.locator('button.settings-trigger-button');
  const agent = page.locator('flow-agent-mode-toggle-chip button');
  if (await agent.count() && (await agent.getAttribute('aria-pressed')) === 'true') await agent.click();
  for (let vuelta = 0; vuelta < 3; vuelta++) {
    const panel = page.locator('flow-prompt-box-settings');
    for (let i = 0; i < 4 && !(await panel.isVisible()); i++) {
      await trigger.click();
      await panel.waitFor({ state: 'visible', timeout: 2500 }).catch(() => {});
    }
    if (!(await panel.isVisible())) throw new Error('No se pudo abrir el panel de ajustes de Flow');
    await panel.getByRole('radiogroup').first().getByRole('radio').nth(1).click();   // video
    await page.waitForTimeout(600);
    await panel.getByRole('radio').filter({ has: icon(page, 'crop_free') }).click();   // Fotogramas
    await panel.getByRole('radio').filter({ has: icon(page, ICONO_ASPECTO[aspect]) }).click();
    await panel.getByRole('radio', { name: 'x1', exact: true }).click();
    const modelBtn = panel.getByRole('button').filter({ hasText: /Veo|Omni/ });
    if (!(await modelBtn.innerText()).includes(model)) {
      await modelBtn.click();
      await page.getByRole('menuitem').filter({ hasText: model }).first().click();
    }
    for (let i = 0; i < 4 && (await panel.isVisible()); i++) {
      await page.keyboard.press('Escape');
      await panel.waitFor({ state: 'hidden', timeout: 1500 }).catch(() => {});
    }
    for (let i = 0; i < 4; i++) {
      await page.waitForTimeout(700);
      if (ajustesVideoOk(await trigger.innerText().catch(() => ''), aspect)) return;
    }
  }
  throw new Error(`Los ajustes de video de Flow no se aplicaron (muestra "${(await trigger.innerText()).replace(/\s+/g, ' ')}")`);
}

// El cuadro inicial: chip "Iniciar" > Cargar contenido multimedia > Agregar a la instruccion.
async function ponerInicio(page, ruta) {
  const chip = page.locator('flow-ingredient-bar button.empty-chip').first();
  await chip.waitFor({ state: 'visible', timeout: 15000 });
  await chip.click();
  const cargar = page.locator('flow-add-menu-popover-content span.upload-text').first();
  await cargar.waitFor({ state: 'visible', timeout: 10000 });
  const [fc] = await Promise.all([page.waitForEvent('filechooser', { timeout: 10000 }), cargar.click()]);
  await fc.setFiles(ruta);
  const agregar = page.getByRole('button', { name: /Agregar a la instrucci|A[ñn]adir a (la )?petici|Add to prompt/i });
  await agregar.waitFor({ state: 'visible', timeout: 60000 });
  await agregar.click();
  await page.locator('flow-ingredient-bar flow-image-ingredient-chip').first().waitFor({ state: 'visible', timeout: 30000 });
  await page.waitForFunction(() => ![...document.querySelectorAll('flow-ingredient-bar [aria-busy=true]')].length, null, { timeout: 60000 }).catch(() => {});
  await cerrarMenus(page);
}

const videosEnPagina = (page) => page.evaluate(() => ({
  // cada clip por su miniatura o su video (en algunas cuentas el <video> solo aparece al pasar el raton)
  srcs: [...document.querySelectorAll('flow-video-tile')].map((t) => {
    const v = t.querySelector('video');
    const i = t.querySelector('img');
    return (v && (v.currentSrc || v.src)) || (i && i.src) || '';
  }).filter(Boolean),
  pendientes: document.querySelectorAll('flow-pending-tile').length,
  errores: document.querySelectorAll('flow-error-tile').length,
  textoErrores: [...document.querySelectorAll('flow-error-tile')].map((e) => e.innerText).join(' | '),
  avisos: [...document.querySelectorAll('[role=alert], [role=status], .mat-mdc-snack-bar-container, simple-snack-bar, flow-banner')]
    .map((e) => e.innerText).join(' | '),
}));

/**
 * UN clip de Veo desde un cuadro inicial (inicio = ruta de imagen). Tarda ~4 min: se mira cada 3 s hasta 12 min.
 * Se usa siempre en un proyecto recien abierto (cuadro inicial vacio). Devuelve { buffer } (mp4).
 * Lanza Limite, SinSesion o Error.
 */
export async function generarVideo(page, context, prompt, { inicio, sondeos = 240, cadaMs = 3000 } = {}) {
  exigirSesion(page);
  await cerrarMenus(page);
  const clear = page.locator('div.top-right-actions button.clear-button');
  if (await clear.isVisible().catch(() => false)) {
    await clear.click();
    await page.waitForTimeout(800);
  }
  if (inicio) await ponerInicio(page, inicio);
  const editor = page.locator('div.ProseMirror');
  await editor.click();
  await page.keyboard.press(SELECT_ALL);
  await page.keyboard.press('Backspace');
  await page.keyboard.insertText(prompt.replace(/\s+/g, ' ').trim());
  const antes = await videosEnPagina(page);
  const vistos = new Set(antes.srcs);
  const submit = page.locator('flow-generate-icon-button button[type=submit]');
  await page.waitForFunction((el) => !el.disabled, await submit.elementHandle(), { timeout: 10000 });
  await submit.click();
  let vioPendiente = false;
  for (let i = 0; i < sondeos; i++) {
    await page.waitForTimeout(cadaMs);
    exigirSesion(page);
    const ahora = await videosEnPagina(page);
    const avisoNuevo = ahora.avisos !== antes.avisos ? ahora.avisos : '';
    if (esLimite(avisoNuevo) || esLimite(ahora.textoErrores)) {
      throw new Limite(`Flow avisa de limite/creditos: ${(avisoNuevo || ahora.textoErrores).replace(/\s+/g, ' ').slice(0, 200)}`);
    }
    if (ahora.errores > antes.errores && !ahora.pendientes) {
      const motivo = ahora.textoErrores.replace(/\s+/g, ' ').trim().slice(0, 200);
      if (esInusual(motivo) || esInusual(avisoNuevo)) throw new Inusual('Flow detecto actividad inusual (peticiones seguidas)');
      throw new Error(`Flow no pudo generar el video${motivo ? `: ${motivo}` : ''}`);
    }
    vioPendiente = vioPendiente || ahora.pendientes > 0;
    const k = ahora.srcs.findIndex((s) => !vistos.has(s));
    if (k >= 0 && !ahora.pendientes) {
      // el video de esa tesela: si solo hay miniatura, se pasa el raton para que Flow ponga el <video>
      const tesela = page.locator('flow-video-tile').nth(k);
      let src = await tesela.evaluate((t) => { const v = t.querySelector('video'); return v && (v.currentSrc || v.src); });
      for (let j = 0; j < 5 && !src; j++) {
        await tesela.hover().catch(() => {});
        await page.waitForTimeout(1500);
        src = await tesela.evaluate((t) => { const v = t.querySelector('video'); return v && (v.currentSrc || v.src); });
      }
      if (!src) throw new Error('Flow hizo el video pero no se pudo leer su enlace');
      const res = await context.request.get(src, { timeout: 120000 });
      if (!res.ok()) throw new Error(`Fallo la descarga (${res.status()}) del video`);
      return { buffer: await res.body() };
    }
    if (i === 10 && !vioPendiente) throw new Error('Flow no empezo a generar el video (¿sin creditos?)');
  }
  throw new Error(`No aparecio el video en ${Math.round((sondeos * cadaMs) / 60000)} min`);
}

export { sleep };
