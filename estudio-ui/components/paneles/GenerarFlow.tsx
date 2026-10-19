"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { Check, Loader2, LogIn, Play, Square, Wand2, X } from "lucide-react";
import { Tarjeta } from "../ui";
import { flow, type EscenaFlow, type EstadoFlow } from "@/lib/api";

// Solo aparece si el backend tiene estudio_flow_habilitado (maquina local).
// El archivo manda: una escena con imagen subida o generada esta lista.
const SEG_POR_IMAGEN = 35;

const CASILLA: Record<EscenaFlow["estado"], string> = {
  lista: "bg-ok text-white",
  pendiente: "bg-hundido text-tinta-3",
  error: "bg-error text-white",
  en_curso: "bg-acento text-sobre-acento",
  sin_prompt: "bg-hundido text-tinta-3 opacity-40",
};

const RESULTADO: Record<string, string> = {
  detenido: "Detenido. Lo que falta sigue pendiente: pulsa Continuar cuando quieras.",
  limite: "Flow avisó de un límite de uso y se pausó el lote. Continúa más tarde: lo hecho no se pierde.",
  sin_sesion: "El Chrome de Flow no tiene sesión de Google. Pulsa \"Conectar Flow\", inicia sesión y continúa.",
};

function duracion(seg: number) {
  const m = Math.round(seg / 60);
  return m < 60 ? `~${Math.max(1, m)} min` : `~${Math.floor(m / 60)} h ${m % 60} min`;
}

export default function GenerarFlow({ id, alCambiar }: { id: string; alCambiar: () => void }) {
  const [habilitado, setHabilitado] = useState(false);
  const [est, setEst] = useState<EstadoFlow | null>(null);
  const [error, setError] = useState("");
  const [enviando, setEnviando] = useState(false);
  const listas = useRef<number | null>(null);

  const leer = useCallback(async () => {
    try {
      const e = await flow.estado(id);
      setEst(e);
      setError("");
      // Cada imagen nueva aparece en la lista de archivos sin esperar al final.
      if (listas.current !== null && e.cuenta.lista !== listas.current) alCambiar();
      listas.current = e.cuenta.lista;
    } catch (e) {
      setEst(null);
      setError(String((e as Error).message));
    }
  }, [id, alCambiar]);

  useEffect(() => {
    flow.info().then((i) => { setHabilitado(i.habilitado); if (i.habilitado) leer(); }).catch(() => setHabilitado(false));
  }, [leer]);

  const corriendo = !!est?.corriendo;
  useEffect(() => {
    if (!corriendo) return;
    const t = setInterval(leer, 3000);
    return () => clearInterval(t);
  }, [corriendo, leer]);

  if (!habilitado) return null;

  async function accion(fn: () => Promise<unknown>) {
    setEnviando(true);
    setError("");
    try {
      await fn();
      await leer();
    } catch (e) {
      setError(String((e as Error).message));
    } finally {
      setEnviando(false);
    }
  }

  if (!est) {
    return (
      <Tarjeta titulo="Generar en Google Flow">
        <p className="text-sm text-tinta-3">{error.includes("escenas") ? "Primero ejecuta el paso Escenas: de ahí salen los prompts." : error || "Cargando…"}</p>
      </Tarjeta>
    );
  }

  const c = est.cuenta;
  const faltan = c.pendiente + c.error + c.en_curso;
  const conPrompt = est.escenas.length - c.sin_prompt;
  const enCurso = est.escenas.find((e) => e.estado === "en_curso");

  return (
    <Tarjeta
      titulo="Generar en Google Flow"
      extra={
        <button className="boton boton-linea text-xs" disabled={enviando} onClick={() => accion(flow.conectar)}
          title="Abre el Chrome de Flow (perfil propio) para iniciar sesión con tu cuenta de Google">
          <LogIn size={13} /> Conectar Flow
        </button>
      }
    >
      <div className="space-y-3">
        <p className="text-sm text-tinta-2">
          Nano Banana gratis en tu Chrome de Flow: una imagen por escena, directa a esta lista.
          {" "}<b>{c.lista}</b> de {conPrompt} listas
          {c.error ? <> · <span className="text-error">{c.error} fallidas</span></> : null}
          {faltan && !corriendo ? ` · ${duracion(faltan * SEG_POR_IMAGEN)} para las ${faltan} que faltan` : ""}
        </p>

        <div className="flex flex-wrap items-center gap-2">
          {corriendo ? (
            <>
              <span className="inline-flex items-center gap-2 text-sm font-medium">
                <Loader2 size={15} className="animate-spin text-acento" />
                {est.deteniendo ? "Deteniendo… termina la imagen en curso" :
                  enCurso ? `Escena ${enCurso.escena}${enCurso.intento && enCurso.intento > 1 ? ` (intento ${enCurso.intento})` : ""}` : "Preparando Flow…"}
                {est.pasada && est.pasada > 1 ? ` · repaso ${est.pasada - 1}` : ""}
                {faltan ? ` · quedan ${faltan} (${duracion(faltan * SEG_POR_IMAGEN)})` : ""}
              </span>
              {!est.deteniendo ? (
                <button className="boton boton-linea text-sm" disabled={enviando} onClick={() => accion(() => flow.detener(id))}>
                  <Square size={14} /> Detener
                </button>
              ) : (
                <button className="boton boton-linea text-sm" disabled={enviando} onClick={() => accion(() => flow.detener(id, true))}
                  title="Corta ya: la escena en curso queda pendiente">
                  <X size={14} /> Cortar ya
                </button>
              )}
            </>
          ) : (
            <button className="boton boton-acento" disabled={enviando || !faltan || est.otro_proyecto}
              onClick={() => accion(() => flow.generar(id))}>
              {enviando ? <Loader2 size={15} className="animate-spin" /> : est.resultado ? <Play size={15} /> : <Wand2 size={15} />}
              {!faltan ? "Todas las escenas tienen imagen" : `${est.resultado && est.resultado !== "fin" ? "Continuar" : "Generar en Flow"} (${faltan} pendientes · ${c.lista} listas)`}
            </button>
          )}
          {est.otro_proyecto && <span className="text-sm text-aviso">Flow está generando para otro proyecto.</span>}
        </div>

        {!corriendo && est.resultado && RESULTADO[est.resultado] && (
          <p className="rounded-xl bg-aviso-suave p-3 text-sm text-aviso">{RESULTADO[est.resultado]}</p>
        )}
        {!corriendo && est.resultado === "error" && (
          <p className="rounded-xl bg-error-suave p-3 text-sm text-error">El generador falló: {est.motivo}</p>
        )}
        {!corriendo && est.resultado === "fin" && c.error > 0 && (
          <p className="rounded-xl bg-aviso-suave p-3 text-sm text-aviso">
            {c.error} escenas no salieron tras varios intentos (pasa el ratón para ver el motivo). Puedes reintentarlas o subir esas imágenes a mano.
          </p>
        )}
        {error && <p className="rounded-xl bg-error-suave p-3 text-sm text-error">{error}</p>}

        <ul className="flex flex-wrap gap-1">
          {est.escenas.map((e) => (
            <li key={e.escena} title={`Escena ${e.escena}: ${{ lista: "lista", pendiente: "pendiente", error: `falló${e.motivo ? ` — ${e.motivo}` : ""}`, en_curso: "generando…", sin_prompt: "sin prompt de imagen" }[e.estado]}`}
              className={`grid h-7 min-w-7 place-items-center rounded-md px-1 text-[10px] font-semibold ${CASILLA[e.estado]}`}>
              {e.estado === "lista" ? <Check size={12} /> : e.estado === "error" ? <X size={12} /> :
                e.estado === "en_curso" ? <Loader2 size={12} className="animate-spin" /> : e.escena}
            </li>
          ))}
        </ul>
      </div>
    </Tarjeta>
  );
}
