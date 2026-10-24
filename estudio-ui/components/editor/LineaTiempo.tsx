"use client";

// Linea de tiempo multipista, en tiempo del VIDEO:
//   capas de video (fotos/clips encima)   carriles n..1 + uno vacio para soltar
//   textos                                carriles n..1 + uno vacio
//   principal                             los planos; se mueve entera desde su asa
//   voz                                   por tramos: cada uno se mueve y se recorta
//   subtitulos                            por tramos, igual que la voz (por su lado);
//                                         dentro, sus frases (un clic elige una para corregirla)
//   audios                                carriles 1..n + uno vacio
//   musica                                un bloque: mover y recortar
// Gestos: arrastrar un bloque lo mueve (y de carril); sus bordes lo recortan; la
// raya entre dos planos mueve el corte; soltar un archivo de Medios crea una capa
// (o cambia el clip si cae en la pista principal). Con "juntas", mover la principal,
// la voz o los subtitulos mueve las tres. El iman pega a cabezal, bordes, cortes y
// huecos entre palabras. Solo el cabezal escucha al reloj.

import { memo, useEffect, useMemo, useRef, useState } from "react";
import { AudioLines, Film, GripVertical, Layers, Mic, Music2, Type } from "lucide-react";
import { mini, url, type DatosEditor, type Plano, type Recurso } from "@/lib/api";
import {
  DUR_MIN_CAPA, PLANO_MIN_S, aVideo, carriles, huecos, imantarA, moverCapa, moverTodas, moverTramo, planoEn, recortarCapa,
  recortarTramo, type Capa, type Colocacion, type Extras, type PistaTramos, type TipoCapa, type Tramo,
} from "./modelo";
import type { Seleccion } from "./Reproductor";
import { useSonando, useTiempo, type Reloj } from "./reloj";

export const TIPO_ARRASTRE = "application/x-estudio-recurso";
export const TIPO_AUDIO = "application/x-estudio-audio";
const ETIQUETA_W = 96;
const ALTO = { regla: 24, video: 50, texto: 34, principal: 80, voz: 50, subs: 32, audio: 38, musica: 32 };
const TROZO_ONDA = 2000;

type Fila =
  | { clase: "capa"; tipo: TipoCapa; carril: number; alto: number; vacio: boolean }
  | { clase: "principal" | "voz" | "subs" | "musica"; alto: number };

export interface Soltado { tipo: TipoCapa; carril: number; t: number; recurso?: string; archivo?: string; dur?: number }

export default function LineaTiempo(props: {
  planos: Plano[]; porId: Map<string, Recurso>; datos: DatosEditor; reloj: Reloj; total: number;
  px: number; setPx: (px: number) => void; sel: Seleccion | null; alSeleccionar: (s: Seleccion) => void;
  alMoverCorte: (k: number, tVoz: number) => void; alIntercambiar: (i: number, j: number) => void;
  alReordenar: (i: number, hueco: number) => void;
  alSoltarRecurso: (i: number, rid: string) => void; alSoltar: (s: Soltado) => void;
  capas: Capa[]; alCambiarCapas: (c: Capa[]) => void; extras: Extras; alCambiarExtras: (e: Partial<Extras>) => void;
  cancion: string; iman: boolean; col: Colocacion; alCambiarCol: (c: Colocacion) => void; juntas: boolean;
}) {
  const { planos, porId, datos, reloj, total, px, setPx, sel, alSeleccionar, capas, extras, iman, juntas } = props;
  const caja = useRef<HTMLDivElement>(null);
  const contenido = useRef<HTMLDivElement>(null);
  // Estado vivo durante un gesto (se confirma al soltar).
  const [vivoCapas, setVivoCapasEstado] = useState<Capa[] | null>(null);
  const vivoCapasRef = useRef<Capa[] | null>(null);
  const setVivoCapas = (v: Capa[] | null) => { vivoCapasRef.current = v; setVivoCapasEstado(v); };
  const [vivoCol, setVivoColEstado] = useState<Colocacion | null>(null);
  const vivoColRef = useRef<Colocacion | null>(null);
  const setVivoCol = (v: Colocacion | null) => { vivoColRef.current = v; setVivoColEstado(v); };
  const [vivoMusica, setVivoMusica] = useState<Partial<Extras> | null>(null);
  const [corte, setCorte] = useState<{ k: number; t: number } | null>(null);
  // Un clip arrastrado: encima de otro plano (j) se intercambian; entre dos (hueco) se mueve alli.
  const [moviendo, setMoviendo] = useState<{ i: number; x: number; j: number; hueco: number | null } | null>(null);
  const [soltarEn, setSoltarEn] = useState<string | null>(null);

  const cs = vivoCapas || capas;
  const col = vivoCol || props.col;
  const P = col.P;
  const ex = { ...extras, ...(vivoMusica || {}) };
  const D = datos.duracion || (planos.length ? planos[planos.length - 1].fin : 0);
  // Donde se oyen los huecos entre palabras (para que los cortes peguen a ellos).
  const huecosVideo = useMemo(() => huecos(datos.palabras).map((h) => aVideo(props.col.voz, h)).filter((h): h is number => h != null),
    [datos.palabras, props.col.voz]);
  const ancho = Math.max(1, Math.ceil((total + 8) * px));

  const vistos = useMemo(() => {
    if (!corte) return planos;
    const out = planos.slice();
    out[corte.k] = { ...out[corte.k], fin: corte.t };
    out[corte.k + 1] = { ...out[corte.k + 1], inicio: corte.t };
    return out;
  }, [planos, corte]);

  const filas: Fila[] = useMemo(() => {
    const f: Fila[] = [];
    const nV = carriles(cs, "video"), nT = carriles(cs, "texto"), nA = carriles(cs, "audio");
    for (let n = nV + 1; n >= 1; n--) f.push({ clase: "capa", tipo: "video", carril: n, alto: ALTO.video, vacio: n === nV + 1 });
    for (let n = nT + 1; n >= 1; n--) f.push({ clase: "capa", tipo: "texto", carril: n, alto: ALTO.texto, vacio: n === nT + 1 });
    f.push({ clase: "principal", alto: ALTO.principal }, { clase: "voz", alto: ALTO.voz }, { clase: "subs", alto: ALTO.subs });
    for (let n = 1; n <= nA + 1; n++) f.push({ clase: "capa", tipo: "audio", carril: n, alto: ALTO.audio, vacio: n === nA + 1 });
    f.push({ clase: "musica", alto: ALTO.musica });
    return f;
  }, [cs]);
  const altoTotal = ALTO.regla + filas.reduce((s, x) => s + x.alto, 0);

  function tiempoDe(clientX: number) {
    const rect = contenido.current!.getBoundingClientRect();
    return Math.max(0, (clientX - rect.left) / px);
  }

  // Puntos a los que pega el iman (en tiempo del video).
  function puntos(excepto?: string) {
    const c0 = props.col;
    const p = [0, reloj.t, total, ex.musica_desde];
    if (ex.musica_hasta != null) p.push(ex.musica_hasta);
    if (excepto !== "principal") p.push(c0.P, c0.P + D, ...planos.map((x) => x.fin + c0.P));
    (["voz", "subs"] as const).forEach((pista) => c0[pista].forEach((x, k) => {
      if (excepto !== `${pista}${k}`) p.push(x.en, x.en + x.hasta - x.desde);
    }));
    capas.forEach((c) => { if (c.id !== excepto) p.push(c.inicio, c.fin); });
    return p;
  }
  const pegar = (t: number, ev: PointerEvent, excepto?: string) => (iman && !ev.altKey ? imantarA(t, puntos(excepto), 10 / px) : t);

  /** Gesto generico con el puntero: `mover(dt, ev)` y `fin(movido)`. */
  function gesto(e: React.PointerEvent, mover: (dt: number, ev: PointerEvent) => void, fin: (movido: boolean, ev: PointerEvent) => void) {
    e.stopPropagation();
    e.preventDefault();
    const el = e.currentTarget as HTMLElement;
    el.setPointerCapture(e.pointerId);
    const x0 = e.clientX;
    let movido = false;
    const m = (ev: PointerEvent) => {
      if (!movido && Math.abs(ev.clientX - x0) < 4 && Math.abs(ev.clientY - e.clientY) < 4) return;
      movido = true;
      mover((ev.clientX - x0) / px, ev);
    };
    const u = (ev: PointerEvent) => {
      el.removeEventListener("pointermove", m);
      el.removeEventListener("pointerup", u);
      fin(movido, ev);
    };
    el.addEventListener("pointermove", m);
    el.addEventListener("pointerup", u);
  }

  /** Carril bajo el puntero (para pasar una capa a otro carril del mismo tipo). */
  function carrilBajo(ev: PointerEvent, tipo: TipoCapa) {
    for (const el of document.elementsFromPoint(ev.clientX, ev.clientY)) {
      const d = (el as HTMLElement).dataset;
      if (d?.tipo === tipo && d.carril) return Number(d.carril);
    }
    return undefined;
  }

  function agarrarCapa(c: Capa, e: React.PointerEvent, modo: "mover" | "inicio" | "fin") {
    if (e.button !== 0) return;
    alSeleccionar({ tipo: "capa", id: c.id });
    gesto(e, (dt, ev) => {
      if (modo === "mover") {
        let a = Math.max(0, c.inicio + dt);
        const pa = pegar(a, ev, c.id), pb = pegar(a + (c.fin - c.inicio), ev, c.id) - (c.fin - c.inicio);
        a = Math.abs(pa - a) <= Math.abs(pb - a) ? pa : pb;
        setVivoCapas(moverCapa(capas, c.id, a, carrilBajo(ev, c.tipo)));
      } else {
        const t = pegar(Math.max(0, (modo === "inicio" ? c.inicio : c.fin) + dt), ev, c.id);
        setVivoCapas(recortarCapa(capas, c.id, modo, t));
      }
    }, (movido, ev) => {
      const v = vivoCapasRef.current;
      setVivoCapas(null);
      if (movido && v) props.alCambiarCapas(v);
      if (!movido) reloj.ir(tiempoDe(ev.clientX));
    });
  }

  /** Un tramo de la voz o de los subtitulos: moverlo (con "juntas", las tres pistas) o recortarlo por un borde. */
  function agarrarTramo(pista: PistaTramos, k: number, e: React.PointerEvent, modo: "mover" | "inicio" | "fin") {
    if (e.button !== 0) return;
    if (pista === "voz" && datos.sin_voz) return agarrarPrincipal(e); // sin voz propia, la voz es la de los clips
    alSeleccionar({ tipo: pista, k });
    const c0 = props.col, x = c0[pista][k], largo = x.hasta - x.desde;
    gesto(e, (dt, ev) => {
      if (modo === "mover") {
        let en = Math.max(0, x.en + dt);
        const pa = pegar(en, ev, `${pista}${k}`), pb = pegar(en + largo, ev, `${pista}${k}`) - largo;
        en = Math.max(0, Math.abs(pa - en) <= Math.abs(pb - en) ? pa : pb);
        setVivoCol(juntas ? moverTodas(c0, en - x.en) : { ...c0, [pista]: moverTramo(c0[pista], k, en) });
      } else {
        const t = pegar((modo === "inicio" ? x.en : x.en + largo) + dt, ev, `${pista}${k}`);
        setVivoCol({ ...c0, [pista]: recortarTramo(c0[pista], k, modo, t, D) });
      }
    }, (movido, ev) => {
      const v = vivoColRef.current;
      setVivoCol(null);
      if (movido && v) props.alCambiarCol(v);
      if (movido) return;
      const t = tiempoDe(ev.clientX);
      reloj.ir(t);
      // Un clic en los subtitulos elige la frase que hay debajo (para corregirla).
      const lineas = datos.lineas || [];
      if (pista === "subs" && lineas.length && !datos.sin_voz) {
        const v = x.desde + t - x.en;
        const n = lineas.findIndex(([a, b]) => v >= a && v < b);
        alSeleccionar({ tipo: "subs", k, n: n >= 0 ? n : undefined });
      }
    });
  }

  /** El asa de la pista principal: la mueve entera (con "juntas", tambien la voz y los subtitulos). */
  function agarrarPrincipal(e: React.PointerEvent) {
    if (e.button !== 0) return;
    const c0 = props.col;
    gesto(e, (dt, ev) => {
      let a = Math.max(0, c0.P + dt);
      const pa = pegar(a, ev, "principal"), pb = pegar(a + D, ev, "principal") - D;
      a = Math.max(0, Math.abs(pa - a) <= Math.abs(pb - a) ? pa : pb);
      setVivoCol(juntas || datos.sin_voz ? moverTodas(c0, a - c0.P) : { ...c0, P: Math.round(a * 1000) / 1000 });
    }, (movido, ev) => {
      const v = vivoColRef.current;
      setVivoCol(null);
      if (movido && v) props.alCambiarCol(v);
      if (!movido) reloj.ir(tiempoDe(ev.clientX));
    });
  }

  function agarrarMusica(e: React.PointerEvent, modo: "mover" | "inicio" | "fin") {
    if (e.button !== 0) return;
    alSeleccionar({ tipo: "musica" });
    const d0 = extras.musica_desde, h0 = extras.musica_hasta ?? total, o0 = extras.musica_offset;
    let ultimo: Partial<Extras> = {};
    gesto(e, (dt, ev) => {
      if (modo === "mover") {
        const a = Math.max(0, pegar(d0 + dt, ev));
        ultimo = { musica_desde: a, musica_hasta: a + (h0 - d0) };
      } else if (modo === "inicio") {
        const a = Math.min(h0 - DUR_MIN_CAPA, Math.max(0, pegar(d0 + dt, ev)));
        ultimo = { musica_desde: a, musica_offset: Math.max(0, o0 + (a - d0)) };
      } else {
        ultimo = { musica_hasta: Math.max(d0 + DUR_MIN_CAPA, pegar(h0 + dt, ev)) };
      }
      setVivoMusica(ultimo);
    }, (movido, ev) => {
      setVivoMusica(null);
      if (movido) props.alCambiarExtras(redondear(ultimo));
      else reloj.ir(tiempoDe(ev.clientX));
    });
  }

  function empezarCorte(k: number, e: React.PointerEvent) {
    const min = planos[k].inicio + PLANO_MIN_S, max = planos[k + 1].fin - PLANO_MIN_S;
    let ultimo = planos[k].fin;
    gesto(e, (_dt, ev) => {
      let t = tiempoDe(ev.clientX);
      if (iman && !ev.altKey) t = imantarA(t, huecosVideo, 10 / px);
      ultimo = Math.min(max, Math.max(min, t - P));
      setCorte({ k, t: ultimo });
    }, () => {
      setCorte(null);
      if (Math.abs(ultimo - planos[k].fin) > 0.005) props.alMoverCorte(k, ultimo);
    });
  }

  // Un plano agarrado: soltado entre dos planos (su cuarto izquierdo o derecho) su clip se
  // mueve alli y los de en medio se corren; soltado en el centro de otro, se intercambian.
  // Los cortes no se mueven: van con la voz.
  function agarrarPlano(i: number, e: React.PointerEvent) {
    if (e.button !== 0) return;
    alSeleccionar({ tipo: "plano", i });
    let j = i, hueco: number | null = null;
    gesto(e, (_dt, ev) => {
      const tp = tiempoDe(ev.clientX) - P;
      j = planoEn(planos, tp);
      const x = planos[j], f = (tp - x.inicio) / Math.max(0.01, x.fin - x.inicio);
      hueco = f < 0.25 ? j : f > 0.75 ? j + 1 : null;
      if (hueco === i || hueco === i + 1) { hueco = null; j = i; } // ya esta ahi
      setMoviendo({ i, x: ev.clientX - contenido.current!.getBoundingClientRect().left, j, hueco });
    }, (movido, ev) => {
      setMoviendo(null);
      if (movido && hueco != null) props.alReordenar(i, hueco);
      else if (movido && j !== i) props.alIntercambiar(i, j);
      else if (!movido) reloj.ir(tiempoDe(ev.clientX));
    });
  }

  // Soltar archivos de Medios.
  function sobre(e: React.DragEvent, clave: string, acepta: string) {
    if (!e.dataTransfer.types.includes(acepta)) return;
    e.preventDefault();
    setSoltarEn(clave);
  }
  function soltarEnCarril(e: React.DragEvent, tipo: TipoCapa, carril: number) {
    setSoltarEn(null);
    const t = tiempoDe(e.clientX);
    const rid = e.dataTransfer.getData(TIPO_ARRASTRE);
    const audio = e.dataTransfer.getData(TIPO_AUDIO);
    if (tipo === "video" && rid) { e.preventDefault(); props.alSoltar({ tipo, carril, t, recurso: rid }); }
    if (tipo === "audio" && audio) {
      e.preventDefault();
      const [archivo, dur] = audio.split("|");
      props.alSoltar({ tipo, carril, t, archivo, dur: Number(dur) || 0 });
    }
  }

  /** Mover el cabezal arrastrando (desde el cabezal, la regla o cualquier hueco): la vista
   *  previa sigue al raton; si estaba sonando, se pausa mientras tanto y sigue al soltar.
   *  Cerca de los bordes, la linea de tiempo se desplaza sola. */
  function deslizar(e: React.PointerEvent) {
    if (e.button !== 0) return;
    e.preventDefault();
    e.stopPropagation();
    const el = e.currentTarget as HTMLElement;
    el.setPointerCapture(e.pointerId);
    const sonaba = reloj.sonando;
    if (sonaba) reloj.parar();
    const ir = (clientX: number) => reloj.ir(Math.min(total, tiempoDe(clientX)));
    ir(e.clientX);
    const mover = (ev: PointerEvent) => {
      const c = caja.current;
      if (c) {
        const r = c.getBoundingClientRect();
        if (ev.clientX > r.right - 30) c.scrollBy({ left: 20 });
        else if (ev.clientX < r.left + 30) c.scrollBy({ left: -20 });
      }
      ir(ev.clientX);
    };
    const soltar = () => {
      el.removeEventListener("pointermove", mover);
      el.removeEventListener("pointerup", soltar);
      if (sonaba) reloj.tocar();
    };
    el.addEventListener("pointermove", mover);
    el.addEventListener("pointerup", soltar);
  }

  // Ctrl + rueda: zoom alrededor del raton.
  useEffect(() => {
    const el = caja.current;
    if (!el) return;
    const rueda = (e: WheelEvent) => {
      if (!e.ctrlKey) return;
      e.preventDefault();
      const rect = el.getBoundingClientRect();
      const t = (el.scrollLeft + e.clientX - rect.left - ETIQUETA_W) / px;
      const nuevo = Math.min(400, Math.max(1, px * (e.deltaY < 0 ? 1.25 : 0.8)));
      setPx(nuevo);
      requestAnimationFrame(() => el.scrollTo({ left: t * nuevo - (e.clientX - rect.left - ETIQUETA_W) }));
    };
    el.addEventListener("wheel", rueda, { passive: false });
    return () => el.removeEventListener("wheel", rueda);
  }, [px, setPx]);

  const recAgarrado = moviendo && planos[moviendo.i]?.recurso ? porId.get(planos[moviendo.i].recurso!) : undefined;
  const selCapa = sel?.tipo === "capa" ? sel.id : null;
  let y = ALTO.regla;

  return (
    <div className="flex overflow-hidden rounded-xl border border-linea bg-hundido select-none">
      <div className="shrink-0 border-r border-linea bg-tarjeta text-xs font-semibold text-tinta-3" style={{ width: ETIQUETA_W }}>
        <div style={{ height: ALTO.regla }} />
        {filas.map((f, n) => (
          <div key={n} className={`flex items-center gap-1.5 border-t border-linea px-2.5 ${f.clase === "capa" && f.vacio ? "opacity-60" : ""}`} style={{ height: f.alto }}>
            {etiqueta(f)}
          </div>
        ))}
      </div>
      <div ref={caja} className="relative min-w-0 flex-1 overflow-x-auto overflow-y-hidden">
        <div ref={contenido} className="relative" style={{ width: ancho, height: altoTotal }}
          onPointerDown={deslizar}>
          <Regla total={total + 8} px={px} />
          {filas.map((f, n) => {
            const top = y;
            y += f.alto;
            const base = { top, height: f.alto };
            if (f.clase === "capa") {
              const clave = `${f.tipo}-${f.carril}`;
              const acepta = f.tipo === "audio" ? TIPO_AUDIO : TIPO_ARRASTRE;
              return (
                <div key={n} data-tipo={f.tipo} data-carril={f.carril}
                  className={`absolute inset-x-0 border-t border-linea ${soltarEn === clave ? "bg-ok-suave" : ""}`} style={base}
                  onDragOver={(e) => f.tipo !== "texto" && sobre(e, clave, acepta)} onDragLeave={() => setSoltarEn(null)}
                  onDrop={(e) => soltarEnCarril(e, f.tipo, f.carril)}>
                  {f.vacio && !cs.some((c) => c.tipo === f.tipo && c.carril === f.carril) && (
                    <span className="pointer-events-none absolute left-2 top-1/2 -translate-y-1/2 text-[10px] text-tinta-3">
                      {f.tipo === "texto" ? "Usa «+ Texto» para anadir un texto" : `Suelta aqui ${f.tipo === "audio" ? "un audio" : "una foto o un video"} de Medios`}
                    </span>
                  )}
                  {cs.filter((c) => c.tipo === f.tipo && c.carril === f.carril).map((c) => (
                    <BloqueCapa key={c.id} c={c} px={px} sel={selCapa === c.id} porId={porId} agarrar={agarrarCapa} />
                  ))}
                </div>
              );
            }
            if (f.clase === "principal") {
              return (
                <div key={n} className="absolute inset-x-0 border-t border-linea" style={base}>
                  <div onPointerDown={agarrarPrincipal} title={juntas ? "Arrastra para mover la principal, la voz y los subtitulos" : "Arrastra para mover toda la pista principal"}
                    className="absolute inset-y-1 z-20 flex w-3.5 cursor-grab items-center justify-center rounded-l-md bg-acento/80 text-sobre-acento hover:bg-acento"
                    style={{ left: P * px }}>
                    <GripVertical size={12} />
                  </div>
                  <div className="absolute inset-y-0" style={{ left: P * px, right: 0 }}>
                    <Bloques planos={vistos} porId={porId} px={px} sel={sel?.tipo === "plano" ? sel.i : null} agarrar={agarrarPlano}
                      destino={moviendo && moviendo.hueco == null && moviendo.j !== moviendo.i ? moviendo.j : null} origen={moviendo?.i ?? null}
                      soltarEn={soltarEn} setSoltarEn={setSoltarEn} alSoltar={(i, rid) => { setSoltarEn(null); props.alSoltarRecurso(i, rid); }} />
                    {vistos.slice(0, -1).map((x, k) => (
                      <div key={`c${k}`} title="Arrastra para mover el corte" onPointerDown={(e) => empezarCorte(k, e)}
                        className="group absolute top-0 z-10 flex h-full w-3 -translate-x-1/2 cursor-ew-resize justify-center" style={{ left: x.fin * px }}>
                        <span className={`h-full w-1 rounded-full ${corte?.k === k ? "bg-acento" : "bg-transparent group-hover:bg-acento/70"}`} />
                      </div>
                    ))}
                    {moviendo?.hueco != null && (
                      <span className="pointer-events-none absolute -top-0.5 -bottom-0.5 z-30 w-1 -translate-x-1/2 rounded-full bg-ok shadow"
                        style={{ left: (moviendo.hueco < vistos.length ? vistos[moviendo.hueco].inicio : vistos[vistos.length - 1].fin) * px }} />
                    )}
                    {corte && (
                      <span className="pointer-events-none absolute top-0 z-30 -translate-x-1/2 rounded bg-acento px-1.5 text-[10px] font-semibold text-sobre-acento tabular-nums"
                        style={{ left: corte.t * px }}>{(corte.t + P).toFixed(2)} s</span>
                    )}
                  </div>
                </div>
              );
            }
            if (f.clase === "voz") {
              return (
                <div key={n} className="absolute inset-x-0 border-t border-linea" style={base}>
                  {col.voz.map((x, k) => (
                    <BloqueTramo key={k} x={x} px={px} sel={sel?.tipo === "voz" && sel.k === k} clase="bg-acento-suave/60"
                      titulo={datos.sin_voz ? "Sin voz propia: va con la pista principal" : "Arrastra para mover este trozo de la voz · bordes para recortar · S para partir"}
                      agarrar={(e, modo) => agarrarTramo("voz", k, e, modo)} bordes={!datos.sin_voz}>
                      <Onda datos={datos} px={px} desde={x.desde} ancho={Math.ceil((x.hasta - x.desde) * px)} alto={f.alto - 8} />
                      {!datos.sin_voz && extras.voz_parches.map((y) => {
                        const a = Math.max(y.desde, x.desde), b = Math.min(y.hasta, x.hasta);
                        return b > a ? (
                          <span key={y.archivo + y.desde} title={`Regrabado: «${y.texto}»`}
                            className="pointer-events-none absolute inset-y-0 border-x-2 border-aviso bg-aviso/25 text-[9px] font-semibold text-aviso"
                            style={{ left: (a - x.desde) * px, width: (b - a) * px }}>
                            {(b - a) * px > 50 ? <span className="absolute left-1 top-0">regrabado</span> : null}
                          </span>
                        ) : null;
                      })}
                    </BloqueTramo>
                  ))}
                </div>
              );
            }
            if (f.clase === "subs") {
              return (
                <div key={n} className="absolute inset-x-0 border-t border-linea" style={base}>
                  {col.subs.map((x, k) => (
                    <BloqueTramo key={k} x={x} px={px} sel={sel?.tipo === "subs" && sel.k === k} clase="bg-acento-suave/30"
                      titulo="Clic en una frase para corregirla · arrastra para mover estos subtitulos · bordes para recortar · S para partir"
                      agarrar={(e, modo) => agarrarTramo("subs", k, e, modo)} bordes>
                      {datos.lineas?.length ? (
                        <Frases lineas={datos.lineas} cambios={datos.sin_voz ? {} : extras.subs_texto} px={px} desde={x.desde} hasta={x.hasta}
                          elegida={sel?.tipo === "subs" && sel.k === k ? sel.n ?? null : null} />
                      ) : (
                        <Palabras palabras={datos.palabras} px={px} desde={x.desde} hasta={x.hasta} />
                      )}
                    </BloqueTramo>
                  ))}
                </div>
              );
            }
            const desde = ex.musica_desde, hasta = ex.musica_hasta ?? total;
            return (
              <div key={n} className="absolute inset-x-0 border-t border-linea" style={base}>
                {props.cancion ? (
                  <div onPointerDown={(e) => agarrarMusica(e, "mover")}
                    className={`absolute inset-y-1 flex cursor-grab items-center gap-1 overflow-hidden rounded-md border-2 bg-ok-suave px-2 text-[11px] text-ok ${sel?.tipo === "musica" ? "border-acento" : "border-transparent"}`}
                    style={{ left: desde * px, width: Math.max(4, (hasta - desde) * px) }}>
                    <Borde lado="izq" onPointerDown={(e) => agarrarMusica(e, "inicio")} />
                    <Music2 size={11} /> <span className="truncate">{props.cancion === "random" ? "Aleatoria (se elige al montar)" : props.cancion}</span>
                    <Borde lado="der" onPointerDown={(e) => agarrarMusica(e, "fin")} />
                  </div>
                ) : (
                  <button className="absolute left-2 top-1/2 -translate-y-1/2 text-[10px] text-tinta-3 underline"
                    onPointerDown={(e) => e.stopPropagation()} onClick={() => alSeleccionar({ tipo: "musica" })}>Sin musica: elegir una cancion</button>
                )}
              </div>
            );
          })}
          {moviendo && recAgarrado && (
            // eslint-disable-next-line @next/next/no-img-element
            <img src={url.miniatura(mini(recAgarrado))} alt="" className="pointer-events-none absolute z-30 h-14 w-20 -translate-x-1/2 rounded-md border-2 border-acento object-cover opacity-90 shadow-lg"
              style={{ left: moviendo.x, top: filaTop(filas, "principal") + 10 }} />
          )}
          <Cabezal reloj={reloj} px={px} caja={caja} alto={altoTotal} agarrar={deslizar} />
        </div>
      </div>
    </div>
  );
}

function redondear(e: Partial<Extras>) {
  const out: Partial<Extras> = {};
  for (const [k, v] of Object.entries(e)) (out as Record<string, number>)[k] = Math.round((v as number) * 1000) / 1000;
  return out;
}

function filaTop(filas: Fila[], clase: string) {
  let y = ALTO.regla;
  for (const f of filas) {
    if (f.clase === clase) return y;
    y += f.alto;
  }
  return y;
}

function etiqueta(f: Fila) {
  if (f.clase === "capa") {
    const n = f.carril;
    if (f.tipo === "video") return <><Layers size={12} /> Capa {n}</>;
    if (f.tipo === "texto") return <><Type size={12} /> Texto {n}</>;
    return <><AudioLines size={12} /> Audio {n}</>;
  }
  if (f.clase === "principal") return <><Film size={12} /> Principal</>;
  if (f.clase === "voz") return <><Mic size={12} /> Voz</>;
  if (f.clase === "subs") return <>Subtitulos</>;
  return <><Music2 size={12} /> Musica</>;
}

function Borde({ lado, onPointerDown }: { lado: "izq" | "der"; onPointerDown: (e: React.PointerEvent) => void }) {
  return (
    <span onPointerDown={onPointerDown} title="Arrastra para recortar"
      className={`absolute inset-y-0 z-10 w-2 cursor-ew-resize hover:bg-white/40 ${lado === "izq" ? "left-0" : "right-0"}`} />
  );
}

const COLOR_CAPA: Record<TipoCapa, string> = {
  video: "bg-[#2b6cb0] text-white", texto: "bg-[#b7791f] text-white", audio: "bg-[#2f855a] text-white",
};

function BloqueTramo({ x, px, sel, clase, titulo, agarrar, bordes, children }: {
  x: Tramo; px: number; sel: boolean; clase: string; titulo: string; bordes: boolean;
  agarrar: (e: React.PointerEvent, modo: "mover" | "inicio" | "fin") => void; children: React.ReactNode;
}) {
  return (
    <div onPointerDown={(e) => agarrar(e, "mover")} title={`${titulo}\n${x.desde.toFixed(2)}–${x.hasta.toFixed(2)} s de la voz, en el ${x.en.toFixed(2)} s`}
      className={`absolute inset-y-1 cursor-grab overflow-hidden rounded-md border-2 ${clase} ${sel ? "border-acento" : "border-transparent hover:border-acento/40"}`}
      style={{ left: x.en * px, width: Math.max(4, (x.hasta - x.desde) * px) }}>
      {children}
      {bordes && <Borde lado="izq" onPointerDown={(e) => agarrar(e, "inicio")} />}
      {bordes && <Borde lado="der" onPointerDown={(e) => agarrar(e, "fin")} />}
    </div>
  );
}

const BloqueCapa = memo(function BloqueCapa({ c, px, sel, porId, agarrar }: {
  c: Capa; px: number; sel: boolean; porId: Map<string, Recurso>;
  agarrar: (c: Capa, e: React.PointerEvent, modo: "mover" | "inicio" | "fin") => void;
}) {
  const w = (c.fin - c.inicio) * px;
  const r = c.recurso ? porId.get(c.recurso) : undefined;
  const nombre = c.grafico ? `✦ ${(Object.values(c.grafico.valores).find((x) => x.trim())?.split("\n")[0] || c.grafico.plantilla).replace(/\*/g, "").replace(/\s*\/\s*/g, " ")}`
    : c.tipo === "texto" ? c.texto || "Texto" : c.tipo === "audio" ? (c.archivo || "").replace(/^cancion:|^audios\//, "") : r?.nombre.split("/").pop();
  return (
    <div onPointerDown={(e) => agarrar(c, e, "mover")}
      className={`absolute top-1 bottom-1 cursor-grab overflow-hidden rounded-md border-2 ${c.grafico ? "bg-[#6b46c1] text-white" : COLOR_CAPA[c.tipo]} ${sel ? "border-white ring-2 ring-acento" : "border-transparent"}`}
      style={{ left: c.inicio * px, width: Math.max(4, w),
        backgroundImage: c.tipo === "video" && r ? `url(${url.miniatura(mini(r))})` : undefined, backgroundSize: "auto 100%", backgroundRepeat: "repeat-x" }}
      title={`${nombre} · ${c.inicio.toFixed(2)} → ${c.fin.toFixed(2)} s`}>
      <Borde lado="izq" onPointerDown={(e) => agarrar(c, e, "inicio")} />
      {w > 28 && (
        <span className="pointer-events-none absolute left-2 top-1/2 max-w-[calc(100%-16px)] -translate-y-1/2 truncate rounded bg-black/45 px-1 text-[10px] font-semibold">
          {c.tipo === "video" && c.modo === "ventana" ? "▣ " : ""}{nombre}
        </span>
      )}
      <Borde lado="der" onPointerDown={(e) => agarrar(c, e, "fin")} />
    </div>
  );
});

const Regla = memo(function Regla({ total, px }: { total: number; px: number }) {
  const paso = [0.5, 1, 2, 5, 10, 15, 30, 60, 120, 300].find((s) => s * px >= 70) || 600;
  const marcas = [];
  for (let s = 0; s <= total + 0.001; s += paso) marcas.push(s);
  return (
    <div className="absolute inset-x-0 top-0 bg-tarjeta" style={{ height: ALTO.regla }}>
      {marcas.map((s) => (
        <span key={s} className="absolute top-0 h-full border-l border-linea pl-1 text-[11px] leading-6 text-tinta-3 tabular-nums" style={{ left: s * px }}>
          {Math.floor(s / 60)}:{String(Math.floor(s % 60)).padStart(2, "0")}{s % 1 ? ".5" : ""}
        </span>
      ))}
    </div>
  );
});

const Bloques = memo(function Bloques({ planos, porId, px, sel, agarrar, destino, origen, soltarEn, setSoltarEn, alSoltar }: {
  planos: Plano[]; porId: Map<string, Recurso>; px: number; sel: number | null;
  agarrar: (i: number, e: React.PointerEvent) => void; destino: number | null; origen: number | null;
  soltarEn: string | null; setSoltarEn: (k: string | null) => void; alSoltar: (i: number, rid: string) => void;
}) {
  return (
    <>
      {planos.map((x) => {
        const r = x.recurso ? porId.get(x.recurso) : undefined;
        const w = (x.fin - x.inicio) * px;
        const corto = x.tipo === "video" && (x.dur_recurso || 0) > 0 && (x.offset || 0) + (x.fin - x.inicio) > (x.dur_recurso || 0) + 0.05;
        const clave = `plano-${x.i}`;
        return (
          <div key={x.i}
            onPointerDown={(e) => agarrar(x.i, e)}
            onDragOver={(e) => { if (e.dataTransfer.types.includes(TIPO_ARRASTRE)) { e.preventDefault(); e.stopPropagation(); setSoltarEn(clave); } }}
            onDragLeave={() => setSoltarEn(null)}
            onDrop={(e) => { const rid = e.dataTransfer.getData(TIPO_ARRASTRE); if (rid) { e.preventDefault(); e.stopPropagation(); alSoltar(x.i, rid); } }}
            className={`absolute top-1 bottom-1 cursor-grab overflow-hidden rounded-lg border-2 bg-tarjeta ${
              sel === x.i ? "border-acento" : destino === x.i || soltarEn === clave ? "border-ok" : "border-transparent"} ${origen === x.i ? "opacity-40" : ""}`}
            style={{ left: x.inicio * px + 1, width: Math.max(3, w - 2), backgroundImage: r ? `url(${url.miniatura(mini(r))})` : undefined,
              backgroundSize: "auto 100%", backgroundRepeat: "repeat-x" }}
            title={`${x.escena ? `Escena ${x.escena}` : `Plano ${x.i + 1}`} · ${(x.fin - x.inicio).toFixed(1)} s · ${r?.nombre || ""}\nArrastralo entre dos planos para mover el clip alli, o al centro de otro para intercambiarlos`}>
            {w > 30 && (
              <span className="absolute left-1 top-1 flex items-center gap-0.5 rounded bg-black/60 px-1 text-[10px] font-semibold text-white">
                {x.tipo === "video" && <Film size={9} />}{x.escena ?? x.i + 1}
              </span>
            )}
            {corto && w > 26 && <span className="absolute right-1 top-1 rounded bg-aviso px-1 text-[9px] font-semibold text-white" title="El clip es mas corto que el plano">corto</span>}
            {w > 70 && (
              <span className="absolute inset-x-0 bottom-0 truncate bg-gradient-to-t from-black/75 to-transparent px-1.5 pb-0.5 pt-3 text-[10px] text-white">{x.texto}</span>
            )}
          </div>
        );
      })}
    </>
  );
});

/** Las frases de un trozo de subtitulos: corregidas en cursiva, quitadas tachadas. */
const Frases = memo(function Frases({ lineas, cambios, px, desde, hasta, elegida }: {
  lineas: [number, number, string][]; cambios: Record<string, string>; px: number; desde: number; hasta: number; elegida: number | null;
}) {
  return (
    <>
      {lineas.map(([a, b, t], n) => {
        if ((a + b) / 2 < desde || (a + b) / 2 >= hasta) return null;
        const texto = cambios[String(n)] ?? t, quitada = !texto.trim(), w = (b - a) * px;
        const color = n === elegida ? "bg-acento text-sobre-acento" : quitada ? "bg-hundido text-tinta-3 line-through" : "bg-acento-suave text-acento";
        return (
          <span key={n} className={`pointer-events-none absolute top-0.5 bottom-0.5 overflow-hidden whitespace-nowrap rounded-sm px-1 text-[10px] leading-[22px] ${color} ${String(n) in cambios && !quitada ? "italic" : ""}`}
            style={{ left: (a - desde) * px, width: Math.max(2, w - 2) }}>
            {w > 18 ? (quitada ? t : texto) : ""}
          </span>
        );
      })}
    </>
  );
});

const Palabras = memo(function Palabras({ palabras, px, desde, hasta }: {
  palabras: [number, number, string][]; px: number; desde: number; hasta: number;
}) {
  return (
    <>
      {palabras.map(([a, b, t], k) => {
        if ((a + b) / 2 < desde || (a + b) / 2 >= hasta) return null;
        const w = (b - a) * px;
        return (
          <span key={k} className="pointer-events-none absolute top-0.5 bottom-0.5 overflow-hidden rounded-sm bg-acento-suave px-0.5 text-[10px] leading-4 text-acento"
            style={{ left: (a - desde) * px, width: Math.max(1, w - 1) }} title={t}>
            {w > 16 ? t.trim() : ""}
          </span>
        );
      })}
    </>
  );
});

const Onda = memo(function Onda({ datos, px, desde, ancho, alto }: { datos: DatosEditor; px: number; desde: number; ancho: number; alto: number }) {
  const trozos = Math.ceil(ancho / TROZO_ONDA);
  if (!datos.picos.length) {
    return <p className="px-2 text-[11px] leading-[40px] text-tinta-3">{datos.sin_voz ? "Sin voz: suenan los clips" : "Sin voz generada"}</p>;
  }
  return <>{Array.from({ length: trozos }, (_, n) => <TrozoOnda key={n} n={n} datos={datos} px={px} desde={desde} ancho={Math.min(TROZO_ONDA, ancho - n * TROZO_ONDA)} alto={alto} />)}</>;
});

function TrozoOnda({ n, datos, px, desde, ancho, alto }: { n: number; datos: DatosEditor; px: number; desde: number; ancho: number; alto: number }) {
  const lienzo = useRef<HTMLCanvasElement>(null);
  useEffect(() => {
    const c = lienzo.current;
    if (!c || ancho <= 0) return;
    const dpr = window.devicePixelRatio || 1;
    c.width = ancho * dpr;
    c.height = alto * dpr;
    const g = c.getContext("2d")!;
    g.scale(dpr, dpr);
    g.fillStyle = getComputedStyle(document.documentElement).getPropertyValue("--acento").trim() || "#7b5cff";
    const pps = datos.picos_por_s, picos = datos.picos;
    for (let x = 0; x < ancho; x++) {
      const t0 = desde + (n * TROZO_ONDA + x) / px, t1 = desde + (n * TROZO_ONDA + x + 1) / px;
      let m = 0;
      for (let k = Math.floor(t0 * pps), fin = Math.max(k + 1, Math.floor(t1 * pps)); k < fin && k < picos.length; k++) m = Math.max(m, picos[k]);
      const h = Math.max(1, (m / 255) * (alto - 6));
      g.fillRect(x, (alto - h) / 2, 1, h);
    }
  }, [n, datos, px, desde, ancho, alto]);
  return <canvas ref={lienzo} className="pointer-events-none absolute top-0" style={{ left: n * TROZO_ONDA, width: ancho, height: alto }} />;
}

function Cabezal({ reloj, px, caja, alto, agarrar }: {
  reloj: Reloj; px: number; caja: React.RefObject<HTMLDivElement | null>; alto: number; agarrar: (e: React.PointerEvent) => void;
}) {
  const t = useTiempo(reloj);
  const sonando = useSonando(reloj);
  const x = t * px;
  useEffect(() => {
    const el = caja.current;
    if (!el || !sonando) return;
    if (x < el.scrollLeft || x > el.scrollLeft + el.clientWidth - 40) el.scrollTo({ left: Math.max(0, x - 60) });
  }, [x, sonando, caja]);
  // Franja invisible de 14 px alrededor de la linea: se agarra facil y se arrastra.
  return (
    <div onPointerDown={agarrar} title="Arrastra el cabezal" className="group absolute top-0 z-20 flex w-3.5 -translate-x-1/2 cursor-ew-resize justify-center"
      style={{ left: x, height: alto }}>
      <div className="h-full w-0.5 bg-error group-hover:w-[3px]" />
      <div className="absolute -top-0.5 h-3.5 w-3.5 rounded-b-[5px] rounded-t-sm bg-error shadow" />
    </div>
  );
}
