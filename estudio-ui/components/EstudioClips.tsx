"use client";

// Clip Studio de un video: el video largo con su linea de momentos, la transcripcion,
// los momentos que propone Claude (o los que se anaden a mano) y la exportacion de
// cada uno como short vertical. Los tiempos se ajustan frase a frase o en pasos finos.

import { useCallback, useEffect, useRef, useState } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { ArrowLeft, Download, Loader2, Play, Plus, Scissors, Sparkles, Trash2 } from "lucide-react";
import { AvisoError, Segmentado, Tarjeta } from "./ui";
import { clipStudio, mmss, type DetalleClips, type MomentoClip, type OpcionesShort } from "@/lib/api";

const TRABAJANDO = ["transcribiendo", "proponiendo", "exportando"];

export default function EstudioClips({ id }: { id: string }) {
  const router = useRouter();
  const [d, setD] = useState<DetalleClips | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [sel, setSel] = useState<string | null>(null);
  const [t, setT] = useState(0);
  const video = useRef<HTMLVideoElement>(null);
  const hastaRef = useRef<number | null>(null);

  const cargar = useCallback(() => clipStudio.ver(id).then(setD).catch((e) => setError(String(e.message || e))), [id]);
  useEffect(() => { cargar(); }, [cargar]);
  const trabajando = !!d && TRABAJANDO.includes(d.estado);
  useEffect(() => {
    if (!trabajando) return;
    const k = setInterval(cargar, 2000);
    return () => clearInterval(k);
  }, [trabajando, cargar]);

  const ir = (s: number, hasta?: number) => {
    const v = video.current;
    if (!v) return;
    v.currentTime = s;
    hastaRef.current = hasta ?? null;
    if (hasta != null) v.play().catch(() => {});
  };

  async function guardar(lista: MomentoClip[]) {
    if (!d) return;
    setD({ ...d, propuestas: lista });
    try {
      const r = await clipStudio.guardar(id, lista);
      setD((x) => (x ? { ...x, propuestas: r.propuestas } : x));
    } catch (e) { setError(String((e as Error).message)); }
  }
  const cambiar = (cid: string, cambio: Partial<MomentoClip>) => d && guardar(d.propuestas.map((x) => (x.id === cid ? { ...x, ...cambio } : x)));

  if (error && !d) return <main className="mx-auto max-w-6xl px-4 pt-10"><AvisoError texto={error} /></main>;
  if (!d) return <main className="mx-auto max-w-6xl px-4 pt-10"><Loader2 className="animate-spin text-tinta-3" /></main>;
  const elegido = d.propuestas.find((x) => x.id === sel) || null;

  return (
    <main className="mx-auto max-w-[1500px] px-4 pb-24 pt-8">
      <div className="mb-5 flex flex-wrap items-center gap-3">
        <Link href="/clips" className="boton boton-fantasma !p-2"><ArrowLeft size={16} /></Link>
        <h1 className="font-display text-2xl font-semibold">{d.titulo}</h1>
        <span className="text-sm text-tinta-3">{mmss(d.duracion)} · {d.ancho}×{d.alto}</span>
        <button className="boton boton-fantasma ml-auto !py-1.5 text-sm text-error" disabled={trabajando}
          onClick={async () => { if (confirm("¿Borrar este video y sus shorts?")) { await clipStudio.borrar(id); router.push("/clips"); } }}>
          <Trash2 size={14} /> Borrar
        </button>
      </div>
      {trabajando && (
        <div className="mb-4 rounded-xl border border-linea bg-tarjeta p-3">
          <div className="flex items-center gap-2 text-sm"><Loader2 size={14} className="animate-spin" /> {d.mensaje}</div>
          <div className="mt-2 h-1.5 overflow-hidden rounded-full bg-hundido"><div className="h-full bg-acento transition-all" style={{ width: `${d.progreso}%` }} /></div>
        </div>
      )}
      {d.estado === "error" && <div className="mb-4"><AvisoError texto={d.error} /></div>}
      <AvisoError texto={error} />

      <div className="grid gap-5 lg:grid-cols-[minmax(0,1.35fr)_minmax(0,1fr)]">
        <div className="space-y-4">
          <Tarjeta>
            <div className="relative mx-auto overflow-hidden rounded-xl bg-black" style={{ aspectRatio: `${d.ancho || 16} / ${d.alto || 9}`, maxHeight: "62vh" }}>
              <video ref={video} src={clipStudio.urlOriginal(id)} controls preload="metadata" className="absolute inset-0 h-full w-full"
                onTimeUpdate={(e) => {
                  const v = e.currentTarget;
                  setT(v.currentTime);
                  if (hastaRef.current != null && v.currentTime >= hastaRef.current) { v.pause(); hastaRef.current = null; }
                }} />
              {elegido && <Recuadro d={d} momento={elegido} />}
            </div>
            <LineaMomentos d={d} t={t} sel={sel} onIr={(s) => ir(s)} onElegir={(x) => { setSel(x.id); ir(x.inicio); }} />
          </Tarjeta>
          <Proponer id={id} d={d} trabajando={trabajando} onLanzado={cargar}
            onManual={() => {
              const a = Math.round(t * 10) / 10, b = Math.min(d.duracion, a + 30);
              const nuevo: MomentoClip = { id: Math.random().toString(36).slice(2, 10), inicio: a, fin: b, titulo: "Clip a mano", gancho: "", nota: null, motivo: "" };
              guardar([...d.propuestas, nuevo]);
              setSel(nuevo.id);
            }} />
          <Transcripcion d={d} t={t} onIr={(s) => ir(s)} />
        </div>

        <div className="space-y-4">
          {d.propuestas.length === 0 ? (
            <p className="rounded-2xl border border-dashed border-linea p-8 text-center text-sm text-tinta-3">
              {d.estado === "transcribiendo" ? "Cuando termine la transcripcion, pide a Claude los mejores momentos." : "Aun no hay momentos: pide a Claude que los proponga o anade uno a mano."}
            </p>
          ) : (
            <ul className="space-y-3">
              {d.propuestas.map((x) => (
                <Momento key={x.id} id={id} d={d} x={x} elegido={x.id === sel} trabajando={trabajando}
                  onElegir={() => { setSel(x.id); ir(x.inicio); }} onVer={() => { setSel(x.id); ir(x.inicio, x.fin); }}
                  onCambiar={(c) => cambiar(x.id, c)} onQuitar={() => guardar(d.propuestas.filter((y) => y.id !== x.id))}
                  onExportado={cargar} />
              ))}
            </ul>
          )}
          {d.exportados.length > 0 && (
            <Tarjeta titulo={`Shorts hechos (${d.exportados.length})`}>
              <ul className="grid grid-cols-2 gap-3 sm:grid-cols-3">
                {d.exportados.map((s) => (
                  <li key={s.archivo} className="space-y-1">
                    <video src={clipStudio.urlShort(id, s.archivo)} controls preload="metadata" className="aspect-[9/16] w-full rounded-lg bg-black" />
                    <p className="truncate text-xs" title={s.titulo}>{s.titulo}</p>
                    <a className="boton boton-linea w-full justify-center !py-1 text-xs" href={clipStudio.urlShort(id, s.archivo, true)}>
                      <Download size={12} /> {s.tam_mb} MB
                    </a>
                  </li>
                ))}
              </ul>
            </Tarjeta>
          )}
        </div>
      </div>
    </main>
  );
}

/** El recorte 9:16 sobre el video largo (lo que quedara en el short). */
function Recuadro({ d, momento }: { d: DetalleClips; momento: MomentoClip }) {
  const [x, setX] = useState(0.5);
  useEffect(() => {
    const leer = (e: Event) => { const v = (e as CustomEvent).detail; if (v?.id === momento.id) setX(v.x); };
    window.addEventListener("clips-encuadre", leer);
    return () => window.removeEventListener("clips-encuadre", leer);
  }, [momento.id]);
  const ancho = Math.min(1, (d.alto * 9) / 16 / Math.max(1, d.ancho));
  if (ancho >= 0.999 || x < 0) return null; // video ya vertical, o "entero con fondo desenfocado"
  return (
    <div className="pointer-events-none absolute inset-y-0 border-2 border-acento shadow-[0_0_0_9999px_rgba(0,0,0,0.45)]"
      style={{ left: `${(1 - ancho) * x * 100}%`, width: `${ancho * 100}%` }} />
  );
}

function LineaMomentos({ d, t, sel, onIr, onElegir }: {
  d: DetalleClips; t: number; sel: string | null; onIr: (s: number) => void; onElegir: (x: MomentoClip) => void;
}) {
  const D = Math.max(1, d.duracion);
  return (
    <div className="relative mt-3 h-9 cursor-pointer rounded-lg bg-hundido"
      onClick={(e) => { const r = e.currentTarget.getBoundingClientRect(); onIr(((e.clientX - r.left) / r.width) * D); }}>
      {d.propuestas.map((x) => (
        <button key={x.id} title={`${x.titulo} · ${mmss(x.inicio)}–${mmss(x.fin)}`}
          onClick={(e) => { e.stopPropagation(); onElegir(x); }}
          className={`absolute inset-y-1 rounded ${x.id === sel ? "bg-acento" : "bg-acento/45 hover:bg-acento/70"}`}
          style={{ left: `${(x.inicio / D) * 100}%`, width: `${Math.max(0.4, ((x.fin - x.inicio) / D) * 100)}%` }} />
      ))}
      <span className="pointer-events-none absolute inset-y-0 w-0.5 bg-error" style={{ left: `${(t / D) * 100}%` }} />
    </div>
  );
}

function Proponer({ id, d, trabajando, onLanzado, onManual }: {
  id: string; d: DetalleClips; trabajando: boolean; onLanzado: () => void; onManual: () => void;
}) {
  const [cuantos, setCuantos] = useState(5);
  const [duracion, setDuracion] = useState("medio");
  const [pedido, setPedido] = useState("");
  const [error, setError] = useState("");
  const listo = d.frases.length > 0;
  return (
    <Tarjeta titulo="Buscar momentos">
      <div className="space-y-3">
        <div className="flex flex-wrap items-center gap-3">
          <label className="flex items-center gap-2 text-sm">
            Cuantos
            <select className="campo !w-auto !py-1 text-sm" value={cuantos} onChange={(e) => setCuantos(Number(e.target.value))}>
              {[3, 5, 8, 10, 15].map((n) => <option key={n} value={n}>{n}</option>)}
            </select>
          </label>
          <Segmentado valor={duracion} onChange={setDuracion}
            opciones={[{ v: "corto", t: "15–35 s" }, { v: "medio", t: "30–60 s" }, { v: "largo", t: "55–90 s" }]} />
        </div>
        <input className="campo !py-1.5 text-sm" placeholder="Que buscar (opcional): momentos graciosos, consejos, la parte de la historia…"
          value={pedido} onChange={(e) => setPedido(e.target.value)} />
        {error && <p className="text-xs text-error">{error}</p>}
        <div className="flex flex-wrap gap-2">
          <button className="boton boton-acento !py-1.5 text-sm" disabled={!listo || trabajando}
            onClick={async () => { setError(""); try { await clipStudio.proponer(id, { cuantos, duracion, pedido }); onLanzado(); } catch (e) { setError(String((e as Error).message)); } }}>
            {d.estado === "proponiendo" ? <Loader2 size={14} className="animate-spin" /> : <Sparkles size={14} />}
            {d.propuestas.length ? "Proponer otra vez (sustituye la lista)" : "Proponer con Claude"}
          </button>
          <button className="boton boton-linea !py-1.5 text-sm" disabled={!listo} onClick={onManual} title="Un clip de 30 s desde donde esta el video">
            <Plus size={14} /> Clip desde aqui
          </button>
        </div>
      </div>
    </Tarjeta>
  );
}

function Transcripcion({ d, t, onIr }: { d: DetalleClips; t: number; onIr: (s: number) => void }) {
  if (!d.frases.length) return null;
  return (
    <details className="rounded-2xl border border-linea bg-tarjeta p-4">
      <summary className="cursor-pointer font-display font-semibold">Transcripcion ({d.frases.length} frases)</summary>
      <ol className="mt-3 max-h-80 space-y-0.5 overflow-y-auto pr-1 text-sm">
        {d.frases.map(([a, b, texto], k) => (
          <li key={k}>
            <button onClick={() => onIr(a)} className={`w-full rounded px-1.5 py-0.5 text-left hover:bg-hundido ${t >= a && t < b ? "bg-acento-suave" : ""}`}>
              <span className="mr-2 tabular-nums text-tinta-3">{mmss(a)}</span>{texto}
            </button>
          </li>
        ))}
      </ol>
    </details>
  );
}

/** Inicio y fines de frase cercanos (para mover un borde de frase en frase). */
function bordes(frases: [number, number, string][], cual: "inicio" | "fin") {
  return frases.map((f) => (cual === "inicio" ? Math.max(0, f[0] - 0.15) : f[1] + 0.25));
}

function Momento({ id, d, x, elegido, trabajando, onElegir, onVer, onCambiar, onQuitar, onExportado }: {
  id: string; d: DetalleClips; x: MomentoClip; elegido: boolean; trabajando: boolean;
  onElegir: () => void; onVer: () => void; onCambiar: (c: Partial<MomentoClip>) => void; onQuitar: () => void; onExportado: () => void;
}) {
  const [o, setO] = useState<Omit<OpcionesShort, "inicio" | "fin" | "titulo">>({ encuadre: "recortar", encuadre_x: 0.5, subtitulos: true, gancho: x.gancho, color: "#FFD447" });
  const [error, setError] = useState("");
  const dur = x.fin - x.inicio;
  const mover = (cual: "inicio" | "fin", dir: -1 | 1) => {
    const lista = bordes(d.frases, cual), actual = x[cual];
    const sig = dir > 0 ? lista.find((v) => v > actual + 0.05) : [...lista].reverse().find((v) => v < actual - 0.05);
    if (sig == null) return;
    const c = { ...x, [cual]: Math.round(sig * 100) / 100 };
    if (c.fin - c.inicio >= 1) onCambiar({ [cual]: c[cual] });
  };
  const fino = (cual: "inicio" | "fin", dt: number) => {
    const v = Math.round((x[cual] + dt) * 100) / 100;
    if ((cual === "inicio" ? x.fin - v : v - x.inicio) >= 1 && v >= 0 && v <= d.duracion) onCambiar({ [cual]: v });
  };
  const encuadre = (v: number) => {
    setO((p) => ({ ...p, encuadre_x: v }));
    window.dispatchEvent(new CustomEvent("clips-encuadre", { detail: { id: x.id, x: v } }));
  };
  useEffect(() => {
    if (elegido) window.dispatchEvent(new CustomEvent("clips-encuadre", { detail: { id: x.id, x: o.encuadre === "recortar" ? o.encuadre_x : -1 } }));
  }, [elegido, x.id, o.encuadre, o.encuadre_x]);

  return (
    <li className={`rounded-2xl border bg-tarjeta p-4 ${elegido ? "border-acento" : "border-linea"}`} onClick={() => !elegido && onElegir()}>
      <div className="flex items-start gap-3">
        {x.nota != null && (
          <span className={`grid h-9 w-9 shrink-0 place-items-center rounded-full font-display font-bold ${x.nota >= 8 ? "bg-ok-suave text-ok" : x.nota >= 6 ? "bg-aviso/20 text-aviso" : "bg-hundido text-tinta-2"}`}>{x.nota}</span>
        )}
        <div className="min-w-0 flex-1">
          <input className="w-full bg-transparent font-display font-semibold outline-none" value={x.titulo} onChange={(e) => onCambiar({ titulo: e.target.value })} />
          <p className="text-xs tabular-nums text-tinta-3">{mmss(x.inicio)} → {mmss(x.fin)} · {dur.toFixed(0)} s</p>
          {x.motivo && <p className="mt-1 text-xs text-tinta-2">{x.motivo}</p>}
        </div>
        <button className="boton boton-linea !px-2.5 !py-1 text-xs" onClick={(e) => { e.stopPropagation(); onVer(); }}><Play size={12} /> Ver</button>
        <button className="boton boton-fantasma !p-1.5 text-error" title="Quitar" onClick={(e) => { e.stopPropagation(); onQuitar(); }}><Trash2 size={13} /></button>
      </div>
      {elegido && (
        <div className="mt-3 space-y-3 border-t border-linea pt-3">
          <div className="grid grid-cols-2 gap-2 text-xs">
            {(["inicio", "fin"] as const).map((cual) => (
              <div key={cual} className="rounded-lg border border-linea p-2">
                <p className="etiqueta mb-1">{cual === "inicio" ? "Empieza" : "Termina"} · {x[cual].toFixed(1)} s</p>
                <div className="flex flex-wrap gap-1">
                  <button className="boton boton-fantasma !px-1.5 !py-0.5" title="Frase anterior" onClick={() => mover(cual, -1)}>« frase</button>
                  <button className="boton boton-fantasma !px-1.5 !py-0.5" onClick={() => fino(cual, -0.5)}>−0,5</button>
                  <button className="boton boton-fantasma !px-1.5 !py-0.5" onClick={() => fino(cual, 0.5)}>+0,5</button>
                  <button className="boton boton-fantasma !px-1.5 !py-0.5" title="Frase siguiente" onClick={() => mover(cual, 1)}>frase »</button>
                </div>
              </div>
            ))}
          </div>
          <Segmentado valor={o.encuadre} onChange={(v) => setO((p) => ({ ...p, encuadre: v }))}
            opciones={[{ v: "recortar", t: "Recortar a vertical" }, { v: "ajustar", t: "Entero con fondo desenfocado" }]} />
          {o.encuadre === "recortar" && d.ancho > d.alto && (
            <label className="block text-xs">
              <span className="etiqueta">Que parte se ve (el recuadro sobre el video)</span>
              <input type="range" className="mt-1 w-full accent-[var(--acento)]" min={0} max={1} step={0.01} value={o.encuadre_x}
                onChange={(e) => encuadre(Number(e.target.value))} />
            </label>
          )}
          <div className="flex flex-wrap items-center gap-3 text-sm">
            <label className="flex items-center gap-2"><input type="checkbox" checked={o.subtitulos} onChange={(e) => setO((p) => ({ ...p, subtitulos: e.target.checked }))} /> Subtitulos palabra por palabra</label>
            <span className="w-full text-xs text-tinta-3">Si el video largo ya trae subtitulos grabados, quitalos aqui para que no salgan dos veces.</span>
            <label className="flex items-center gap-2">Color
              <input type="color" className="h-7 w-10 cursor-pointer rounded border border-linea bg-tarjeta" value={o.color} onChange={(e) => setO((p) => ({ ...p, color: e.target.value }))} />
            </label>
          </div>
          <input className="campo !py-1.5 text-sm" placeholder="Gancho arriba los primeros 3 s (vacio: sin gancho)" value={o.gancho}
            onChange={(e) => setO((p) => ({ ...p, gancho: e.target.value }))} />
          {error && <p className="text-xs text-error">{error}</p>}
          <button className="boton boton-acento !py-1.5 text-sm" disabled={trabajando}
            onClick={async () => {
              setError("");
              try { await clipStudio.exportar(id, { ...o, inicio: x.inicio, fin: x.fin, titulo: x.titulo }); onExportado(); } catch (e) { setError(String((e as Error).message)); }
            }}>
            {d.estado === "exportando" ? <Loader2 size={14} className="animate-spin" /> : <Scissors size={14} />} Hacer el short
          </button>
        </div>
      )}
    </li>
  );
}
