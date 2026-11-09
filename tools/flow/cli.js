#!/usr/bin/env node
// Utilidades del Chrome de Flow para el Estudio:
//   node cli.js chrome            abre el Chrome dedicado (perfil en uso) para iniciar sesion
//   node cli.js sesion            {"chrome":bool,"sesion":bool|null,"ocupado":bool} en una linea JSON
//   node cli.js cerrar            cierra el Chrome dedicado (la sesion de Google queda guardada en el perfil)
// Cuentas (un perfil de Chrome por cuenta de Google, para rotar los creditos de video):
//   node cli.js perfiles          lista de perfiles con su correo y creditos vistos por ultima vez
//   node cli.js perfil-nuevo      crea un perfil y abre su Chrome para iniciar sesion con otra cuenta
//   node cli.js perfil-abrir N    abre el Chrome del perfil N (para iniciar sesion o mirar)
//   node cli.js perfil-quitar N   borra el perfil N (el 0 no)
//   node cli.js revisar [N]       entra en cada perfil (o solo el N) y anota correo, sesion y creditos
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { anotarPerfil, cdpAlive, cerrarChrome, ensureChrome, leerPerfiles, nuevoPerfil, quitarPerfil, usarPerfil, userDataDir } from './chrome.js';
import { comprobarSesion, conectar, creditos, nuevoProyecto } from './flow.js';

const LOCK = path.join(path.dirname(fileURLToPath(import.meta.url)), '.flow.lock');
const [cmd, arg] = process.argv.slice(2);
const out = (o) => console.log(JSON.stringify(o));
// ocupado = hay un lote vivo (un bloqueo de un proceso que ya murio no cuenta)
const ocupado = () => {
  if (!fs.existsSync(LOCK)) return false;
  try { process.kill(Number(fs.readFileSync(path.join(LOCK, 'pid'), 'utf8')), 0); return true; } catch { return false; }
};
const numero = () => {
  const n = Number(arg);
  if (!Number.isInteger(n) || !leerPerfiles().perfiles[n]) throw new Error(`no hay perfil ${arg}`);
  return n;
};
const exigirLibre = () => { if (ocupado()) throw new Error('Flow esta generando: espera a que termine'); };

async function revisar(i) {
  await usarPerfil(i);
  await ensureChrome();
  const { browser, page } = await conectar();
  try {
    if (!(await comprobarSesion(page))) return anotarPerfil(i, { sin_sesion: true, visto: Date.now() }).perfiles[i];
    // los creditos salen en el menu de cuenta de un proyecto: el ultimo abierto, o uno nuevo si la cuenta no tiene
    const proyecto = page.locator('a.project-thumbnail-container').first();
    if (await proyecto.isVisible().catch(() => false)) await proyecto.click();
    else await nuevoProyecto(page);
    const c = await creditos(page);
    return anotarPerfil(i, { sin_sesion: false, error: null, email: c.email, creditos: c.creditos, visto: Date.now() }).perfiles[i];
  } finally {
    await browser.close().catch(() => {});
  }
}

try {
  if (cmd === 'chrome') {
    const r = await ensureChrome();
    out({ ok: true, iniciado: r.started, perfil: userDataDir() });
  } else if (cmd === 'sesion') {
    // Con un lote en marcha no se toca la pagina: si esta generando, hay sesion.
    if (ocupado()) {
      out({ chrome: true, sesion: true, ocupado: true });
    } else if (!(await cdpAlive())) {
      out({ chrome: false, sesion: null, ocupado: false });
    } else {
      const { browser, page } = await conectar();
      const sesion = await comprobarSesion(page).finally(() => browser.close().catch(() => {}));
      out({ chrome: true, sesion, ocupado: false });
    }
  } else if (cmd === 'cerrar') {
    if (ocupado()) out({ ok: false, motivo: 'Flow esta generando: detén la generacion antes de cerrar' });
    else out({ ok: true, cerrado: await cerrarChrome() });
  } else if (cmd === 'perfiles') {
    out({ ...leerPerfiles(), ocupado: ocupado() });
  } else if (cmd === 'perfil-nuevo') {
    exigirLibre();
    const i = nuevoPerfil();
    await usarPerfil(i);
    await ensureChrome({ url: 'https://accounts.google.com/ServiceLogin?continue=https://flow.google.com/' });
    out({ ok: true, perfil: i, ...leerPerfiles() });
  } else if (cmd === 'perfil-abrir') {
    exigirLibre();
    const i = numero();
    await usarPerfil(i);
    await ensureChrome();
    out({ ok: true, perfil: i, ...leerPerfiles() });
  } else if (cmd === 'perfil-quitar') {
    exigirLibre();
    const i = numero();
    const abierto = leerPerfiles().actual === i;
    if (abierto) await cerrarChrome();
    out({ ok: true, ...quitarPerfil(i) });
  } else if (cmd === 'revisar') {
    exigirLibre();
    const lista = arg != null ? [numero()] : leerPerfiles().perfiles.map((_, i) => i);
    const antes = leerPerfiles().actual;
    for (const i of lista) {
      try { await revisar(i); } catch (err) { anotarPerfil(i, { error: String(err.message || err).slice(0, 200), visto: Date.now() }); }
    }
    await usarPerfil(antes);
    await cerrarChrome();
    out({ ok: true, ...leerPerfiles() });
  } else {
    console.log('Uso: node cli.js chrome | sesion | cerrar | perfiles | perfil-nuevo | perfil-abrir N | perfil-quitar N | revisar [N]');
  }
} catch (err) {
  out({ ok: false, motivo: String(err.message || err) });
  process.exit(1);
}
