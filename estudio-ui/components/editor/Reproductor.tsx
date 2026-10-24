"use client";

// Vista previa sin montar. El reloj cuenta el tiempo del VIDEO; la pista principal,
// la voz y los subtitulos van cada uno donde los puso el editor (la voz y los
// subtitulos por tramos). Encima van las capas (fotos y videos a
// pantalla completa o en ventana, textos propios) y suenan la voz, la musica en
// su tramo, los audios de las capas y el sonido de los clips. Es una
// aproximacion del render: los efectos del estilo editorial/intenso solo se ven
// en el video montado.

import { useEffect, useMemo, useRef, useState } from "react";
import { Pause, Play, SkipBack, SkipForward } from "lucide-react";
import { mini, url, type AjusteClip, type DatosEditor, type Params, type Plano, type Recurso } from "@/lib/api";
import { FACTOR_PARCHE, nombreClip, parcheEn, planoEn, tramoEn, type Capa, type Colocacion, type Extras, type Parche } from "./modelo";
import { sincronizar, useSonando, useTiempo, type Reloj } from "./reloj";

const ALTO_VIDEO: Record<string, number> = { "9:16": 1920, "16:9": 1080, "1:1": 1080 };
const PROPORCION: Record<string, string> = { "9:16": "9 / 16", "16:9": "16 / 9", "1:1": "1 / 1" };

/** Segundo del clip que se ve `local` segundos despues del inicio del plano (como lo hace el render). */
export function tiempoClip(x: Plano, local: number, modoDef: AjusteClip) {
  const off = x.offset || 0, dr = x.dur_recurso || 0, nec = x.fin - x.inicio;
  if (!dr || off + nec <= dr + 0.05) return { t: off + local, vel: 1, quieto: false };
  const modo = x.ajuste || modoDef;
  if (modo === "repetir") {
    const t = off + local;
    return { t: t < dr ? t : (t - dr) % dr, vel: 1, quieto: false };
  }
  const factor = modo === "lento" ? Math.min(1.25, nec / Math.max(0.05, dr - off)) : 1;
  const t = off + local / factor;
  return t >= dr - 0.04 ? { t: dr - 0.04, vel: 1, quieto: true } : { t, vel: 1 / factor, quieto: false };
}

export const urlAudio = (id: string, archivo?: string) =>
  !archivo ? "" : archivo.startsWith("cancion:") ? `/api/motor/musics/${encodeURIComponent(archivo.slice(8))}` : url.archivo(id, archivo);

export type Seleccion = { tipo: "plano"; i: number } | { tipo: "capa"; id: string } | { tipo: "musica" }
  | { tipo: "voz"; k: number } | { tipo: "subs"; k: number; n?: number };

export default function Reproductor({ id, reloj, total, planos, porId, datos, r, modoDef, capas, extras, col, sel, alSeleccionar,
  alCambiarCapa, alSubtitulos }: {
  id: string; reloj: Reloj; total: number; planos: Plano[]; porId: Map<string, Recurso>; datos: DatosEditor;
  r: Params; modoDef: AjusteClip; capas: Capa[]; extras: Extras; col: Colocacion; sel: Seleccion | null; alSeleccionar: (s: Seleccion) => void;
  alCambiarCapa: (id: string, cambio: Partial<Capa>) => void; alSubtitulos: (pct: number) => void;
}) {
  const t = useTiempo(reloj);
  const sonando = useSonando(reloj);
  const voz = useRef<HTMLAudioElement>(null);
  const musica = useRef<HTMLAudioElement>(null);
  const video = useRef<HTMLVideoElement>(null);
  const marco = useRef<HTMLDivElement>(null);
  // Lo que se esta arrastrando en la pantalla (se guarda al soltar: un paso de deshacer).
  const [vivo, setVivo] = useState<{ id: string; cambio: Partial<Capa> } | null>(null);
  const [vivoSubs, setVivoSubs] = useState<number | null>(null);
  const [guias, setGuias] = useState({ x: false, y: false });

  const D = datos.duracion || (planos.length ? planos[planos.length - 1].fin : 0);
  const tv = t - col.P; // tiempo de la pista principal (los planos van en tiempo de la voz original)
  const enPrincipal = tv >= 0 && tv < D;
  const i = planos.length && enPrincipal ? planoEn(planos, tv) : -1;
  // La voz que suena y el subtitulo que se lee: el trozo de cada pista bajo el cabezal.
  const kv = tramoEn(col.voz, t), ks = tramoEn(col.subs, t);
  const tVozTodo = kv >= 0 ? col.voz[kv].desde + t - col.voz[kv].en : null;
  // En una parte regrabada calla la voz original y suena el retoque.
  const parche = tVozTodo != null && !datos.sin_voz ? parcheEn(extras.voz_parches, tVozTodo) : null;
  const tVoz = parche ? null : tVozTodo;
  const trozoSubs = ks >= 0 ? col.subs[ks] : null;
  const x = i >= 0 ? planos[i] : null;
  const rec = x?.recurso ? porId.get(x.recurso) : undefined;
  const aspecto = (r.aspecto as string) || "16:9";
  const encaje = (r.encaje as string) || "desenfoque";
  const alto = ALTO_VIDEO[aspecto] || 1080;

  useEffect(() => { reloj.conectar(total); }, [reloj, total]);

  useEffect(() => {
    if (voz.current) voz.current.volume = Math.min(1, Number(r.volumen_voz ?? 1));
    sincronizar(voz.current, tVoz, sonando);
  }, [tVoz, sonando, r.volumen_voz]);

  const sonidoClip = useMemo(() => {
    if (!x || x.tipo !== "video") return 0;
    if (datos.sin_voz) return 1;
    const modo = ((r.sonido_clips as Record<string, string>) || {})[nombreClip(x.nombre)] || (r.sonido_defecto as string) || "silencio";
    return modo === "silencio" ? 0 : Math.min(1, Number(r.sonido_volumen ?? 0.8));
  }, [x, datos.sin_voz, r.sonido_clips, r.sonido_defecto, r.sonido_volumen]);

  useEffect(() => {
    const v = video.current;
    if (!v || !x || x.tipo !== "video") return;
    const c = tiempoClip(x, tv - x.inicio, modoDef);
    v.muted = sonidoClip === 0;
    v.volume = sonidoClip;
    sincronizar(v, c.t, sonando && !c.quieto, c.vel, 0.3);
  }, [tv, sonando, x, modoDef, sonidoClip]);

  // Musica: solo una cancion elegida (la aleatoria se decide al montar), en su tramo.
  const cancion = (r.musica as string) || "";
  const conMusica = cancion !== "" && cancion !== "random";
  const mHasta = extras.musica_hasta ?? total;
  useEffect(() => {
    const m = musica.current;
    if (!m || !conMusica) return;
    m.volume = Math.min(1, Number(r.musica_volumen ?? 0.2));
    const dentro = t >= extras.musica_desde && t < mHasta;
    const dm = m.duration || 0;
    const local = extras.musica_offset + (t - extras.musica_desde);
    sincronizar(m, dentro ? (dm ? local % dm : local) : null, sonando, 1, 0.4);
  }, [t, sonando, conMusica, r.musica_volumen, extras.musica_desde, extras.musica_offset, mHasta]);

  // Imagen de la pista principal: zoom lento (misma regla que el render).
  let escala = 1;
  if (x && x.tipo !== "video") {
    const nec = Math.max(0.1, x.fin - x.inicio);
    const z = Math.min(Number(r.zoom ?? 0.08), 0.008 * nec);
    const avance = Math.min(1, Math.max(0, (tv - x.inicio) / nec));
    escala = x.i % 2 === 0 ? 1 + z * avance : 1 + z - z * avance;
  }

  /** Arrastrar un objeto en la pantalla: moverlo (con guias al centro) o cambiar su tamano desde la esquina.
   *  Una capa a pantalla completa que se mueve pasa a ventana del mismo tamano. */
  function arrastrar(e: React.PointerEvent, c: Capa, modo: "mover" | "tamano") {
    if (e.button !== 0 || !marco.current) return;
    e.stopPropagation();
    e.preventDefault();
    alSeleccionar({ tipo: "capa", id: c.id });
    const rect = marco.current.getBoundingClientRect();
    const el = e.currentTarget as HTMLElement;
    el.setPointerCapture(e.pointerId);
    const completa = c.tipo === "video" && c.modo !== "ventana";
    const b = { x: completa ? 0.5 : c.x ?? 0.5, y: completa ? 0.5 : c.y ?? 0.5, escala: completa ? 1 : c.escala ?? 0.4, tam: c.tam ?? 90 };
    const cx = rect.left + b.x * rect.width, cy = rect.top + b.y * rect.height;
    const d0 = Math.max(8, Math.hypot(e.clientX - cx, e.clientY - cy));
    let ultimo: Partial<Capa> | null = null, movido = false;
    const mover = (ev: PointerEvent) => {
      if (!movido && Math.hypot(ev.clientX - e.clientX, ev.clientY - e.clientY) < 3) return;
      movido = true;
      if (modo === "mover") {
        let x = b.x + (ev.clientX - e.clientX) / rect.width, y = b.y + (ev.clientY - e.clientY) / rect.height;
        const gx = Math.abs(x - 0.5) < 0.015, gy = Math.abs(y - 0.5) < 0.015;
        if (gx) x = 0.5;
        if (gy) y = 0.5;
        setGuias({ x: gx, y: gy });
        ultimo = { x: redondo(Math.min(1, Math.max(0, x))), y: redondo(Math.min(1, Math.max(0, y))),
          ...(completa ? { modo: "ventana" as const, escala: 1 } : {}) };
      } else {
        const f = Math.hypot(ev.clientX - cx, ev.clientY - cy) / d0;
        ultimo = c.tipo === "texto"
          ? { tam: Math.round(Math.min(400, Math.max(16, b.tam * f))) }
          : { escala: redondo(Math.min(1, Math.max(0.05, b.escala * f))), ...(completa ? { modo: "ventana" as const, x: 0.5, y: 0.5 } : {}) };
      }
      setVivo({ id: c.id, cambio: ultimo });
    };
    const soltar = () => {
      el.removeEventListener("pointermove", mover);
      el.removeEventListener("pointerup", soltar);
      setVivo(null);
      setGuias({ x: false, y: false });
      if (movido && ultimo) alCambiarCapa(c.id, ultimo);
    };
    el.addEventListener("pointermove", mover);
    el.addEventListener("pointerup", soltar);
  }

  /** Arrastrar los subtitulos arriba o abajo (pasan a posicion personalizada). */
  function arrastrarSubs(e: React.PointerEvent) {
    if (e.button !== 0 || !marco.current) return;
    e.stopPropagation();
    e.preventDefault();
    const rect = marco.current.getBoundingClientRect();
    const el = e.currentTarget as HTMLElement;
    el.setPointerCapture(e.pointerId);
    let ultimo: number | null = null;
    const mover = (ev: PointerEvent) => {
      ultimo = Math.round(Math.min(95, Math.max(5, ((ev.clientY - rect.top) / rect.height) * 100)));
      setVivoSubs(ultimo);
    };
    const soltar = () => {
      el.removeEventListener("pointermove", mover);
      el.removeEventListener("pointerup", soltar);
      setVivoSubs(null);
      if (ultimo != null) alSubtitulos(ultimo);
    };
    el.addEventListener("pointermove", mover);
    el.addEventListener("pointerup", soltar);
  }

  const ajusteImg = encaje === "recortar" ? "object-cover" : "object-contain";
  const miniatura = rec ? url.miniatura(mini(rec)) : "";
  const activas = capas.filter((c) => c.inicio <= t && t < c.fin).sort((a, b) => a.carril - b.carril)
    .map((c) => (vivo?.id === c.id ? { ...c, ...vivo.cambio } : c));
  const selId = sel?.tipo === "capa" ? sel.id : null;
  const audiosCerca = capas.filter((c) => c.tipo === "audio" && c.inicio - 2 <= t && t < c.fin);
  const siguiente = planos.slice(i + 1).find((y) => y.tipo === "video");

  return (
    <div className="space-y-3">
      <div className="mx-auto overflow-hidden rounded-xl bg-black"
        style={{ aspectRatio: PROPORCION[aspecto] || "16 / 9", width: `min(100%, calc(58vh * ${PROPORCION[aspecto] || "16 / 9"}))`, containerType: "size" }}>
        <div ref={marco} className="relative h-full w-full">
          {encaje === "desenfoque" && miniatura && (
            // eslint-disable-next-line @next/next/no-img-element
            <img src={miniatura} alt="" className="absolute inset-0 h-full w-full scale-110 object-cover opacity-70 blur-xl" />
          )}
          {x && rec && (x.tipo === "video" ? (
            <video key={`${x.i}-${x.recurso}`} ref={video} src={url.original(id, rec.id)} preload="auto" playsInline
              className={`absolute inset-0 h-full w-full ${ajusteImg}`} onClick={() => alSeleccionar({ tipo: "plano", i: x.i })} />
          ) : (
            // eslint-disable-next-line @next/next/no-img-element
            <img src={url.original(id, rec.id)} alt="" onClick={() => alSeleccionar({ tipo: "plano", i: x.i })}
              className={`absolute inset-0 h-full w-full ${ajusteImg}`} style={{ transform: `scale(${escala})` }} />
          ))}
          {/* Mismo orden que el render: capas de video, subtitulos y, encima, los textos propios. */}
          {activas.filter((c) => c.tipo === "video").map((c) => (
            <CapaVisual key={c.id} c={c} t={t} sonando={sonando} rec={c.recurso ? porId.get(c.recurso) : undefined} id={id}
              elegida={selId === c.id} arrastrar={arrastrar} />
          ))}
          {r.subtitulos !== false && trozoSubs && (
            <Subtitulos t={trozoSubs.desde + t - trozoSubs.en} rango={[trozoSubs.desde, trozoSubs.hasta]} datos={datos}
              cambios={datos.sin_voz ? {} : extras.subs_texto} r={r} alto={alto}
              pct={vivoSubs} arrastrar={arrastrarSubs} />
          )}
          {activas.filter((c) => c.tipo === "texto").map((c) => (
            <TextoCapa key={c.id} c={c} alto={alto} elegida={selId === c.id} arrastrar={arrastrar} />
          ))}
          {guias.x && <div className="pointer-events-none absolute inset-y-0 left-1/2 w-px bg-[#ff3df2]" />}
          {guias.y && <div className="pointer-events-none absolute inset-x-0 top-1/2 h-px bg-[#ff3df2]" />}
        </div>
      </div>
      {siguiente?.recurso && porId.get(siguiente.recurso) && (
        <video key={`pre-${siguiente.recurso}`} src={url.original(id, siguiente.recurso)} preload="auto" muted className="hidden" />
      )}
      {datos.audio && <audio ref={voz} src={url.archivo(id, datos.audio)} preload="auto" />}
      {!datos.sin_voz && extras.voz_parches.map((x) => (
        <ParcheAudio key={x.archivo + x.desde} x={x} local={parche === x && tVozTodo != null ? tVozTodo - x.desde : null}
          sonando={sonando} src={url.archivo(id, x.archivo)} volumen={Math.min(1, Number(r.volumen_voz ?? 1))} />
      ))}
      {conMusica && <audio ref={musica} src={`/api/motor/musics/${encodeURIComponent(cancion)}`} preload="auto" />}
      {audiosCerca.map((c) => <CapaAudio key={c.id} c={c} t={t} sonando={sonando} src={urlAudio(id, c.archivo)} />)}

      <div className="flex items-center justify-center gap-2">
        <button className="boton boton-fantasma !p-2" title="Al principio" onClick={() => reloj.ir(0)}>
          <SkipBack size={16} />
        </button>
        <button className="boton boton-acento !px-4" title="Reproducir (espacio)" onClick={() => (sonando ? reloj.parar() : reloj.tocar())}>
          {sonando ? <Pause size={16} /> : <Play size={16} />}
        </button>
        <button className="boton boton-fantasma !p-2" title="Al final" onClick={() => reloj.ir(total)}>
          <SkipForward size={16} />
        </button>
        <span className="ml-2 text-sm tabular-nums text-tinta-2">{reloj_mmss(t)} / {reloj_mmss(total)}</span>
      </div>
      {!datos.audio && !datos.sin_voz && <p className="text-center text-xs text-tinta-3">Sin audio de voz todavia: genera la voz para oir la vista previa.</p>}
      {cancion === "random" && <p className="text-center text-xs text-tinta-3">Musica aleatoria: se elige al montar (no suena aqui).</p>}
    </div>
  );
}

function CapaVisual({ c, t, sonando, rec, id, elegida, arrastrar }: {
  c: Capa; t: number; sonando: boolean; rec?: Recurso; id: string; elegida: boolean;
  arrastrar: (e: React.PointerEvent, c: Capa, modo: "mover" | "tamano") => void;
}) {
  const v = useRef<HTMLVideoElement>(null);
  const local = (c.offset || 0) + (t - c.inicio);
  const dr = c.archivo ? 0 : rec?.duracion || 0;
  useEffect(() => {
    if (!v.current) return;
    const vol = Math.min(1, c.volumen ?? 0);
    v.current.muted = vol === 0;
    v.current.volume = vol;
    const quieto = dr > 0 && local >= dr - 0.05;
    sincronizar(v.current, quieto ? dr - 0.05 : local, sonando && !quieto, 1, 0.3);
  }, [local, sonando, dr, c.volumen]);
  // Un grafico animado es un WebM transparente propio de la capa; si no, el recurso del proyecto.
  const src = c.archivo ? url.archivo(id, c.archivo) : rec ? url.original(id, rec.id) : "";
  if (!src) return null;
  const esVideo = !!c.archivo || rec?.tipo === "video";
  const ventana = c.modo === "ventana";
  const clase = ventana ? "block w-full rounded-md shadow-lg" : "h-full w-full object-cover";
  return (
    <Movible elegida={elegida} onMover={(e) => arrastrar(e, c, "mover")} onTamano={(e) => arrastrar(e, c, "tamano")}
      estilo={ventana
        ? { left: `${(c.x ?? 0.5) * 100}%`, top: `${(c.y ?? 0.5) * 100}%`, width: `${(c.escala ?? 0.4) * 100}%`, transform: "translate(-50%, -50%)" }
        : { inset: 0 }}>
      {esVideo ? (
        <video ref={v} src={src} preload="auto" playsInline draggable={false} className={clase} />
      ) : (
        // eslint-disable-next-line @next/next/no-img-element
        <img src={src} alt="" draggable={false} className={clase} />
      )}
    </Movible>
  );
}

/** Caja que se arrastra en la pantalla; elegida, muestra su borde y la esquina para cambiar el tamano. */
function Movible({ elegida, onMover, onTamano, estilo, children }: {
  elegida: boolean; onMover: (e: React.PointerEvent) => void; onTamano: (e: React.PointerEvent) => void;
  estilo: React.CSSProperties; children: React.ReactNode;
}) {
  return (
    <div onPointerDown={onMover} title="Arrastra para mover · esquina para cambiar el tamano"
      className={`absolute cursor-move touch-none ${elegida ? "outline outline-2 outline-offset-2 outline-acento" : "hover:outline hover:outline-1 hover:outline-white/60"}`}
      style={estilo}>
      {children}
      {elegida && (
        <span onPointerDown={(e) => { e.stopPropagation(); onTamano(e); }} title="Arrastra para cambiar el tamano"
          className="absolute bottom-1 right-1 z-10 h-4 w-4 cursor-nwse-resize rounded-sm border-2 border-white bg-acento shadow" />
      )}
    </div>
  );
}

function CapaAudio({ c, t, sonando, src }: { c: Capa; t: number; sonando: boolean; src: string }) {
  const a = useRef<HTMLAudioElement>(null);
  const dentro = t >= c.inicio && t < c.fin;
  useEffect(() => {
    if (!a.current) return;
    a.current.volume = Math.min(1, c.volumen ?? 1);
    sincronizar(a.current, dentro ? (c.offset || 0) + (t - c.inicio) : null, sonando, 1, 0.3);
  }, [t, dentro, sonando, c.offset, c.inicio, c.volumen]);
  return src ? <audio ref={a} src={src} preload="auto" /> : null;
}

/** Una parte regrabada: a su ritmo, o acelerada (como el render) si no cabe en su hueco. */
function ParcheAudio({ x, local, sonando, src, volumen }: { x: Parche; local: number | null; sonando: boolean; src: string; volumen: number }) {
  const a = useRef<HTMLAudioElement>(null);
  useEffect(() => {
    const el = a.current;
    if (!el) return;
    el.volume = volumen;
    const f = Math.min(FACTOR_PARCHE, Math.max(1, (el.duration || 0) / (x.hasta - x.desde)));
    sincronizar(el, local == null ? null : local * f, sonando, f, 0.25);
  }, [local, sonando, x.desde, x.hasta, volumen]);
  return <audio ref={a} src={src} preload="auto" />;
}

function TextoCapa({ c, alto, elegida, arrastrar }: {
  c: Capa; alto: number; elegida: boolean; arrastrar: (e: React.PointerEvent, c: Capa, modo: "mover" | "tamano") => void;
}) {
  return (
    <Movible elegida={elegida} onMover={(e) => arrastrar(e, c, "mover")} onTamano={(e) => arrastrar(e, c, "tamano")}
      estilo={{ left: `${(c.x ?? 0.5) * 100}%`, top: `${(c.y ?? 0.5) * 100}%`, transform: "translate(-50%, -50%)", maxWidth: "92%" }}>
      <div className="whitespace-pre-wrap text-center font-bold leading-tight"
        style={{ fontSize: `${((c.tam ?? 90) / alto) * 100}cqh`, color: c.color || "#FFFFFF" }}>
        <span className={`rounded-md px-[0.3em] ${c.fondo !== false ? "bg-black/55" : ""}`}
          style={{ textShadow: c.fondo === false ? "0 0 4px #000, 0 0 4px #000" : undefined }}>{c.texto}</span>
      </div>
    </Movible>
  );
}

const redondo = (v: number) => Math.round(v * 1000) / 1000;

function reloj_mmss(s: number) {
  const m = Math.floor(s / 60);
  const seg = Math.floor(s % 60);
  return `${m}:${String(seg).padStart(2, "0")}.${Math.floor((s % 1) * 10)}`;
}

/** Las palabras que se ven en una frase, con sus tiempos (como palabras_por_linea en el
 *  servidor): las habladas si coinciden en numero; si no, repartidas por letras. */
function palabrasDeFrase(palabras: [number, number, string][], a: number, b: number, mostradas: string[]): [number, number, string][] {
  const habladas = palabras.filter((w) => w[0] >= a - 0.05 && w[0] < b - 0.02);
  if (habladas.length === mostradas.length) return habladas.map((w, n) => [w[0], w[1], mostradas[n]]);
  const ini = habladas[0]?.[0] ?? a, fin = habladas[habladas.length - 1]?.[1] ?? b;
  const letras = mostradas.reduce((s, w) => s + w.length, 0) || 1;
  let t = ini;
  return mostradas.map((w) => {
    const d = ((fin - ini) * w.length) / letras;
    const x: [number, number, string] = [t, t + d, w];
    t += d;
    return x;
  });
}

/** Frases de 8 palabras, si la voz no trae SRT. */
function frasesDePalabras(pal: [number, number, string][]): [number, number, string][] {
  const out: [number, number, string][] = [];
  for (let k = 0; k < pal.length; k += 8) {
    const g = pal.slice(k, k + 8);
    out.push([g[0][0], g[g.length - 1][1], g.map((w) => w[2].trim()).join(" ")]);
  }
  return out;
}

function Subtitulos({ t, rango, datos, cambios, r, alto, pct, arrastrar }: {
  t: number; rango: [number, number]; datos: DatosEditor; cambios: Record<string, string>; r: Params; alto: number;
  pct: number | null; arrastrar: (e: React.PointerEvent) => void;
}) {
  const lineas = datos.lineas?.length ? datos.lineas : frasesDePalabras(datos.palabras);
  const porPalabra = r.edicion && r.edicion !== "clasico" && r.ed_palabras !== false;
  const grupo = porPalabra ? Number(r.palabras_max ?? 4) : 0;
  // La frase que se lee (la ultima que ya empezo y no acabo hace mas de 0,3 s), si es de este trozo.
  let n = -1;
  for (let k = 0; k < lineas.length && lineas[k][0] <= t; k++) if (t < lineas[k][1] + 0.3) n = k;
  if (n < 0) return null;
  const [a, b, original] = lineas[n];
  if ((a + b) / 2 < rango[0] || (a + b) / 2 >= rango[1]) return null;
  const texto = cambios[String(n)] ?? original;
  const mostradas = texto.split(/\s+/).filter(Boolean);
  if (!mostradas.length) return null;
  let trozo: [number, number, string][] = mostradas.map((w) => [a, b, w]), ahora = -1;
  if (grupo) {
    const ws = palabrasDeFrase(datos.palabras, a, b, mostradas);
    ahora = Math.max(0, ws.findLastIndex((w) => w[0] <= t));
    const desde = Math.floor(ahora / grupo) * grupo;
    trozo = ws.slice(desde, desde + grupo);
    ahora -= desde;
  }
  const pos = (r.sub_posicion as string) || "bottom";
  const top = pct != null ? `${pct}%` : pos === "top" ? "8%" : pos === "center" ? "50%" : pos === "custom" ? `${Number(r.sub_posicion_pct ?? 70)}%` : "88%";
  const tam = Number(r.tam_fuente ?? 60) / alto * 100;
  const color = (r.color_texto as string) || "#FFFFFF";
  const resalte = (r.color_resalte as string) || "#FFD447";
  const intenso = r.edicion === "intenso";
  return (
    <div className="pointer-events-none absolute inset-x-[6%] flex justify-center text-center font-bold leading-tight"
      style={{ top, transform: "translateY(-50%)", fontSize: `${tam}cqh` }}>
      <span onPointerDown={arrastrar} title="Arrastra los subtitulos arriba o abajo"
        className={`pointer-events-auto cursor-ns-resize touch-none rounded-md px-[0.35em] py-[0.1em] hover:outline hover:outline-1 hover:outline-white/60 ${r.sub_fondo !== false ? "bg-black/55" : ""} ${pct != null ? "outline outline-2 outline-acento" : ""}`}
        style={{ color, textShadow: r.sub_fondo === false ? `0 0 3px ${(r.color_contorno as string) || "#000"}, 0 0 3px #000` : undefined }}>
        {trozo.map((w, k) => (
          <span key={k}>
            <span style={k === ahora ? { color: resalte, display: "inline-block", transform: intenso ? "scale(1.12)" : undefined, marginInline: intenso ? "0.16em" : undefined } : undefined}>
              {intenso ? w[2].toUpperCase() : w[2]}
            </span>{" "}
          </span>
        ))}
      </span>
    </div>
  );
}
