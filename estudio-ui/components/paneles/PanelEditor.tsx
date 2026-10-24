"use client";

// Paso Editor: el editor de linea de tiempo sobre lo que dejo Ajuste. Es
// opcional: "Todo hasta el video" no se detiene aqui, pero lo que se edite
// aqui es lo que se monta.

import { useState } from "react";
import { Sparkles } from "lucide-react";
import type { PanelProps } from "../Proyecto";
import { AvisoError } from "../ui";
import type { Plano, Recurso } from "@/lib/api";
import Editor from "../editor/Editor";
import { Selector } from "./PanelAsignacion";

export default function PanelEditor(props: PanelProps) {
  const { vista, ejecutar, ocupado, irA } = props;
  const et = vista.etapas.asignacion;
  const recursos = vista.etapas.recursos.salida?.recursos || [];
  const [eligiendo, setEligiendo] = useState<{ plano: Plano; alElegir: (r: Recurso | null) => void } | null>(null);

  if (!et.salida) {
    return (
      <div className="grid place-items-center gap-3 rounded-2xl border border-linea bg-tarjeta py-20 text-center text-tinta-2">
        <p>Primero hay que repartir el contenido entre las frases (paso Ajuste).</p>
        <div className="flex gap-2">
          <button className="boton boton-linea" onClick={() => irA("asignacion")}>Ir a Ajuste</button>
          <button className="boton boton-acento" disabled={ocupado} onClick={() => ejecutar("asignacion")}>
            <Sparkles size={15} /> Asignar ahora
          </button>
        </div>
      </div>
    );
  }

  return (
    <div className="space-y-3">
      <AvisoError texto={et.error} />
      <Editor {...props} elegirClip={(plano, alElegir) => setEligiendo({ plano, alElegir })} />
      {eligiendo && (
        <Selector
          plano={eligiendo.plano}
          recursos={recursos}
          actual={eligiendo.plano.recurso}
          onElegir={(rid) => { eligiendo.alElegir(recursos.find((r) => r.id === rid) || null); setEligiendo(null); }}
          onCerrar={() => setEligiendo(null)}
        />
      )}
    </div>
  );
}
