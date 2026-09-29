"use client";

import { RefreshCw, Undo2 } from "lucide-react";
import type { PanelProps } from "../Proyecto";
import { AvisoError, Tarjeta } from "../ui";
import { mmss } from "@/lib/api";

export default function PanelGuion({ vista, p, set, ejecutar, ocupado }: PanelProps) {
  const et = vista.etapas.guion;
  const g = p("guion");
  const manual = typeof g.texto_manual === "string" && g.texto_manual.trim() !== "";
  const texto = manual ? (g.texto_manual as string) : et.salida?.texto || "";
  const palabras = texto.split(/\s+/).filter(Boolean).length;
  const pps = { es: 2.5, en: 2.6, pt: 2.4, de: 2.2 }[(g.idioma as string) || "es"] || 2.5;

  async function regenerar() {
    set("guion", "texto_manual", null);
    await ejecutar("guion", ["guion"]);
  }

  if (!et.salida && !manual) {
    return (
      <Tarjeta>
        <AvisoError texto={et.error} />
        <p className="text-tinta-2">
          Todavia no hay guion. Pulsa <b>Escribir guion</b> en el paso anterior, o escribelo tu mismo aqui abajo.
        </p>
        <textarea className="campo mt-4 min-h-[200px]" placeholder="Escribe el guion…" value=""
          onChange={(e) => set("guion", "texto_manual", e.target.value)} />
        <button className="boton boton-acento mt-3" disabled={ocupado} onClick={() => ejecutar("guion")}>
          Escribir guion con Claude
        </button>
      </Tarjeta>
    );
  }

  return (
    <div className="space-y-4">
      <AvisoError texto={et.error} />
      {et.estado === "obsoleta" && !manual && (
        <p className="rounded-xl bg-aviso-suave p-3 text-sm text-aviso">
          El material o las indicaciones cambiaron despues de escribir este guion.
        </p>
      )}
      <Tarjeta
        extra={
          <div className="flex gap-2">
            {manual && (
              <button className="boton boton-fantasma text-xs" onClick={() => set("guion", "texto_manual", null)}>
                <Undo2 size={14} /> Descartar mis cambios
              </button>
            )}
            <button className="boton boton-linea text-xs" disabled={ocupado} onClick={regenerar}>
              <RefreshCw size={14} /> Rehacer con Claude
            </button>
          </div>
        }
        titulo={manual ? "Guion (editado por ti)" : "Guion"}
      >
        <textarea
          className="campo min-h-[380px] text-[15px]"
          value={texto}
          onChange={(e) => set("guion", "texto_manual", e.target.value)}
        />
        <p className="mt-2 text-xs text-tinta-3">
          {palabras} palabras · ≈ {mmss(palabras / pps)} de voz · editar aqui guarda solo; la voz se rehara al continuar.
        </p>
      </Tarjeta>
    </div>
  );
}
