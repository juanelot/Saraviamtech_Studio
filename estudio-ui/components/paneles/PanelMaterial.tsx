"use client";

import type { PanelProps } from "../Proyecto";
import { ImageIcon } from "lucide-react";
import { Campo, Segmentado, Tarjeta } from "../ui";
import { mmss } from "@/lib/api";

export const MODELOS = [
  { v: "haiku", t: "Haiku (rapido)" },
  { v: "sonnet", t: "Sonnet (equilibrado)" },
  { v: "opus", t: "Opus (el mejor, lento)" },
];
export const ESFUERZOS = [
  { v: "low", t: "Bajo" },
  { v: "medium", t: "Medio" },
  { v: "high", t: "Alto" },
];

const DURACIONES = [30, 45, 60, 90, 120, 180, 300, 480, 600, 720, 900, 1200, 1800, 2700, 3600];
const MAX_MIN = 180;

export default function PanelMaterial({ p, set, irA }: PanelProps) {
  const g = p("guion");
  const modo = (g.modo as string) || "redactar";
  const dur = Number(g.duracion_s) || 60;
  return (
    <div className="grid gap-5 lg:grid-cols-[1.6fr_1fr]">
      <Tarjeta>
        <Campo
          etiqueta={modo === "literal" ? "Tu guion (se leera tal cual)" : "Material"}
          ayuda={modo === "literal"
            ? "Se usara exactamente este texto como locucion."
            : "Notas, un articulo pegado, una cronologia, datos sueltos... Claude solo usara hechos de aqui."}
        >
          <textarea
            className="campo min-h-[340px]"
            value={(g.material as string) || ""}
            onChange={(e) => set("guion", "material", e.target.value)}
            placeholder="Pega o escribe aqui de que trata el video…"
          />
        </Campo>
        <p className="mt-2 text-right text-xs text-tinta-3">
          {String(g.material || "").split(/\s+/).filter(Boolean).length} palabras
        </p>
      </Tarjeta>

      <div className="space-y-5">
        <Tarjeta titulo="Como contarlo">
          <div className="space-y-4">
            <Campo etiqueta="Guion">
              <Segmentado
                valor={modo}
                opciones={[{ v: "redactar", t: "Claude lo redacta" }, { v: "literal", t: "Usar mi texto" }]}
                onChange={(v) => set("guion", "modo", v)}
              />
            </Campo>
            {modo === "redactar" && (
              <>
                <Campo etiqueta="Duracion objetivo" ayuda={`Elige una o escribe los minutos (hasta ${MAX_MIN}). Los guiones largos tardan mas en escribirse.`}>
                  <div className="flex gap-2">
                    <select className="campo" value={DURACIONES.includes(dur) ? dur : "otra"}
                      onChange={(e) => e.target.value !== "otra" && set("guion", "duracion_s", Number(e.target.value))}>
                      {DURACIONES.map((d) => <option key={d} value={d}>{d < 3600 ? `${mmss(d)} min` : "1 hora"}</option>)}
                      {!DURACIONES.includes(dur) && <option value="otra">{mmss(dur)} min</option>}
                    </select>
                    <input type="number" min={0.5} max={MAX_MIN} step={0.5} className="campo !w-24" title="Minutos"
                      value={Math.round((dur / 60) * 10) / 10}
                      onChange={(e) => {
                        const m = Math.min(MAX_MIN, Math.max(0.5, Number(e.target.value) || 1));
                        set("guion", "duracion_s", Math.round(m * 60));
                      }} />
                  </div>
                </Campo>
                <Campo etiqueta="Indicaciones" ayuda="Tono, publico, gancho, que evitar…">
                  <textarea className="campo min-h-[96px]" value={(g.instrucciones as string) || ""}
                    onChange={(e) => set("guion", "instrucciones", e.target.value)}
                    placeholder="Ej.: tono curioso, para publico joven, termina con una pregunta" />
                </Campo>
              </>
            )}
            <Campo etiqueta="Idioma">
              <select className="campo" value={(g.idioma as string) || "es"} onChange={(e) => set("guion", "idioma", e.target.value)}>
                <option value="es">Espanol</option>
                <option value="en">Ingles</option>
                <option value="pt">Portugues</option>
                <option value="fr">Frances</option>
                <option value="it">Italiano</option>
                <option value="de">Aleman</option>
              </select>
            </Campo>
          </div>
        </Tarjeta>
        {modo === "redactar" && (
          <Tarjeta titulo="Claude">
            <div className="grid grid-cols-2 gap-3">
              <Campo etiqueta="Modelo">
                <select className="campo" value={(g.modelo as string) || "sonnet"} onChange={(e) => set("guion", "modelo", e.target.value)}>
                  {MODELOS.map((m) => <option key={m.v} value={m.v}>{m.t}</option>)}
                </select>
              </Campo>
              <Campo etiqueta="Esfuerzo">
                <select className="campo" value={(g.esfuerzo as string) || "low"} onChange={(e) => set("guion", "esfuerzo", e.target.value)}>
                  {ESFUERZOS.map((m) => <option key={m.v} value={m.v}>{m.t}</option>)}
                </select>
              </Campo>
            </div>
            <p className="mt-3 text-xs text-tinta-3">Usa tu suscripcion de Claude (CLI), sin API key.</p>
          </Tarjeta>
        )}
        <button type="button" onClick={() => irA("miniatura")}
          className="flex w-full items-start gap-3 rounded-2xl border border-dashed border-linea p-4 text-left transition hover:border-acento">
          <ImageIcon size={18} className="mt-0.5 shrink-0 text-acento" />
          <span className="text-sm">
            <b>¿Ya tienes la miniatura, o una de referencia?</b>
            <span className="mt-0.5 block text-tinta-2">Subela ahora en el paso Miniatura. Si no, al final Claude te propone conceptos y prompts.</span>
          </span>
        </button>
      </div>
    </div>
  );
}
