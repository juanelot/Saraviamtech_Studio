// Finds and launches a dedicated Chrome (separate user-data-dir, remote debugging on
// localhost) that stays signed in to Flow. Chrome is started normally and detached, so it
// keeps running after this process exits; Playwright only attaches to it over CDP.
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import { spawn } from 'node:child_process';
import { fileURLToPath } from 'node:url';

export const CDP_PORT = Number(process.env.FLOW_CDP_PORT || 9333);
export const FLOW_URL = 'https://flow.google.com/';

const isWin = process.platform === 'win32';
const isMac = process.platform === 'darwin';

export function chromePath() {
  if (process.env.FLOW_CHROME_PATH) return process.env.FLOW_CHROME_PATH;
  const candidates = isWin
    ? [
        path.join(process.env.PROGRAMFILES || 'C:/Program Files', 'Google/Chrome/Application/chrome.exe'),
        path.join(process.env['PROGRAMFILES(X86)'] || 'C:/Program Files (x86)', 'Google/Chrome/Application/chrome.exe'),
        path.join(process.env.LOCALAPPDATA || '', 'Google/Chrome/Application/chrome.exe'),
      ]
    : isMac
      ? ['/Applications/Google Chrome.app/Contents/MacOS/Google Chrome',
         path.join(os.homedir(), 'Applications/Google Chrome.app/Contents/MacOS/Google Chrome')]
      : ['/usr/bin/google-chrome', '/usr/bin/google-chrome-stable'];
  const found = candidates.find((p) => p && fs.existsSync(p));
  if (!found) throw new Error(`Chrome not found. Set FLOW_CHROME_PATH. Checked: ${candidates.join(', ')}`);
  return found;
}

// Dedicated user-data-dir (Chrome refuses remote debugging on the default one).
function dirBase() {
  if (isWin) return path.join(process.env.LOCALAPPDATA || os.homedir(), 'FlowImageChrome');
  if (isMac) return path.join(os.homedir(), 'Library/Application Support/FlowImageChrome');
  return path.join(os.homedir(), '.config/FlowImageChrome');
}

// ---------- perfiles: una cuenta de Google por perfil de Chrome ----------
// perfiles.json: {"actual": 0, "perfiles": [{"dir", "email", "creditos", "visto", "sin_sesion"}]}. El 0 es el
// perfil de siempre (FlowImageChrome); los demas FlowImageChrome-2, -3... Solo un Chrome a la vez (un puerto CDP):
// cambiar de cuenta = cerrar el Chrome y abrirlo con otro perfil.
const RUTA_PERFILES = path.join(path.dirname(fileURLToPath(import.meta.url)), 'perfiles.json');
const RUTA_ABIERTO = `${RUTA_PERFILES}.abierto`;   // el dir con que se abrio el Chrome que esta corriendo

export function leerPerfiles() {
  let d = {};
  try { d = JSON.parse(fs.readFileSync(RUTA_PERFILES, 'utf8')); } catch { /* primera vez */ }
  const perfiles = Array.isArray(d.perfiles) && d.perfiles.length ? d.perfiles : [{ dir: dirBase() }];
  const actual = Number.isInteger(d.actual) && d.actual >= 0 && d.actual < perfiles.length ? d.actual : 0;
  return { actual, perfiles };
}

export function guardarPerfiles(d) {
  const tmp = `${RUTA_PERFILES}.tmp`;
  fs.writeFileSync(tmp, JSON.stringify(d, null, 2));
  fs.renameSync(tmp, RUTA_PERFILES);
}

export function anotarPerfil(i, cambios) {
  const d = leerPerfiles();
  if (!d.perfiles[i]) return d;
  d.perfiles[i] = { ...d.perfiles[i], ...cambios };
  guardarPerfiles(d);
  return d;
}

export function nuevoPerfil() {
  const d = leerPerfiles();
  const usados = new Set(d.perfiles.map((p) => p.dir));
  let n = 2;
  while (usados.has(`${dirBase()}-${n}`)) n++;
  d.perfiles.push({ dir: `${dirBase()}-${n}` });
  guardarPerfiles(d);
  return d.perfiles.length - 1;
}

export function quitarPerfil(i) {
  const d = leerPerfiles();
  if (i <= 0 || i >= d.perfiles.length) throw new Error('ese perfil no se puede quitar');
  const [p] = d.perfiles.splice(i, 1);
  if (d.actual >= d.perfiles.length || d.actual === i) d.actual = 0;
  else if (d.actual > i) d.actual--;
  guardarPerfiles(d);
  fs.rmSync(p.dir, { recursive: true, force: true });
  return d;
}

export function userDataDir() {
  if (process.env.FLOW_USER_DATA_DIR) return process.env.FLOW_USER_DATA_DIR;
  const d = leerPerfiles();
  return d.perfiles[d.actual].dir;
}

// Cierra el Chrome de Flow (si esta abierto) y espera a que suelte el puerto.
export async function cerrarChrome() {
  if (!(await cdpAlive())) return false;
  try {
    const v = await (await fetch(`http://127.0.0.1:${CDP_PORT}/json/version`)).json();
    const ws = new WebSocket(v.webSocketDebuggerUrl);
    await new Promise((ok, mal) => { ws.onopen = ok; ws.onerror = mal; });
    ws.send(JSON.stringify({ id: 1, method: 'Browser.close' }));
  } catch { /* ya se estaba cerrando */ }
  for (let i = 0; i < 40 && (await cdpAlive()); i++) await new Promise((r) => setTimeout(r, 250));
  await new Promise((r) => setTimeout(r, 800));   // que suelte el bloqueo del perfil
  return true;
}

// Pasa al perfil i: si el Chrome abierto es de otro perfil, se cierra (el siguiente ensureChrome abre el nuevo).
export async function usarPerfil(i) {
  const d = leerPerfiles();
  if (!d.perfiles[i]) throw new Error(`no hay perfil ${i}`);
  d.actual = i;
  guardarPerfiles(d);
  let abierto = null;
  try { abierto = fs.readFileSync(RUTA_ABIERTO, 'utf8'); } catch { /* nada abierto por nosotros */ }
  if ((await cdpAlive()) && abierto !== d.perfiles[i].dir) await cerrarChrome();
  return d.perfiles[i];
}

// The user's normal Chrome data dir, used only by `setup --from-profile` on macOS.
export function defaultChromeDir() {
  if (isWin) return path.join(process.env.LOCALAPPDATA || '', 'Google/Chrome/User Data');
  if (isMac) return path.join(os.homedir(), 'Library/Application Support/Google/Chrome');
  return path.join(os.homedir(), '.config/google-chrome');
}

export async function cdpAlive() {
  try {
    const res = await fetch(`http://127.0.0.1:${CDP_PORT}/json/version`, { signal: AbortSignal.timeout(2000) });
    return res.ok;
  } catch {
    return false;
  }
}

// On macOS, closing the last window leaves Chrome running with no pages, and Playwright
// can't attach to a page-less browser. Open a fresh window in that case.
async function ensureWindow(url) {
  const targets = await (await fetch(`http://127.0.0.1:${CDP_PORT}/json/list`)).json();
  if (targets.some((t) => t.type === 'page')) return;
  await fetch(`http://127.0.0.1:${CDP_PORT}/json/new?${url}`, { method: 'PUT' });
  await new Promise((r) => setTimeout(r, 1500));
}

export async function ensureChrome({ url = FLOW_URL } = {}) {
  if (await cdpAlive()) {
    await ensureWindow(url);
    return { started: false };
  }
  const dir = userDataDir();
  fs.mkdirSync(dir, { recursive: true });
  const child = spawn(chromePath(), [
    `--remote-debugging-port=${CDP_PORT}`,
    `--user-data-dir=${dir}`,
    '--no-first-run',
    '--no-default-browser-check',
    url,
  ], { detached: true, stdio: 'ignore' });
  child.unref();
  try { fs.writeFileSync(RUTA_ABIERTO, dir); } catch { /* solo sirve para saber que perfil esta abierto */ }
  for (let i = 0; i < 30; i++) {
    await new Promise((r) => setTimeout(r, 500));
    if (await cdpAlive()) return { started: true };
  }
  throw new Error(`Chrome started but CDP port ${CDP_PORT} did not answer within 15s`);
}

// One-time copy of an existing Chrome profile (cookies included) into the dedicated dir.
// Works on macOS (cookies are keyed to the Keychain, not the folder). On Windows, Chrome's
// app-bound cookie encryption makes copies useless, so sign in once in the dedicated Chrome.
export function copyProfile(profileName) {
  if (isWin) throw new Error('Profile copy is not supported on Windows: run `flow-image chrome` and sign in once.');
  const src = path.join(defaultChromeDir(), profileName);
  if (!fs.existsSync(src)) throw new Error(`Profile not found: ${src}`);
  const dst = path.join(userDataDir(), 'Default');
  if (fs.existsSync(dst)) throw new Error(`${dst} already exists; delete ${userDataDir()} first to re-copy.`);
  const skip = new Set(['Cache', 'Code Cache', 'GPUCache', 'Service Worker', 'DawnGraphiteCache', 'DawnWebGPUCache', 'GrShaderCache', 'ShaderCache']);
  fs.mkdirSync(userDataDir(), { recursive: true });
  fs.cpSync(src, dst, { recursive: true, filter: (p) => !skip.has(path.basename(p)) && !/Singleton|LOCK$/.test(path.basename(p)) });
  return dst;
}
