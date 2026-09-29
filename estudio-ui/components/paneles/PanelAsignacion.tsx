"use client";

import { useState } from "react";
import { Film, Pin, PinOff, Sparkles, X } from "lucide-react";
import type { PanelProps } from "../Proyecto";
import { AvisoError, Campo, Segmentado, Tarjeta } from "../ui";
import { mini, mmss, url, type Plano, type Recurso } from "@/lib/api";
import { ESFUERZOS, MODELOS } from "./PanelMaterial";

export default function PanelAsignacion({ vista, p, set, ejecutar, ocupado }: PanelProps) {
  const et = vista.etapas.asignacion;
  const a = p("asignacion");
  const recursos = vista.etapas.recursos.salida?.recursos || [];
  const porId = new Map(recursos.map((r) => [r.id, r]));
  const fijados = (a.fijados as Record<string, string>) || {};
  const [eligiendo, setEligiendo] = useState<Plano | null>(null);
  const modo = (a.modo as string) || "claude";

  function fijar(i: number, rid: string | null) {
    const nuevo = { ...fijados };
    if (rid) nuevo[String(i)] = rid;
    else delete nuevo[String(i)];
    set("asignacion", "fijados", nuevo);
    setEligiendo(null);
  }

  const pendientesDeAplicar = et.estado === "obsoleta" && et.salida;

  return (
    <div className="space-y-5">
      <AvisoError texto={et.error} />
      <div className="grid gap-5 lg:grid-cols-[1.4fr_1fr]">
        <Tarjeta titulo="Como elegir">
          <div className="space-y-4">
            <Segmentado
              valor={modo}
              opciones={[
                { v: "escenas", t: "Por escenas (Flow)" },
                { v: "claude", t: "Claude elige" },
                { v: "orden", t: "En orden de archivo" },
              ]}
              onChange={(v) => set("asignacion", "modo", v)}
            />
            {modo === "escenas" && (
              <Campo etiqueta="Si una escena tiene imagen y video" ayuda="Cada escena usa el archivo con su numero (de Contenido).">
                <Segmentado
                  valor={(a.preferir as string) || "video"}
                  opciones={[{ v: "video", t: "Usar el video" }, { v: "imagen", t: "Usar la imagen" }]}
                  onChange={(v) => set("asignacion", "preferir", v)}
                />
              </Campo>
            )}
            {modo === "claude" && (
              <Campo etiqueta="Criterio (opcional)" ayuda="Ej.: usa los videos en los momentos de accion; el logo solo al final.">
                <textarea className="campo min-h-[70px]" value={(a.criterio as string) || ""}
                  onChange={(e) => set("asignacion", "criterio", e.target.value)} />
              </Campo>
            )}
          </div>
        </Tarjeta>
        {modo === "claude" && (
          <Tarjeta titulo="Claude">
            <div className="grid grid-cols-2 gap-3">
              <Campo etiqueta="Modelo">
                <select className="campo" value={(a.modelo as string) || "sonnet"} onChange={(e) => set("asignacion", "modelo", e.target.value)}>
                  {MODELOS.map((m) => <option key={m.v} value={m.v}>{m.t}</option>)}
                </select>
              </Campo>
              <Campo etiqueta="Esfuerzo">
                <select className="campo" value={(a.esfuerzo as string) || "low"} onChange={(e) => set("asignacion", "esfuerzo", e.target.value)}>
                  {ESFUERZOS.map((m) => <option key={m.v} value={m.v}>{m.t}</option>)}
                </select>
              </Campo>
            </div>
          </Tarjeta>
        )}
      </div>

      {!!et.salida?.faltan?.length && (
        <p className="rounded-xl bg-aviso-suave p-3 text-sm text-aviso">
          Escenas sin archivo: {et.salida.faltan.join(", ")}. Se repite el contenido anterior; sube los que faltan en Contenido o fija uno a mano.
        </p>
      )}

      <div className="flex flex-wrap items-center justify-between gap-3">
        <p className="text-sm text-tinta-2">
          {et.salida
            ? `${et.salida.planos.length} ${modo === "escenas" ? "escenas" : "planos"} · ${et.salida.recursos_usados} de ${recursos.length} archivos usados · ${Object.keys(fijados).length} fijados a mano`
            : "Todavia sin asignar."}
        </p>
        <button className={`boton ${pendientesDeAplicar ? "boton-acento" : "boton-linea"}`} disabled={ocupado} onClick={() => ejecutar("asignacion")}>
          <Sparkles size={15} /> {et.salida ? (pendientesDeAplicar ? "Aplicar cambios" : "Volver a asignar") : "Asignar planos"}
        </button>
      </div>

      {et.salida && (
        <ol className="space-y-2">
          {et.salida.planos.map((x) => {
            const rid = fijados[String(x.i)] || x.recurso!;
            const r = porId.get(rid);
            const fijo = !!fijados[String(x.i)];
            return (
              <li key={x.i} className="flex gap-3 rounded-xl border border-linea bg-tarjeta p-2.5">
                <button onClick={() => setEligiendo(x)} className="relative h-20 w-28 shrink-0 overflow-hidden rounded-lg bg-hundido" title="Cambiar recurso">
                  {r && (
                    // eslint-disable-next-line @next/next/no-img-element
                    <img src={url.miniatura(mini(r))} alt="" className="h-full w-full object-cover" />
                  )}
                  {r?.tipo === "video" && <Film size={13} className="absolute left-1.5 top-1.5 text-white drop-shadow" />}
                </button>
                <div className="min-w-0 flex-1">
                  <div className="flex items-center gap-2 text-xs text-tinta-3">
                    <span className="font-semibold text-tinta-2">{x.escena ? `Escena ${x.escena}` : `#${x.i + 1}`}</span>
                    <span className="tabular-nums">{mmss(x.inicio)} · {(x.fin - x.inicio).toFixed(1)}s</span>
                    {fijo && <span className="inline-flex items-center gap-1 rounded-full bg-acento-suave px-2 text-acento"><Pin size={10} /> fijado</span>}
                  </div>
                  <p className="mt-0.5 text-sm">{x.texto}</p>
                  <p className="mt-0.5 truncate text-xs text-tinta-3">
                    {r?.nombre} {!fijo && x.motivo ? `· ${x.motivo}` : ""}
                  </p>
                </div>
                <div className="flex shrink-0 flex-col gap-1">
                  <button className="boton boton-linea !px-2.5 !py-1 text-xs" onClick={() => setEligiendo(x)}>Cambiar</button>
                  {fijo && (
                    <button className="boton boton-fantasma !px-2.5 !py-1 text-xs" onClick={() => fijar(x.i, null)}>
                      <PinOff size={12} /> Soltar
                    </button>
                  )}
                </div>
              </li>
            );
          })}
        </ol>
      )}

      {eligiendo && (
        <Selector
          plano={eligiendo}
          recursos={recursos}
          actual={fijados[String(eligiendo.i)] || eligiendo.recurso}
          onElegir={(rid) => fijar(eligiendo.i, rid)}
          onCerrar={() => setEligiendo(null)}
        />
      )}
    </div>
  );
}

function Selector({ plano, recursos, actual, onElegir, onCerrar }: {
  plano: Plano; recursos: Recurso[]; actual?: string;
  onElegir: (rid: string) => void; onCerrar: () => void;
}) {
  const [filtro, setFiltro] = useState("");
  const f = filtro.toLowerCase();
  const lista = recursos.filter((r) => !f || r.nombre.toLowerCase().includes(f) || r.descripcion.toLowerCase().includes(f));
  return (
    <div className="fixed inset-0 z-40 grid place-items-center bg-black/50 p-4" onClick={onCerrar}>
      <div className="flex max-h-[85vh] w-full max-w-4xl flex-col rounded-2xl bg-tarjeta p-5 shadow-xl" onClick={(e) => e.stopPropagation()}>
        <div className="mb-3 flex items-start justify-between gap-3">
          <div>
            <p className="etiqueta">Plano #{plano.i + 1}</p>
            <p className="mt-1 text-sm">{plano.texto}</p>
          </div>
          <button onClick={onCerrar} className="boton boton-fantasma !p-2"><X size={16} /></button>
        </div>
        <input className="campo mb-3" placeholder="Buscar por nombre o descripcion…" value={filtro} onChange={(e) => setFiltro(e.target.value)} autoFocus />
        <ul className="grid flex-1 grid-cols-2 gap-3 overflow-auto sm:grid-cols-3 md:grid-cols-4">
          {lista.map((r) => (
            <li key={r.id}>
              <button
                onClick={() => onElegir(r.id)}
                className={`w-full overflow-hidden rounded-xl border text-left transition hover:border-acento ${r.id === actual ? "border-acento ring-2 ring-acento-suave" : "border-linea"}`}
              >
                {/* eslint-disable-next-line @next/next/no-img-element */}
                <img src={url.miniatura(mini(r))} alt="" className="aspect-[4/3] w-full bg-hundido object-cover" />
                <p className="line-clamp-3 p-2 text-xs text-tinta-2">{r.descripcion || r.nombre}</p>
              </button>
            </li>
          ))}
        </ul>
      </div>
    </div>
  );
}
