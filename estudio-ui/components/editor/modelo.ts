// Modelo del editor: los planos que se ven y lo que se guarda en el paso Ajuste.
//
// El backend (asignacion._editar) es quien manda: rehace los planos con `limites`
// y reparte `fijados`, `inicio_clip` y `ajuste` por indice de plano. Aqui cada
// operacion cambia la lista de planos AL MOMENTO (para que la linea de tiempo
// responda sin esperar) y devuelve los parametros nuevos; al aplicar, la lista
// que devuelve el servidor sustituye a esta.

import type { AjusteClip, DatosGrafico, Plano, Recurso } from "@/lib/api";

export const PLANO_MIN_S = 0.3;

export type PorPlano<T> = Record<string, T>;

export interface Edicion {
  limites: number[] | null;
  fijados: PorPlano<string>;
  inicio_clip: PorPlano<number>;
  ajuste: PorPlano<AjusteClip>;
}

export interface Estado {
  planos: Plano[];
  ed: Edicion;
}

type Palabra = [number, number, string];

const r3 = (x: number) => Math.round(x * 1000) / 1000;

export function limitesDe(planos: Plano[]) {
  return planos.slice(0, -1).map((x) => r3(x.fin));
}

function textoEntre(palabras: Palabra[], a: number, b: number, otro: string) {
  if (!palabras.length) return otro;
  return palabras.filter(([s, e]) => a <= (s + e) / 2 && (s + e) / 2 < b).map((w) => w[2].trim()).join(" ") || otro;
}

/** Corre las claves por plano: `desde` en adelante se mueven `delta`; `quitar` desaparece. */
function correr<T>(d: PorPlano<T>, desde: number, delta: number, quitar?: number): PorPlano<T> {
  const out: PorPlano<T> = {};
  for (const [k, v] of Object.entries(d)) {
    const i = Number(k);
    if (i === quitar) continue;
    out[String(i >= desde ? i + delta : i)] = v;
  }
  return out;
}

const reindexar = (planos: Plano[]) => planos.map((x, i) => ({ ...x, i }));

/** Partir el plano `i` en el tiempo `t`: las dos mitades llevan el mismo clip y la segunda sigue donde iba. */
export function partir(e: Estado, i: number, t: number, palabras: Palabra[]): Estado | null {
  const x = e.planos[i];
  if (!x || t < x.inicio + PLANO_MIN_S || t > x.fin - PLANO_MIN_S) return null;
  const a = { ...x, fin: r3(t), texto: textoEntre(palabras, x.inicio, t, x.texto) };
  const b = { ...x, inicio: r3(t), offset: r3((x.offset || 0) + (t - x.inicio)), texto: textoEntre(palabras, t, x.fin, ""),
    inicio_elegido: false };
  const planos = reindexar([...e.planos.slice(0, i), a, b, ...e.planos.slice(i + 1)]);
  const fijados = correr(e.ed.fijados, i + 1, 1);
  const ajuste = correr(e.ed.ajuste, i + 1, 1);
  if (e.ed.fijados[String(i)]) fijados[String(i + 1)] = e.ed.fijados[String(i)];
  if (e.ed.ajuste[String(i)]) ajuste[String(i + 1)] = e.ed.ajuste[String(i)];
  return { planos, ed: { limites: limitesDe(planos), fijados, ajuste, inicio_clip: correr(e.ed.inicio_clip, i + 1, 1) } };
}

/** Unir el plano `i` con el siguiente: queda el clip del primero. */
export function unir(e: Estado, i: number): Estado | null {
  const x = e.planos[i], y = e.planos[i + 1];
  if (!x || !y) return null;
  const planos = reindexar([...e.planos.slice(0, i), { ...x, fin: y.fin, texto: `${x.texto} ${y.texto}`.trim() },
    ...e.planos.slice(i + 2)]);
  const q = i + 1;
  return {
    planos,
    ed: {
      limites: limitesDe(planos),
      fijados: correr(e.ed.fijados, q + 1, -1, q),
      ajuste: correr(e.ed.ajuste, q + 1, -1, q),
      inicio_clip: correr(e.ed.inicio_clip, q + 1, -1, q),
    },
  };
}

/** Mover el corte entre el plano `k` y el `k+1` al tiempo `t` (ya acotado). */
export function moverCorte(e: Estado, k: number, t: number, palabras: Palabra[]): Estado | null {
  const x = e.planos[k], y = e.planos[k + 1];
  if (!x || !y) return null;
  const tt = r3(Math.min(Math.max(t, x.inicio + PLANO_MIN_S), y.fin - PLANO_MIN_S));
  const planos = e.planos.slice();
  planos[k] = { ...x, fin: tt, texto: textoEntre(palabras, x.inicio, tt, x.texto) };
  planos[k + 1] = {
    ...y, inicio: tt, texto: textoEntre(palabras, tt, y.fin, y.texto),
    offset: y.inicio_elegido ? y.offset : r3(Math.max(0, (y.offset || 0) + (tt - y.inicio))),
  };
  return { planos, ed: { ...e.ed, limites: limitesDe(planos) } };
}

export function cambiarClip(e: Estado, i: number, r: Recurso | null, original?: Plano): Estado {
  const fijados = { ...e.ed.fijados };
  const planos = e.planos.slice();
  if (r) {
    fijados[String(i)] = r.id;
    planos[i] = { ...planos[i], recurso: r.id, nombre: r.nombre, tipo: r.tipo, dur_recurso: r.duracion, offset: 0, fijado: true };
  } else {
    delete fijados[String(i)];
    if (original) planos[i] = { ...planos[i], ...original, i, inicio: planos[i].inicio, fin: planos[i].fin, texto: planos[i].texto };
    planos[i] = { ...planos[i], fijado: false };
  }
  return { planos, ed: { ...e.ed, fijados } };
}

export function inicioClip(e: Estado, i: number, s: number | null): Estado {
  const inicio_clip = { ...e.ed.inicio_clip };
  const planos = e.planos.slice();
  if (s == null) delete inicio_clip[String(i)];
  else inicio_clip[String(i)] = r3(s);
  planos[i] = { ...planos[i], offset: s == null ? planos[i].offset : r3(s), inicio_elegido: s != null };
  return { planos, ed: { ...e.ed, inicio_clip } };
}

export function ajusteClip(e: Estado, i: number, modo: AjusteClip | null): Estado {
  const ajuste = { ...e.ed.ajuste };
  const planos = e.planos.slice();
  if (modo) ajuste[String(i)] = modo;
  else delete ajuste[String(i)];
  planos[i] = { ...planos[i], ajuste: modo || undefined };
  return { planos, ed: { ...e.ed, ajuste } };
}

/** Los huecos entre palabras (y el inicio de la primera): donde queda bien un corte. */
export const huecos = (palabras: Palabra[]) =>
  palabras.map((w, k) => (k === 0 ? w[0] : (palabras[k - 1][1] + w[0]) / 2));

export function planoEn(planos: Plano[], t: number) {
  let lo = 0, hi = planos.length - 1;
  while (lo < hi) {
    const m = (lo + hi + 1) >> 1;
    if (planos[m].inicio <= t) lo = m;
    else hi = m - 1;
  }
  return lo;
}

/** Nombre del archivo sin carpeta ni extension (asi se guarda el sonido por clip). */
export const nombreClip = (nombre?: string) => (nombre || "").split("/").pop()!.replace(/\.[^.]+$/, "");

/** Lo que hace el render si el clip no alcanza, cuando el plano no elige nada. */
export function ajustePorDefecto(modoEscenas: boolean, vozContinua: boolean): AjusteClip {
  return modoEscenas ? (vozContinua ? "lento" : "congelar") : "repetir";
}

export const NOMBRE_AJUSTE: Record<AjusteClip, string> = { repetir: "Repetir", congelar: "Congelar", lento: "Mas lento" };

/** Intercambiar los clips de dos planos (arrastrar un plano sobre otro). Cada uno se queda en su sitio y con su duracion. */
export function intercambiar(e: Estado, i: number, j: number): Estado | null {
  const x = e.planos[i], y = e.planos[j];
  if (!x || !y || i === j || !x.recurso || !y.recurso) return null;
  const clip = (p: Plano) => ({ recurso: p.recurso, nombre: p.nombre, tipo: p.tipo, dur_recurso: p.dur_recurso, offset: p.offset,
    inicio_elegido: p.inicio_elegido });
  const planos = e.planos.slice();
  planos[i] = { ...x, ...clip(y), fijado: true };
  planos[j] = { ...y, ...clip(x), fijado: true };
  const inicio_clip = { ...e.ed.inicio_clip };
  const a = inicio_clip[String(i)], b = inicio_clip[String(j)];
  delete inicio_clip[String(i)];
  delete inicio_clip[String(j)];
  if (b != null) inicio_clip[String(i)] = b;
  if (a != null) inicio_clip[String(j)] = a;
  return { planos, ed: { ...e.ed, fijados: { ...e.ed.fijados, [String(i)]: y.recurso, [String(j)]: x.recurso }, inicio_clip } };
}

/** Llevar el clip del plano `i` al hueco `hueco` (0 = antes del primero, n = despues del ultimo).
 *  Los cortes no se mueven (van con la voz): los clips de en medio se corren un plano. */
export function moverClip(e: Estado, i: number, hueco: number): { estado: Estado; destino: number } | null {
  const n = e.planos.length;
  const destino = hueco > i ? hueco - 1 : hueco;
  if (!e.planos[i] || destino === i || destino < 0 || destino >= n) return null;
  const orden = e.planos.map((_, s) => s); // orden[s]: de que plano viene el clip que acaba en s
  orden.splice(i, 1);
  orden.splice(destino, 0, i);
  const a = Math.min(i, destino), b = Math.max(i, destino);
  const planos = e.planos.slice();
  const fijados = { ...e.ed.fijados }, inicio_clip = { ...e.ed.inicio_clip }, ajuste = { ...e.ed.ajuste };
  for (let s = a; s <= b; s++) {
    const de = e.planos[orden[s]], k = String(s), kd = String(orden[s]);
    planos[s] = { ...e.planos[s], recurso: de.recurso, nombre: de.nombre, tipo: de.tipo, dur_recurso: de.dur_recurso,
      offset: de.offset, inicio_elegido: de.inicio_elegido, ajuste: de.ajuste, fijado: !!de.recurso };
    if (de.recurso) fijados[k] = de.recurso; else delete fijados[k];
    if (e.ed.inicio_clip[kd] != null) inicio_clip[k] = e.ed.inicio_clip[kd]; else delete inicio_clip[k];
    if (e.ed.ajuste[kd]) ajuste[k] = e.ed.ajuste[kd]; else delete ajuste[k];
  }
  return { estado: { planos, ed: { ...e.ed, fijados, inicio_clip, ajuste } }, destino };
}

/** Quitar un plano: su tramo pasa al anterior (o al siguiente si es el primero). La voz no se toca. */
export function quitar(e: Estado, i: number): Estado | null {
  if (e.planos.length < 2) return null;
  if (i > 0) return unir(e, i - 1);
  const s = unir(e, 0);
  if (!s) return null;
  // El primero desaparece: el tramo unido lleva el clip del segundo.
  const y = e.planos[1];
  s.planos[0] = { ...s.planos[0], recurso: y.recurso, nombre: y.nombre, tipo: y.tipo, dur_recurso: y.dur_recurso, offset: y.offset, fijado: true };
  if (y.recurso) s.ed.fijados = { ...s.ed.fijados, "0": y.recurso };
  return s;
}

// ------------------------------------------------------------------ capas (render.capas)
// Lo que va encima o aparte de la pista principal, en tiempo del VIDEO (la pista
// principal y la voz empiezan en `voz_retraso`).

export type TipoCapa = "video" | "texto" | "audio";

export interface Capa {
  id: string;
  tipo: TipoCapa;
  carril: number;
  inicio: number;
  fin: number;
  // video
  recurso?: string;
  modo?: "completa" | "ventana";
  x?: number;
  y?: number;
  escala?: number;
  offset?: number;
  volumen?: number;
  // texto
  texto?: string;
  tam?: number;
  color?: string;
  fondo?: boolean;
  // audio (o el WebM de un grafico animado, en una capa de video)
  archivo?: string;
  // grafico animado (HyperFrames): con que se hizo, para volver a editarlo
  grafico?: DatosGrafico;
}

/** Lo demas del render que el editor mueve: donde va cada pista y la musica.
 *  `voz_retraso` es lo de antes (las tres pistas juntas); lo que es null sale de el. */
export interface Extras {
  voz_retraso: number;
  principal_desde: number | null;
  voz_tramos: Tramo[] | null;
  subs_tramos: Tramo[] | null;
  /** Texto corregido de los subtitulos: {indice de la frase: texto}; vacio la quita. */
  subs_texto: Record<string, string>;
  /** Partes de la voz regrabadas con otro texto, cada una en su mismo hueco (tiempo de la voz). */
  voz_parches: Parche[];
  musica_desde: number;
  musica_hasta: number | null;
  musica_offset: number;
}

// ------------------------------------------------------------------ partes de la voz regrabadas
// El servidor encaja cada parche en [desde, hasta): si es mas largo lo acelera (hasta
// FACTOR_PARCHE); si es mas corto, el resto es silencio. Nada mas se mueve.

export interface Parche { desde: number; hasta: number; archivo: string; texto: string }
export const FACTOR_PARCHE = 1.3;

export const parcheEn = (ps: Parche[], v: number) => ps.find((x) => v >= x.desde && v < x.hasta) || null;

/** Poner un parche: quita los que pisa. */
export function ponerParche(ps: Parche[], nuevo: Parche) {
  return [...ps.filter((x) => !(x.desde < nuevo.hasta && nuevo.desde < x.hasta)), nuevo].sort((a, b) => a.desde - b.desde);
}

/** El texto nuevo repartido entre las frases de los subtitulos de ese hueco (por su duracion). */
export function frasesConTexto(lineas: [number, number, string][], a: number, b: number, texto: string) {
  const dentro = lineas.map((l, n) => ({ l, n })).filter(({ l }) => (l[0] + l[1]) / 2 >= a && (l[0] + l[1]) / 2 < b);
  const ws = texto.split(/\s+/).filter(Boolean);
  const total = dentro.reduce((s, { l }) => s + l[1] - l[0], 0) || 1;
  const out: Record<string, string> = {};
  let k = 0, acum = 0;
  dentro.forEach(({ l, n }, idx) => {
    acum += l[1] - l[0];
    const hasta = idx === dentro.length - 1 ? ws.length : Math.round((ws.length * acum) / total);
    out[String(n)] = ws.slice(k, hasta).join(" ");
    k = hasta;
  });
  return out;
}

// ------------------------------------------------------------------ principal, voz y subtitulos
// Cada pista va por su lado. La voz y los subtitulos van por tramos: el trozo
// [desde, hasta) de la voz suena (o se lee) desde el segundo `en` del video.

export interface Tramo { desde: number; hasta: number; en: number }
export interface Colocacion { P: number; voz: Tramo[]; subs: Tramo[] }
export type PistaTramos = "voz" | "subs";

/** Lo mismo que capas.colocacion en el servidor. Sin voz propia, la voz es el sonido de los clips: va con la principal. */
export function colocacion(ex: Extras, D: number, sinVoz: boolean): Colocacion {
  const R = ex.voz_retraso;
  const P = ex.principal_desde ?? R;
  const voz = sinVoz ? [{ desde: 0, hasta: D, en: P }] : ex.voz_tramos ?? [{ desde: 0, hasta: D, en: R }];
  return { P, voz, subs: ex.subs_tramos ?? voz };
}

export const finTramos = (ts: Tramo[]) => Math.max(0, ...ts.map((x) => x.en + x.hasta - x.desde));

/** El tramo que suena en el segundo `t` del video (el ultimo si se pisan), o -1. */
export function tramoEn(ts: Tramo[], t: number) {
  for (let k = ts.length - 1; k >= 0; k--) {
    const x = ts[k];
    if (t >= x.en && t < x.en + x.hasta - x.desde) return k;
  }
  return -1;
}

/** Segundo del video donde se oye el segundo `v` de la voz (o null si ese trozo se quito). */
export function aVideo(ts: Tramo[], v: number) {
  const x = ts.find((y) => v >= y.desde && v < y.hasta);
  return x ? x.en + v - x.desde : null;
}

export function moverTramo(ts: Tramo[], k: number, en: number) {
  return ts.map((x, n) => (n === k ? { ...x, en: r3(Math.max(0, en)) } : x));
}

/** Recortar un tramo por un borde (`t` en tiempo del video): lo que queda no se mueve. */
export function recortarTramo(ts: Tramo[], k: number, borde: "inicio" | "fin", t: number, D: number) {
  return ts.map((x, n) => {
    if (n !== k) return x;
    if (borde === "fin") return { ...x, hasta: r3(Math.min(D, Math.max(x.desde + DUR_MIN_CAPA, x.desde + t - x.en))) };
    const desde = Math.min(x.hasta - DUR_MIN_CAPA, Math.max(0, x.desde + t - x.en, x.desde - x.en));
    return { ...x, desde: r3(desde), en: r3(x.en + desde - x.desde) };
  });
}

/** Partir el tramo que suena en `t` (tiempo del video) en dos que se mueven por separado. */
export function partirTramo(ts: Tramo[], t: number) {
  const k = tramoEn(ts, t);
  if (k < 0) return null;
  const x = ts[k], v = x.desde + t - x.en;
  if (v <= x.desde + DUR_MIN_CAPA || v >= x.hasta - DUR_MIN_CAPA) return null;
  return { tramos: [...ts.slice(0, k), { ...x, hasta: r3(v) }, { desde: r3(v), hasta: x.hasta, en: r3(t) }, ...ts.slice(k + 1)], k: k + 1 };
}

/** Las tres pistas `dt` segundos (sin pasar de 0): para moverlas juntas. */
export function moverTodas(c: Colocacion, dt: number): Colocacion {
  const min = Math.min(c.P, ...c.voz.map((x) => x.en), ...c.subs.map((x) => x.en));
  const d = Math.max(-min, dt);
  const mover = (ts: Tramo[]) => ts.map((x) => ({ ...x, en: r3(x.en + d) }));
  return { P: r3(c.P + d), voz: mover(c.voz), subs: mover(c.subs) };
}

export const DUR_MIN_CAPA = 0.2;
export const nuevoId = () => Math.random().toString(36).slice(2, 10);

export function carriles(capas: Capa[], tipo: TipoCapa) {
  const usados = capas.filter((c) => c.tipo === tipo).map((c) => c.carril);
  return Math.max(0, ...usados);
}

/** Carril libre para [a, b): el primero sin choques, o uno nuevo. */
export function carrilLibre(capas: Capa[], tipo: TipoCapa, a: number, b: number, preferido = 1) {
  for (let n = preferido; n < 30; n++) {
    if (!capas.some((c) => c.tipo === tipo && c.carril === n && c.inicio < b && a < c.fin)) return n;
  }
  return preferido;
}

export function moverCapa(capas: Capa[], id: string, inicio: number, carril?: number) {
  return capas.map((c) => {
    if (c.id !== id) return c;
    const d = c.fin - c.inicio;
    const a = r3(Math.max(0, inicio));
    return { ...c, inicio: a, fin: r3(a + d), carril: carril ?? c.carril };
  });
}

/** Recortar por un borde. En video/audio, recortar el principio adelanta el punto de entrada del archivo. */
export function recortarCapa(capas: Capa[], id: string, borde: "inicio" | "fin", t: number) {
  return capas.map((c) => {
    if (c.id !== id) return c;
    if (borde === "fin") return { ...c, fin: r3(Math.max(c.inicio + DUR_MIN_CAPA, t)) };
    const a = r3(Math.min(Math.max(0, t), c.fin - DUR_MIN_CAPA));
    const offset = c.tipo === "texto" ? c.offset : r3(Math.max(0, (c.offset || 0) + (a - c.inicio)));
    return { ...c, inicio: a, offset };
  });
}

export function partirCapa(capas: Capa[], id: string, t: number) {
  const c = capas.find((x) => x.id === id);
  if (!c || t <= c.inicio + DUR_MIN_CAPA || t >= c.fin - DUR_MIN_CAPA) return null;
  const b: Capa = { ...c, id: nuevoId(), inicio: r3(t), offset: c.tipo === "texto" ? c.offset : r3((c.offset || 0) + (t - c.inicio)) };
  return [...capas.map((x) => (x.id === id ? { ...x, fin: r3(t) } : x)), b];
}

/** Imantar un tiempo a los bordes cercanos (cabezal, otras capas, cortes, 0). */
export function imantarA(t: number, puntos: number[], radio: number) {
  let mejor = t, dist = radio;
  for (const p of puntos) {
    const d = Math.abs(p - t);
    if (d < dist) {
      dist = d;
      mejor = p;
    }
  }
  return mejor;
}
