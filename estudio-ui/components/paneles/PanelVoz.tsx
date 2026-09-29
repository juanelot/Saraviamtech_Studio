"use client";

import { useMemo, useState } from "react";
import type { PanelProps } from "../Proyecto";
import { AvisoError, Campo, Deslizador, Tarjeta } from "../ui";
import { AZURE_VOICES } from "@/lib/voces";
import { mmss, url } from "@/lib/api";

export default function PanelVoz({ id, vista, p, set, ejecutar, ocupado }: PanelProps) {
  const et = vista.etapas.voz;
  const v = p("voz");
  const voz = (v.voz as string) || "es-ES-AlvaroNeural-Male";
  const [idioma, setIdioma] = useState(() => voz.split("-").slice(0, 2).join("-"));
  const idiomas = useMemo(() => Array.from(new Set(AZURE_VOICES.map((x) => x.lang))).sort(), []);
  const voces = AZURE_VOICES.filter((x) => x.lang === idioma);

  return (
    <div className="grid gap-5 lg:grid-cols-[1fr_1.3fr]">
      <Tarjeta titulo="Voz">
        <div className="space-y-4">
          <div className="grid grid-cols-2 gap-3">
            <Campo etiqueta="Idioma">
              <select className="campo" value={idioma} onChange={(e) => setIdioma(e.target.value)}>
                {idiomas.map((l) => <option key={l} value={l}>{l}</option>)}
              </select>
            </Campo>
            <Campo etiqueta="Locutor">
              <select className="campo" value={voz} onChange={(e) => set("voz", "voz", e.target.value)}>
                {!voces.some((x) => x.value === voz) && <option value={voz}>{voz}</option>}
                {voces.map((x) => (
                  <option key={x.value} value={x.value}>
                    {x.value.split("-")[2].replace("Neural", "")} · {x.gender === "Female" ? "mujer" : "hombre"}
                  </option>
                ))}
              </select>
            </Campo>
          </div>
          <Campo etiqueta="Velocidad">
            <Deslizador valor={Number(v.velocidad) || 1} min={0.7} max={1.5} paso={0.05}
              onChange={(x) => set("voz", "velocidad", x)} formato={(x) => `${x.toFixed(2)}×`} />
          </Campo>
          <div className="border-t border-linea pt-4">
            <p className="etiqueta mb-2">Planos</p>
            <p className="mb-3 text-xs text-tinta-3">
              La narracion se corta en planos por sus pausas; cada plano lleva un recurso.
            </p>
            <Campo etiqueta="Duracion minima de un plano">
              <Deslizador valor={Number(v.plano_min_s) || 2.5} min={1} max={8} paso={0.5}
                onChange={(x) => set("voz", "plano_min_s", x)} formato={(x) => `${x}s`} />
            </Campo>
            <Campo etiqueta="Duracion maxima de un plano" className="mt-3">
              <Deslizador valor={Number(v.plano_max_s) || 6} min={2} max={15} paso={0.5}
                onChange={(x) => set("voz", "plano_max_s", x)} formato={(x) => `${x}s`} />
            </Campo>
          </div>
          <button className="boton boton-linea" disabled={ocupado} onClick={() => ejecutar("voz")}>
            {et.salida ? "Volver a sintetizar" : "Sintetizar voz"}
          </button>
        </div>
      </Tarjeta>

      <div className="space-y-4">
        <AvisoError texto={et.error} />
        {et.salida ? (
          <>
            <Tarjeta titulo="Escuchar" extra={<span className="text-sm text-tinta-3">{mmss(et.salida.duracion)}</span>}>
              <audio controls className="w-full" src={url.archivo(id, et.salida.audio, et.terminado)} />
            </Tarjeta>
            <Tarjeta titulo={`${et.salida.planos.length} planos`}>
              <ol className="max-h-[420px] space-y-1.5 overflow-auto pr-1">
                {et.salida.planos.map((x) => (
                  <li key={x.i} className="flex gap-3 rounded-lg px-2 py-1.5 text-sm hover:bg-hundido">
                    <span className="w-20 shrink-0 tabular-nums text-xs text-tinta-3">
                      {mmss(x.inicio)} · {(x.fin - x.inicio).toFixed(1)}s
                    </span>
                    <span>{x.texto}</span>
                  </li>
                ))}
              </ol>
            </Tarjeta>
          </>
        ) : (
          <Tarjeta><p className="text-tinta-2">Elige la voz y sintetiza para escucharla y ver los planos.</p></Tarjeta>
        )}
      </div>
    </div>
  );
}
