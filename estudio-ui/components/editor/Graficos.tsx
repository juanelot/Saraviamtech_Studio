"use client";

// Formulario de un grafico animado (HyperFrames): plantilla, textos, color, posicion y
// duracion. Al crear, el servidor lo renderiza transparente (~30 s, en cache si se
// repite) y el editor lo pone como una capa de video mas.

import { useEffect, useState } from "react";
import { Check, Loader2, Play, Sparkles, Wand2 } from "lucide-react";
import { Segmentado } from "../ui";
import { api, mmss, type DatosGrafico, type GraficoHecho, type IdeaGrafico, type PlantillaGrafico } from "@/lib/api";

export interface GraficoPuesto { hecho: GraficoHecho; datos: DatosGrafico; inicio: number }

// Claude lee lo que se dice y propone graficos para todo el video. Se marcan los que
// gustan y se crean uno tras otro; al terminar se ponen todos a la vez en la linea de
// tiempo (un solo deshacer los quita). Luego se cambian o se borran como cualquier capa.
export function IdeasGraficos({ id, onIr, onPoner }: {
  id: string; onIr: (t: number) => void; onPoner: (puestos: GraficoPuesto[]) => void;
}) {
  const [ideas, setIdeas] = useState<IdeaGrafico[]>([]);
  const [marcadas, setMarcadas] = useState<Set<string>>(new Set());
  const [puestas, setPuestas] = useState<Set<string>>(new Set());
  const [cuantos, setCuantos] = useState(6);
  const [pedido, setPedido] = useState("");
  const [pensando, setPensando] = useState(false);
  const [creando, setCreando] = useState("");
  const [error, setError] = useState("");
  useEffect(() => {
    api.ideasGraficos(id).then((r) => { setIdeas(r.ideas); setPedido(r.pedido || ""); setMarcadas(new Set(r.ideas.map((x) => x.id))); }).catch(() => {});
  }, [id]);

  async function proponer() {
    setPensando(true); setError("");
    try {
      const r = await api.proponerGraficos(id, { cuantos, pedido });
      setIdeas(r.ideas); setMarcadas(new Set(r.ideas.map((x) => x.id))); setPuestas(new Set());
    } catch (e) { setError(String((e as Error).message)); } finally { setPensando(false); }
  }

  async function poner() {
    const elegidas = ideas.filter((x) => marcadas.has(x.id) && !puestas.has(x.id));
    const hechos: GraficoPuesto[] = [];
    const fallos: string[] = [];
    setError("");
    for (const [k, x] of elegidas.entries()) {
      setCreando(`Creando ${k + 1} de ${elegidas.length} (unos 30 s cada uno)…`);
      const datos: DatosGrafico = { plantilla: x.plantilla, valores: x.valores, color: x.color, posicion: x.posicion };
      try {
        hechos.push({ hecho: await api.crearGrafico(id, { ...datos, duracion: x.duracion }), datos, inicio: x.inicio });
      } catch (e) { fallos.push(`${x.nombre} (${mmss(x.inicio)}): ${(e as Error).message}`); }
    }
    setCreando("");
    if (hechos.length) {
      onPoner(hechos);
      setPuestas((p) => new Set([...p, ...elegidas.filter((x) => hechos.some((h) => h.inicio === x.inicio && h.datos.plantilla === x.plantilla)).map((x) => x.id)]));
    }
    if (fallos.length) setError(`No se pudieron crear: ${fallos.join(" · ")}`);
  }

  const pendientes = ideas.filter((x) => marcadas.has(x.id) && !puestas.has(x.id)).length;
  const ocupado = pensando || !!creando;
  return (
    <div className="space-y-3">
      <p className="text-xs text-tinta-3">
        Claude lee lo que dice la voz y propone donde poner graficos, solo con datos que se dicen. Marca los que te gusten:
        se ponen en la linea de tiempo y luego los cambias o borras como cualquier capa.
      </p>
      <div className="flex items-center gap-2">
        <label className="flex flex-1 items-center gap-2 text-sm">
          <span className="shrink-0">Hasta {cuantos}</span>
          <input type="range" className="w-full accent-[var(--acento)]" min={1} max={15} value={cuantos} onChange={(e) => setCuantos(Number(e.target.value))} />
        </label>
      </div>
      <input className="campo !py-1.5 text-sm" placeholder="Que buscar (opcional): p. ej. solo las cifras" value={pedido} onChange={(e) => setPedido(e.target.value)} />
      <button className="boton boton-acento !px-3 !py-1.5 text-sm" disabled={ocupado} onClick={proponer}>
        {pensando ? <Loader2 size={14} className="animate-spin" /> : <Sparkles size={14} />} {pensando ? "Claude esta leyendo…" : ideas.length ? "Proponer otra vez" : "Proponer con Claude"}
      </button>
      {error && <p className="rounded-lg bg-error-suave p-2 text-xs text-error">{error}</p>}
      {ideas.length > 0 && (
        <ul className="space-y-1.5">
          {ideas.map((x) => {
            const puesta = puestas.has(x.id);
            return (
              <li key={x.id} data-idea-grafico={x.id} className={`rounded-lg border p-2 text-xs ${puesta ? "border-ok/50 bg-ok-suave" : "border-linea"}`}>
                <div className="flex items-start gap-2">
                  {puesta ? <Check size={15} className="mt-0.5 shrink-0 text-ok" /> : (
                    <input type="checkbox" className="mt-0.5 accent-[var(--acento)]" checked={marcadas.has(x.id)} disabled={ocupado}
                      onChange={(e) => setMarcadas((m) => { const n = new Set(m); if (e.target.checked) n.add(x.id); else n.delete(x.id); return n; })} />
                  )}
                  <div className="min-w-0 flex-1">
                    <p><b>{mmss(x.inicio)} · {x.nombre}</b>{puesta && <span className="text-ok"> · puesto</span>}</p>
                    <p className="mt-0.5 whitespace-pre-line text-tinta-2">{Object.values(x.valores).filter((v) => v.trim()).join(" · ").replace(/\*/g, "").replace(/\s*\/\s*/g, " ")}</p>
                    {x.motivo && <p className="mt-0.5 text-tinta-3">{x.motivo}</p>}
                  </div>
                  <button className="shrink-0 rounded p-1 hover:bg-linea" title={`Ir a «${x.frase}»`} onClick={() => onIr(x.inicio)}><Play size={13} /></button>
                </div>
              </li>
            );
          })}
        </ul>
      )}
      {pendientes > 0 && (
        <button className="boton boton-acento !px-3 !py-1.5 text-sm" disabled={ocupado} onClick={poner}>
          {creando ? <Loader2 size={14} className="animate-spin" /> : <Wand2 size={14} />} {creando || `Poner ${pendientes} en el video`}
        </button>
      )}
    </div>
  );
}

let catalogo: Promise<{ plantillas: PlantillaGrafico[]; falta: string }> | null = null;
const cargarCatalogo = () => (catalogo ??= api.plantillasGraficos().catch((e) => { catalogo = null; throw e; }));

export function FormGrafico({ id, inicial, duracion, boton, onListo, onCancelar }: {
  id: string; inicial?: DatosGrafico; duracion?: number; boton: string;
  onListo: (hecho: GraficoHecho, datos: DatosGrafico) => void; onCancelar?: () => void;
}) {
  const [lista, setLista] = useState<PlantillaGrafico[]>([]);
  const [falta, setFalta] = useState("");
  const [plantilla, setPlantilla] = useState(inicial?.plantilla || "titulo");
  const [valores, setValores] = useState<Record<string, string>>(inicial?.valores || {});
  const [color, setColor] = useState(inicial?.color || "");
  const [posicion, setPosicion] = useState(inicial?.posicion || "");
  const [dur, setDur] = useState(duracion || 0);
  const [ocupado, setOcupado] = useState(false);
  const [error, setError] = useState("");
  useEffect(() => { cargarCatalogo().then((c) => { setLista(c.plantillas); setFalta(c.falta); }).catch((e) => setError(String(e.message))); }, []);

  const pl = lista.find((x) => x.id === plantilla);
  if (falta) return <p className="rounded-lg bg-aviso/15 p-3 text-sm">Los graficos animados no estan disponibles: {falta}.</p>;
  if (!pl) return error ? <p className="text-sm text-error">{error}</p> : <Loader2 className="animate-spin text-tinta-3" />;
  const colorVisto = color || pl.color || "#FFD447";
  const posVista = posicion || pl.posicion;
  const durVista = dur || pl.dur;

  async function crear() {
    if (!pl) return;
    setOcupado(true); setError("");
    const datos: DatosGrafico = {
      plantilla, color: colorVisto, posicion: posVista,
      valores: Object.fromEntries(pl.campos.map((c) => [c.id, valores[c.id] ?? c.defecto])),
    };
    try {
      onListo(await api.crearGrafico(id, { ...datos, duracion: durVista }), datos);
    } catch (e) { setError(String((e as Error).message)); } finally { setOcupado(false); }
  }

  return (
    <div className="space-y-3">
      <div className="grid grid-cols-2 gap-1.5">
        {lista.map((x) => (
          <button key={x.id} onClick={() => setPlantilla(x.id)} title={x.descripcion}
            className={`rounded-lg border px-2 py-1.5 text-left text-xs ${x.id === plantilla ? "border-acento bg-acento-suave text-acento" : "border-linea hover:border-acento/60"}`}>
            <b className="block">{x.nombre}</b>
          </button>
        ))}
      </div>
      <p className="text-xs text-tinta-3">{pl.descripcion}</p>
      {pl.campos.map((c) => (
        <label key={c.id} className="block">
          <span className="etiqueta">{c.etiqueta}</span>
          {c.lineas ? (
            <textarea className="campo mt-1 !py-1.5 text-sm" rows={4} value={valores[c.id] ?? c.defecto}
              onChange={(e) => setValores((v) => ({ ...v, [c.id]: e.target.value }))} />
          ) : (
            <input className="campo mt-1 !py-1.5 text-sm" value={valores[c.id] ?? c.defecto}
              onChange={(e) => setValores((v) => ({ ...v, [c.id]: e.target.value }))} />
          )}
        </label>
      ))}
      <div className="flex items-center gap-3">
        <label className="flex items-center gap-2 text-sm">
          Color
          <input type="color" className="h-8 w-12 cursor-pointer rounded border border-linea bg-tarjeta" value={colorVisto} onChange={(e) => setColor(e.target.value)} />
        </label>
        <label className="flex flex-1 items-center gap-2 text-sm">
          <span className="shrink-0">{durVista.toFixed(1)} s</span>
          <input type="range" className="w-full accent-[var(--acento)]" min={1.5} max={12} step={0.5} value={durVista} onChange={(e) => setDur(Number(e.target.value))} />
        </label>
      </div>
      <Segmentado valor={posVista} onChange={setPosicion}
        opciones={[{ v: "arriba", t: "Arriba" }, { v: "centro", t: "Centro" }, { v: "abajo", t: "Abajo" }]} />
      {error && <p className="rounded-lg bg-error-suave p-2 text-xs text-error">{error}</p>}
      <div className="flex gap-1.5">
        <button className="boton boton-acento !px-3 !py-1.5 text-sm" disabled={ocupado} onClick={crear}>
          {ocupado ? <Loader2 size={14} className="animate-spin" /> : <Wand2 size={14} />} {ocupado ? "Renderizando (unos 30 s)…" : boton}
        </button>
        {onCancelar && <button className="boton boton-fantasma !px-3 !py-1.5 text-sm" disabled={ocupado} onClick={onCancelar}>Cancelar</button>}
      </div>
    </div>
  );
}
