#!/usr/bin/env node
// Clips de video con Veo (Flow, modo Fotogramas): cada clip sale de un cuadro inicial (imagen) y un prompt.
// Va rotando las cuentas de Google (perfiles.json, ver chrome.js): antes de cada clip mira los creditos de la
// cuenta y, si no llegan (o Flow avisa de limite), pasa a la siguiente cuenta con sesion y creditos.
//
//   node videos.js --script clips.json --out carpeta --aspect 9:16 [--model lite] [--detener ruta/.detener]
// clips.json: {"clips": [{"n": 3, "prompt": "...", "inicio": "ruta/imagen.jpg"}]}  ->  carpeta/clip_0003.mp4
// El ARCHIVO manda: un clip que ya existe se salta.
//
// Una linea JSON por evento. Salida: 0 fin, 2 detenido, 3 ninguna cuenta con sesion, 4 sin creditos en ninguna,
// 5 Google sigue avisando de actividad inusual tras las esperas, 1 error.
import fs from 'node:fs';
import path from 'node:path';
import { parseArgs } from 'node:util';
import { withFlowLock } from './lock.js';
import { anotarPerfil, leerPerfiles, usarPerfil } from './chrome.js';
import {
  COSTE_VIDEO, Inusual, Limite, SinSesion, VIDEO_MODELS, abrirProyecto, comprobarSesion, configurarVideo, conectar, creditos,
  generarVideo, nuevoProyecto, sleep,
} from './flow.js';

const INTENTOS = 3;
const PAUSA_CLIPS = 45000;              // entre un clip y el siguiente: seguidos, Google avisa de "actividad inusual"
const ESPERAS_INUSUAL = [90, 180, 300]; // segundos de espera cada vez que sale ese aviso (luego cuenta como fallo)
const { values: op } = parseArgs({
  options: {
    script: { type: 'string' },
    out: { type: 'string' },
    aspect: { type: 'string', default: '9:16' },
    model: { type: 'string', default: 'lite' },
    detener: { type: 'string', default: '' },
  },
});

const emitir = (o) => process.stdout.write(`${JSON.stringify({ t: Date.now(), ...o })}\n`);
const salir = (codigo, evento) => { if (evento) emitir(evento); process.exit(codigo); };
if (!op.script || !op.out) salir(1, { evento: 'error', motivo: 'faltan --script y --out' });
if (!['9:16', '16:9'].includes(op.aspect)) salir(1, { evento: 'error', motivo: 'Veo solo hace 9:16 o 16:9' });
if (!VIDEO_MODELS[op.model]) salir(1, { evento: 'error', motivo: `--model debe ser ${Object.keys(VIDEO_MODELS).join(', ')}` });

let parar = false;
const detenido = () => parar || (op.detener && fs.existsSync(op.detener));
process.on('SIGTERM', () => { parar = true; });
process.on('SIGINT', () => { parar = true; });

// Espera troceada para que "detener" no tenga que esperar entera.
async function pausa(ms) {
  for (let t = 0; t < ms && !detenido(); t += 500) await sleep(500);
}

const archivo = (n) => path.join(op.out, `clip_${String(n).padStart(4, '0')}.mp4`);

async function main() {
  const { clips = [] } = JSON.parse(fs.readFileSync(op.script, 'utf8'));
  const pendientes = clips.filter((c) => c.prompt && c.inicio && fs.existsSync(c.inicio) && !fs.existsSync(archivo(c.n)));
  emitir({ evento: 'inicio', total: clips.length, pendientes: pendientes.length });
  if (!pendientes.length) return [0, { evento: 'fin', ok: 0, error: 0 }];
  fs.mkdirSync(op.out, { recursive: true });

  const { perfiles, actual } = leerPerfiles();
  const orden = perfiles.map((_, i) => (actual + i) % perfiles.length);   // empieza por la cuenta en uso
  let sesion = null;
  let cuenta = null;      // {i, creditos}
  let sinSesion = 0;
  let ultimoFallo = '';   // una cuenta que fallo por otra cosa (no creditos): se avisa de eso
  const cerrar = async () => { await sesion?.browser.close().catch(() => {}); sesion = null; };

  // La siguiente cuenta (en orden) con sesion y creditos para un clip; null si no queda ninguna.
  const siguienteCuenta = async () => {
    await cerrar();
    while (orden.length) {
      const i = orden.shift();
      emitir({ evento: 'cuenta', perfil: i, estado: 'probando' });
      try {
        await usarPerfil(i);
        sesion = await conectar();
        if (!(await comprobarSesion(sesion.page))) {
          anotarPerfil(i, { sin_sesion: true, visto: Date.now() });
          emitir({ evento: 'cuenta', perfil: i, estado: 'sin_sesion' });
          sinSesion++;
          await cerrar();
          continue;
        }
        const c = await creditos(sesion.page);
        anotarPerfil(i, { sin_sesion: false, error: null, email: c.email, creditos: c.creditos, visto: Date.now() });
        emitir({ evento: 'cuenta', perfil: i, estado: 'ok', email: c.email, creditos: c.creditos });
        if (c.creditos != null && c.creditos < COSTE_VIDEO) { await cerrar(); continue; }
        const proyecto = await nuevoProyecto(sesion.page);
        await abrirProyecto(sesion.page, proyecto);
        await configurarVideo(sesion.page, { aspect: op.aspect, model: op.model });
        return { i, creditos: c.creditos };
      } catch (err) {
        ultimoFallo = String(err.message || err).slice(0, 200);
        emitir({ evento: 'cuenta', perfil: i, estado: 'fallo', motivo: ultimoFallo });
        await cerrar();
      }
    }
    return null;
  };

  let ok = 0;
  const fallidos = [];
  let primero = true;
  for (const c of pendientes) {
    if (!primero) await pausa(PAUSA_CLIPS);
    primero = false;
    let hecho = false;
    let inusuales = 0;
    for (let intento = 1; intento <= INTENTOS && !hecho; intento++) {
      if (detenido()) { await cerrar(); return [2, { evento: 'fin', ok, error: fallidos.length, detenido: true }]; }
      if (!cuenta || (cuenta.creditos != null && cuenta.creditos < COSTE_VIDEO)) {
        cuenta = await siguienteCuenta();
        if (!cuenta) {
          if (ultimoFallo) return [1, { evento: 'error', motivo: `Flow fallo al preparar la cuenta: ${ultimoFallo}`, ok }];
          return sinSesion === perfiles.length
            ? [3, { evento: 'sin_sesion', motivo: 'ninguna cuenta de Flow tiene la sesion iniciada' }]
            : [4, { evento: 'sin_creditos', motivo: 'no quedan creditos de video en ninguna cuenta', ok }];
        }
      }
      emitir({ clip: c.n, estado: 'generando', intento, perfil: cuenta.i });
      const t0 = Date.now();
      try {
        const { buffer } = await generarVideo(sesion.page, sesion.context, c.prompt, { inicio: path.resolve(c.inicio) });
        const final = archivo(c.n);
        fs.writeFileSync(`${final}.part`, buffer);
        fs.renameSync(`${final}.part`, final);
        hecho = true;
        ok++;
        if (cuenta.creditos != null) cuenta.creditos -= COSTE_VIDEO;
        anotarPerfil(cuenta.i, { creditos: cuenta.creditos, visto: Date.now() });
        emitir({ clip: c.n, estado: 'ok', segundos: Math.round((Date.now() - t0) / 1000), perfil: cuenta.i, creditos: cuenta.creditos });
        // proyecto nuevo para el siguiente clip: el cuadro inicial anterior no se queda puesto
        await nuevoProyecto(sesion.page).then((p) => abrirProyecto(sesion.page, p))
          .then(() => configurarVideo(sesion.page, { aspect: op.aspect, model: op.model }))
          .catch(() => { cuenta = { ...cuenta, creditos: 0 }; });   // si falla, se reabre al pedir cuenta
      } catch (err) {
        if (err instanceof Inusual && inusuales >= ESPERAS_INUSUAL.length) {
          // Google sigue frenando tras todas las esperas: se para el lote (los que falten se quedan con su imagen)
          await cerrar();
          return [5, { evento: 'inusual', motivo: 'Google detecto actividad inusual: se para por ahora', ok, fallidos: [...fallidos, c.n] }];
        }
        if (err instanceof Inusual && inusuales < ESPERAS_INUSUAL.length) {
          const espera = ESPERAS_INUSUAL[inusuales++];
          emitir({ clip: c.n, estado: 'espera', segundos: espera, motivo: 'Google detecto actividad inusual: esperando' });
          await pausa(espera * 1000);
          // proyecto limpio: el cuadro inicial del intento fallido se queda puesto en el anterior
          await nuevoProyecto(sesion.page).then((p) => abrirProyecto(sesion.page, p))
            .then(() => configurarVideo(sesion.page, { aspect: op.aspect, model: op.model }))
            .catch(() => { cuenta = { ...cuenta, creditos: 0 }; orden.unshift(cuenta.i); });
          intento--;   // no gasta intento: el clip no tiene la culpa
          continue;
        }
        if (err instanceof SinSesion || err instanceof Limite) {
          anotarPerfil(cuenta.i, err instanceof Limite ? { creditos: 0 } : { sin_sesion: true });
          emitir({ clip: c.n, estado: 'cambio_cuenta', perfil: cuenta.i, motivo: err.message.slice(0, 200) });
          cuenta = { ...cuenta, creditos: 0 };
          intento--;   // no cuenta como intento: es la cuenta, no el clip
          continue;
        }
        emitir({ clip: c.n, estado: 'intento', intento, motivo: String(err.message || err).slice(0, 300) });
        cuenta = { ...cuenta, creditos: 0 };   // pagina en mal estado: se reabre (la misma cuenta vuelve si le quedan)
        orden.unshift(cuenta.i);
        await sleep(4000);
      }
    }
    if (!hecho) { fallidos.push(c.n); emitir({ clip: c.n, estado: 'error', intentos: INTENTOS }); }
  }
  await cerrar();
  return [0, { evento: 'fin', ok, error: fallidos.length, fallidos }];
}

withFlowLock(main, { pollMs: 1000 })
  .then(([codigo, evento]) => salir(codigo, evento))
  .catch((err) => salir(1, { evento: 'error', motivo: String(err?.message || err).slice(0, 500) }));
