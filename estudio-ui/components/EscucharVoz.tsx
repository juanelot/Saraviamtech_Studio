"use client";

// Boton para escuchar unos segundos de una voz de Gemini antes de elegirla. La primera vez tarda unos segundos (se
// genera); despues sale al momento (queda guardada en el servidor).
import { useEffect, useRef, useState } from "react";
import { Loader2, Play, Square } from "lucide-react";
import { fabrica } from "@/lib/api";

export default function EscucharVoz({ voz, idioma = "espanol" }: { voz: string; idioma?: string }) {
  const [estado, setEstado] = useState<"quieto" | "cargando" | "sonando">("quieto");
  const [error, setError] = useState<string | null>(null);
  const audio = useRef<HTMLAudioElement | null>(null);

  // al cambiar de voz se para la que sonaba
  useEffect(() => () => { audio.current?.pause(); }, [voz]);
  useEffect(() => { audio.current?.pause(); setEstado("quieto"); setError(null); }, [voz, idioma]);

  async function escuchar() {
    if (estado === "sonando") {
      audio.current?.pause();
      setEstado("quieto");
      return;
    }
    setError(null);
    setEstado("cargando");
    try {
      const r = await fetch(fabrica.urlMuestraVoz(voz, idioma));
      if (!r.ok) {
        const j = await r.json().catch(() => null);
        throw new Error(j?.detail || `no se pudo (${r.status})`);
      }
      const url = URL.createObjectURL(await r.blob());
      audio.current?.pause();
      const a = new Audio(url);
      audio.current = a;
      a.onended = () => setEstado("quieto");
      await a.play();
      setEstado("sonando");
    } catch (e) {
      setError((e as Error).message);
      setEstado("quieto");
    }
  }

  return (
    <span className="inline-flex flex-col">
      <button type="button" className="boton boton-linea !px-3" onClick={escuchar} disabled={estado === "cargando"}
        title={estado === "sonando" ? "Parar" : "Escuchar unos segundos de esta voz"}>
        {estado === "cargando" ? <Loader2 size={15} className="animate-spin" /> : estado === "sonando" ? <Square size={14} /> : <Play size={15} />}
        <span className="text-xs">{estado === "cargando" ? "Generando…" : estado === "sonando" ? "Parar" : "Escuchar"}</span>
      </button>
      {error && <span className="mt-1 max-w-56 text-xs text-error">{error}</span>}
    </span>
  );
}
