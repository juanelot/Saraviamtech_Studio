"use client";

// Clips de Veo (Google Flow, solo en el PC): cada escena con imagen y prompt de video pasa a ser un clip de 8 s que
// empieza en esa imagen. Van a recursos/videos/scene_NNNN.mp4 y ganan a la imagen de la escena al asignar.
import { useCallback, useEffect, useState } from "react";
import { Clapperboard, Loader2, Play, Square } from "lucide-react";
import { Tarjeta } from "../ui";
import { flow, type EstadoVeo } from "@/lib/api";

const CASILLA: Record<string, string> = {
  lista: "bg-ok text-white",
  pendiente: "bg-hundido text-tinta-3",
  error: "bg-error text-white",
  en_curso: "bg-acento text-sobre-acento",
  sin_prompt: "bg-hundido text-tinta-3 opacity-40",
  sin_imagen: "bg-hundido text-tinta-3 opacity-40",
};
const TITULO: Record<string, string> = {
  lista: "tiene video", pendiente: "pendiente", error: "fallo", en_curso: "haciendose",
  sin_prompt: "sin prompt de video", sin_imagen: "primero necesita su imagen",
};
const RESULTADO: Record<string, string> = {
  detenido: "Detenido. Lo que falta sigue pendiente.",
  sin_creditos: "Se acabaron los creditos de video en todas las cuentas de Flow. Se renuevan cada dia.",
  sin_sesion: "Ninguna cuenta de Flow tiene la sesion iniciada (Configuracion > Google Flow).",
  inusual: "Google detecto actividad inusual y se paro. Prueba mas tarde: lo hecho no se pierde.",
};

export default function GenerarVeo({ id, alCambiar }: { id: string; alCambiar: () => void }) {
  const [est, setEst] = useState<EstadoVeo | null>(null);
  const [error, setError] = useState("");
  const [enviando, setEnviando] = useState(false);

  const leer = useCallback(async () => {
    try {
      const e = await flow.videos(id);
      setEst((antes) => { if (antes && antes.cuenta.lista !== e.cuenta.lista) alCambiar(); return e; });
      setError("");
    } catch (e) {
      setError(String((e as Error).message));
    }
  }, [id, alCambiar]);

  useEffect(() => { flow.info().then((i) => { if (i.habilitado) leer(); }).catch(() => {}); }, [leer]);
  useEffect(() => {
    if (!est?.corriendo) return;
    const t = setInterval(leer, 4000);
    return () => clearInterval(t);
  }, [est?.corriendo, leer]);

  if (!est) return error && !error.includes("habilitado") ? <p className="text-xs text-error">{error}</p> : null;
  const c = est.cuenta;
  const faltan = c.pendiente + c.error;

  async function hacer(fn: () => Promise<unknown>) {
    setEnviando(true); setError("");
    try { await fn(); await leer(); } catch (e) { setError(String((e as Error).message)); } finally { setEnviando(false); }
  }

  return (
    <Tarjeta titulo="Videos con Veo (Google Flow)">
      <div className="space-y-3">
        <p className="text-sm text-tinta-2">
          Cada escena con imagen y prompt de video se convierte en un clip de 8 s que empieza en esa imagen
          (10 creditos por clip). <b>{c.lista}</b> con video
          {c.sin_imagen ? <> · {c.sin_imagen} esperan su imagen</> : null}
          {est.clips_disponibles != null ? <> · quedan unos <b>{est.clips_disponibles}</b> clips en tus cuentas</> : null}
        </p>
        <div className="flex flex-wrap items-center gap-2">
          {est.corriendo ? (
            <>
              <span className="inline-flex items-center gap-2 text-sm font-medium">
                <Loader2 size={15} className="animate-spin text-acento" /> {est.mensaje || "Trabajando…"}
              </span>
              <button className="boton boton-linea text-sm" disabled={enviando} onClick={() => hacer(() => flow.detener(id))}>
                <Square size={14} /> Detener
              </button>
            </>
          ) : (
            <button className="boton boton-acento" disabled={enviando || !faltan || est.otro} onClick={() => hacer(() => flow.generarVideos(id))}>
              {enviando ? <Loader2 size={15} className="animate-spin" /> : est.resultado ? <Play size={15} /> : <Clapperboard size={15} />}
              {!faltan ? "No hay escenas pendientes" : `Hacer videos con Veo (${faltan})`}
            </button>
          )}
          {est.otro && <span className="text-sm text-aviso">Flow esta trabajando en otra cosa.</span>}
        </div>
        <p className="text-xs text-tinta-3">
          Va despacio a proposito (unos 3-5 min por clip con pausas): si Google ve peticiones seguidas avisa de
          &quot;actividad inusual&quot;. Las escenas sin clip se quedan con su imagen.
        </p>
        {!est.corriendo && est.resultado && RESULTADO[est.resultado] && (
          <p className="rounded-xl bg-aviso-suave p-3 text-sm text-aviso">{RESULTADO[est.resultado]}</p>
        )}
        {!est.corriendo && est.resultado === "error" && (
          <p className="rounded-xl bg-error-suave p-3 text-sm text-error">Fallo: {est.motivo}</p>
        )}
        <div className="flex flex-wrap gap-1.5">
          {est.escenas.map((e) => (
            <span key={e.escena} title={`Escena ${e.escena}: ${TITULO[e.estado] || e.estado}${e.motivo ? ` — ${e.motivo}` : ""}`}
              className={`flex h-7 w-7 items-center justify-center rounded-md text-xs font-semibold ${CASILLA[e.estado] || ""}`}>
              {e.escena}
            </span>
          ))}
        </div>
        {error && <p className="text-xs text-error">{error}</p>}
      </div>
    </Tarjeta>
  );
}
