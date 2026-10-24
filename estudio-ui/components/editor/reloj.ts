// Reloj del editor: el tiempo del VIDEO vive fuera de React para que solo se
// repinten quienes lo escuchan (cabezal, reproductor). Cuenta solo; la voz, la
// musica, los clips y los audios se sincronizan a el (no al reves), asi se puede
// reproducir tambien el tramo antes o despues de la voz.

import { useSyncExternalStore } from "react";

export interface Reloj {
  t: number;
  sonando: boolean;
  duracion: number;
  oyentes: Set<() => void>;
  conectar: (duracion: number) => void;
  ir: (t: number) => void;
  tocar: () => void;
  parar: () => void;
}

export function crearReloj(): Reloj {
  let marca = 0, desde = 0, cuadro = 0;
  const r: Reloj = {
    t: 0, sonando: false, duracion: 0, oyentes: new Set(),
    conectar(duracion) {
      r.duracion = duracion;
      if (r.t > duracion) r.t = duracion;
      avisar();
    },
    ir(t) {
      r.t = Math.max(0, Math.min(t, r.duracion || t));
      desde = r.t;
      marca = performance.now();
      avisar();
    },
    tocar() {
      if (r.sonando) return;
      if (r.t >= r.duracion - 0.05) r.t = 0;
      r.sonando = true;
      desde = r.t;
      marca = performance.now();
      cuadro = requestAnimationFrame(paso);
      avisar();
    },
    parar() {
      r.sonando = false;
      cancelAnimationFrame(cuadro);
      avisar();
    },
  };
  function paso() {
    if (!r.sonando) return;
    r.t = desde + (performance.now() - marca) / 1000;
    if (r.t >= r.duracion) {
      r.t = r.duracion;
      r.parar();
      return;
    }
    avisar();
    cuadro = requestAnimationFrame(paso);
  }
  function avisar() {
    r.oyentes.forEach((f) => f());
  }
  return r;
}

export function useTiempo(r: Reloj) {
  return useSyncExternalStore(
    (f) => {
      r.oyentes.add(f);
      return () => r.oyentes.delete(f);
    },
    () => r.t,
    () => 0,
  );
}

export function useSonando(r: Reloj) {
  return useSyncExternalStore(
    (f) => {
      r.oyentes.add(f);
      return () => r.oyentes.delete(f);
    },
    () => r.sonando,
    () => false,
  );
}

/** Lleva un elemento de audio/video al segundo `t` (o lo calla si `t` es null). */
export function sincronizar(el: HTMLMediaElement | null, t: number | null, sonando: boolean, vel = 1, margen = 0.25) {
  if (!el) return;
  if (t == null || t < 0) {
    if (!el.paused) el.pause();
    return;
  }
  if (Math.abs(el.playbackRate - vel) > 0.01) el.playbackRate = vel;
  if (sonando) {
    if (Math.abs(el.currentTime - t) > margen) el.currentTime = t;
    if (el.paused) el.play().catch(() => {});
  } else {
    if (!el.paused) el.pause();
    if (Math.abs(el.currentTime - t) > 0.04) el.currentTime = t;
  }
}
