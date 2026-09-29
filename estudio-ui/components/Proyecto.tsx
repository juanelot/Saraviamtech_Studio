"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import Link from "next/link";
import { ArrowLeft, ArrowRight, Check, Loader2, Play, X, ChevronDown, ChevronUp } from "lucide-react";
import { api, type EtapaId, type EstadoEtapa, type Params, type Vista } from "@/lib/api";
import { ChipEstado } from "./ui";
import PanelMaterial from "./paneles/PanelMaterial";
import PanelGuion from "./paneles/PanelGuion";
import PanelVoz from "./paneles/PanelVoz";
import PanelRecursos from "./paneles/PanelRecursos";
import PanelAsignacion from "./paneles/PanelAsignacion";
import PanelVideo from "./paneles/PanelVideo";

export interface PanelProps {
  id: string;
  vista: Vista;
  p: (etapa: EtapaId) => Params;
  set: (etapa: EtapaId, clave: string, valor: unknown) => void;
  ejecutar: (hasta: EtapaId, forzar?: EtapaId[]) => Promise<void>;
  ocupado: boolean;
  recargar: () => Promise<void>;
}

type ParadaId = "material" | "guion" | "voz" | "recursos" | "asignacion" | "video";

const PARADAS: { id: ParadaId; etapa: EtapaId; titulo: string; sub: string }[] = [
  { id: "material", etapa: "guion", titulo: "Material", sub: "De que trata" },
  { id: "guion", etapa: "guion", titulo: "Guion", sub: "Lo que se dice" },
  { id: "voz", etapa: "voz", titulo: "Voz", sub: "Quien lo dice" },
  { id: "recursos", etapa: "recursos", titulo: "Recursos", sub: "Tus imagenes y videos" },
  { id: "asignacion", etapa: "asignacion", titulo: "Planos", sub: "Que se ve en cada frase" },
  { id: "video", etapa: "render", titulo: "Video", sub: "Montaje final" },
];

// Accion principal de cada parada: que etapa ejecutar y a donde ir despues.
const SIGUIENTE: Record<ParadaId, { texto: string; hasta?: EtapaId; ir?: ParadaId }> = {
  material: { texto: "Escribir guion", hasta: "guion", ir: "guion" },
  guion: { texto: "Generar voz", hasta: "voz", ir: "voz" },
  voz: { texto: "Elegir recursos", ir: "recursos" },
  recursos: { texto: "Asignar planos", hasta: "asignacion", ir: "asignacion" },
  asignacion: { texto: "Montar video", hasta: "render", ir: "video" },
  video: { texto: "Montar video", hasta: "render" },
};

const NOMBRE_ETAPA: Record<EtapaId, string> = {
  guion: "Guion", voz: "Voz", recursos: "Recursos", asignacion: "Planos", render: "Video",
};

export default function Proyecto({ id }: { id: string }) {
  const [vista, setVista] = useState<Vista | null>(null);
  const [error, setError] = useState("");
  const [parada, setParada] = useState<ParadaId>("material");
  const [locales, setLocales] = useState<Record<string, Params>>({});
  const [titulo, setTitulo] = useState("");
  const [verLog, setVerLog] = useState(false);
  const pendientes = useRef<Record<string, Params>>({});
  const temporizador = useRef<ReturnType<typeof setTimeout> | null>(null);
  const tituloTimer = useRef<ReturnType<typeof setTimeout> | null>(null);
  const inicial = useRef(true);

  const recargar = useCallback(async () => {
    try {
      const v = await api.ver(id);
      setVista(v);
      setError("");
      if (inicial.current) {
        inicial.current = false;
        setTitulo(v.proyecto.titulo);
        // Abrir en la primera parada que no este al dia.
        const e = v.etapas;
        const pmat = (e.guion.params.material as string) || "";
        const primera: ParadaId = !pmat.trim() ? "material"
          : e.guion.estado !== "ok" ? "guion"
          : e.voz.estado !== "ok" ? "voz"
          : e.recursos.estado !== "ok" ? "recursos"
          : e.asignacion.estado !== "ok" ? "asignacion" : "video";
        const hash = window.location.hash.slice(1) as ParadaId;
        setParada(PARADAS.some((x) => x.id === hash) ? hash : v.trabajo?.etapa ? paradaDe(v.trabajo.etapa) : primera);
      }
    } catch (err) {
      setError(String((err as Error).message));
    }
  }, [id]);

  useEffect(() => {
    // recargar es async: el setState ocurre tras el fetch, no dentro del efecto.
    // eslint-disable-next-line react-hooks/set-state-in-effect
    recargar();
  }, [recargar]);

  useEffect(() => {
    if (!inicial.current) history.replaceState(null, "", `#${parada}`);
  }, [parada]);

  // Mientras hay un trabajo, se consulta cada 1,5 s.
  const trabajando = !!vista?.trabajo;
  useEffect(() => {
    if (!trabajando) return;
    const t = setInterval(recargar, 1500);
    return () => clearInterval(t);
  }, [trabajando, recargar]);

  const guardar = useCallback(async () => {
    if (temporizador.current) clearTimeout(temporizador.current);
    temporizador.current = null;
    const envio = pendientes.current;
    if (!Object.keys(envio).length) return;
    pendientes.current = {};
    try {
      setVista(await api.editar(id, { params: envio }));
    } catch (err) {
      setError(String((err as Error).message));
    }
  }, [id]);

  const set = useCallback((etapa: EtapaId, clave: string, valor: unknown) => {
    setLocales((l) => ({ ...l, [etapa]: { ...(l[etapa] || {}), [clave]: valor } }));
    pendientes.current = {
      ...pendientes.current,
      [etapa]: { ...(pendientes.current[etapa] || {}), [clave]: valor },
    };
    if (temporizador.current) clearTimeout(temporizador.current);
    temporizador.current = setTimeout(guardar, 600);
  }, [guardar]);

  const p = useCallback((etapa: EtapaId): Params => {
    const base = vista?.etapas[etapa].params || {};
    const loc = locales[etapa] || {};
    const out: Params = { ...base };
    for (const [k, v] of Object.entries(loc)) if (v !== null) out[k] = v;
    return out;
  }, [vista, locales]);

  const ejecutar = useCallback(async (hasta: EtapaId, forzar: EtapaId[] = []) => {
    await guardar();
    try {
      setVista(await api.ejecutar(id, hasta, forzar));
      setVerLog(false);
    } catch (err) {
      setError(String((err as Error).message));
    }
  }, [guardar, id]);

  function cambiarTitulo(t: string) {
    setTitulo(t);
    if (tituloTimer.current) clearTimeout(tituloTimer.current);
    tituloTimer.current = setTimeout(() => api.editar(id, { titulo: t }).then(setVista), 700);
  }

  if (!vista) {
    return (
      <main className="mx-auto max-w-6xl px-4 py-16 text-tinta-3">
        {error ? <p className="text-error">{error}</p> : <Loader2 className="animate-spin" />}
      </main>
    );
  }

  const props: PanelProps = { id, vista, p, set, ejecutar, ocupado: trabajando, recargar };
  const actual = PARADAS.find((x) => x.id === parada)!;
  const idx = PARADAS.findIndex((x) => x.id === parada);
  const sig = SIGUIENTE[parada];
  const materialListo = !!String(p("guion").material || "").trim();

  function estadoParada(x: (typeof PARADAS)[number]): EstadoEtapa {
    if (x.id === "material") return materialListo ? "ok" : "pendiente";
    return vista!.etapas[x.etapa].estado;
  }

  async function accionPrincipal() {
    if (sig.hasta) await ejecutar(sig.hasta);
    if (sig.ir) setParada(sig.ir);
  }

  return (
    <main className="mx-auto max-w-6xl px-4 pb-40 pt-6">
      <div className="mb-6 flex flex-wrap items-center gap-3">
        <Link href="/" className="boton boton-fantasma !px-2.5"><ArrowLeft size={16} /></Link>
        <input
          value={titulo}
          onChange={(e) => cambiarTitulo(e.target.value)}
          className="min-w-0 flex-1 bg-transparent font-display text-2xl font-semibold tracking-tight outline-none md:text-3xl"
          aria-label="Titulo del video"
        />
        <button className="boton boton-linea" disabled={trabajando || !materialListo} onClick={() => { ejecutar("render"); setParada("video"); }}>
          <Play size={15} /> Todo hasta el video
        </button>
      </div>

      {/* Etapas */}
      <ol className="mb-6 grid grid-cols-3 gap-2 md:grid-cols-6">
        {PARADAS.map((x, i) => {
          const est = estadoParada(x);
          const activa = x.id === parada;
          return (
            <li key={x.id}>
              <button
                onClick={() => setParada(x.id)}
                className={`w-full rounded-xl border p-3 text-left transition ${
                  activa ? "border-tinta bg-tarjeta shadow-sm" : "border-linea hover:border-tinta-3"
                }`}
              >
                <div className="flex items-center gap-2">
                  <span className={`grid h-6 w-6 shrink-0 place-items-center rounded-full text-xs font-bold ${
                    est === "ok" ? "bg-ok text-white"
                      : est === "ejecutando" ? "latido bg-acento text-white"
                      : est === "error" ? "bg-error text-white"
                      : est === "obsoleta" ? "bg-aviso text-white"
                      : "bg-hundido text-tinta-3"}`}>
                    {est === "ok" ? <Check size={13} strokeWidth={3} /> : i + 1}
                  </span>
                  <span className="truncate text-sm font-semibold">{x.titulo}</span>
                </div>
                <p className="mt-1 hidden truncate text-xs text-tinta-3 md:block">{x.sub}</p>
              </button>
            </li>
          );
        })}
      </ol>

      {error && (
        <p className="mb-4 flex items-start justify-between gap-3 rounded-xl bg-error-suave p-3 text-sm text-error">
          {error}
          <button onClick={() => setError("")}><X size={16} /></button>
        </p>
      )}

      <div className="mb-3 flex items-center gap-3">
        <h2 className="font-display text-xl font-semibold">{actual.titulo}</h2>
        {actual.id !== "material" && <ChipEstado estado={vista.etapas[actual.etapa].estado} />}
        {vista.etapas[actual.etapa].duracion_s != null && actual.id !== "material" && (
          <span className="text-xs text-tinta-3">ultima vez: {vista.etapas[actual.etapa].duracion_s}s</span>
        )}
      </div>

      {parada === "material" && <PanelMaterial {...props} />}
      {parada === "guion" && <PanelGuion {...props} />}
      {parada === "voz" && <PanelVoz {...props} />}
      {parada === "recursos" && <PanelRecursos {...props} />}
      {parada === "asignacion" && <PanelAsignacion {...props} />}
      {parada === "video" && <PanelVideo {...props} />}

      {/* Barra inferior: trabajo en curso + accion principal */}
      <div className="fixed inset-x-0 bottom-0 z-20 border-t border-linea bg-papel/95 backdrop-blur">
        {verLog && (
          <pre className="mx-auto max-h-64 max-w-6xl overflow-auto whitespace-pre-wrap px-4 py-3 font-mono text-xs leading-relaxed text-tinta-2">
            {vista.log.slice(-120).join("\n") || "Sin actividad todavia."}
          </pre>
        )}
        <div className="mx-auto flex max-w-6xl flex-wrap items-center gap-3 px-4 py-3">
          <button onClick={() => setVerLog((x) => !x)} className="boton boton-fantasma !px-2.5 text-xs">
            {verLog ? <ChevronDown size={14} /> : <ChevronUp size={14} />} Registro
          </button>
          {vista.trabajo ? (
            <div className="flex min-w-0 flex-1 items-center gap-3">
              <Loader2 size={16} className="shrink-0 animate-spin text-acento" />
              <div className="min-w-0 flex-1">
                <div className="flex justify-between gap-2 text-xs">
                  <span className="truncate font-medium">
                    {vista.trabajo.etapa ? NOMBRE_ETAPA[vista.trabajo.etapa] : "Preparando"} · {vista.trabajo.mensaje}
                  </span>
                  <span className="tabular-nums text-tinta-3">{vista.trabajo.progreso}%</span>
                </div>
                <div className="mt-1 h-1.5 overflow-hidden rounded-full bg-hundido">
                  <div className="h-full rounded-full bg-acento transition-all" style={{ width: `${vista.trabajo.progreso}%` }} />
                </div>
              </div>
              <button className="boton boton-linea !py-1.5 text-xs" onClick={() => api.cancelar(id).then(recargar)}>
                Cancelar
              </button>
            </div>
          ) : (
            <div className="flex flex-1 items-center justify-end gap-2">
              {idx > 0 && (
                <button className="boton boton-fantasma" onClick={() => setParada(PARADAS[idx - 1].id)}>
                  <ArrowLeft size={15} /> {PARADAS[idx - 1].titulo}
                </button>
              )}
              <button
                className="boton boton-acento"
                onClick={accionPrincipal}
                disabled={(parada === "material" && !materialListo) || (parada === "video" && vista.etapas.render.estado === "ok")}
              >
                {sig.texto} <ArrowRight size={15} />
              </button>
            </div>
          )}
        </div>
      </div>
    </main>
  );
}

function paradaDe(e: EtapaId): ParadaId {
  return e === "render" ? "video" : (e as ParadaId);
}
