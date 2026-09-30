"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { usePathname } from "next/navigation";
import { Loader2, MessageCircle, RotateCcw, Send, X } from "lucide-react";
import { asistente, type Charla } from "@/lib/api";

const CLAVE = "estudio-asistente-charla";
const SUGERENCIAS = [
  "¿Que hace cada etapa?",
  "¿Por que una etapa sale como desactualizada?",
  "¿Como uso recursos de una carpeta del servidor?",
  "Me salio un error, ¿que paso?",
];

function leerCharla() {
  try {
    return localStorage.getItem(CLAVE);
  } catch {
    return null;
  }
}

function guardarCharla(id: string | null) {
  try {
    if (id) localStorage.setItem(CLAVE, id);
    else localStorage.removeItem(CLAVE);
  } catch {}
}

// Markdown minimo: **negrita**, `codigo` y bloques ``` ```. El resto va tal cual.
function Texto({ texto }: { texto: string }) {
  const bloques = texto.split(/```[\w-]*\n?/);
  return (
    <>
      {bloques.map((b, i) =>
        i % 2 === 1 ? (
          <pre key={i} className="my-2 overflow-x-auto rounded-lg bg-hundido p-2 font-mono text-xs">{b.trim()}</pre>
        ) : (
          <span key={i}>
            {b.split(/(\*\*[^*]+\*\*|`[^`]+`)/g).map((t, j) =>
              t.startsWith("**") ? <strong key={j}>{t.slice(2, -2)}</strong>
                : t.startsWith("`") ? <code key={j} className="rounded bg-hundido px-1 font-mono text-[0.85em]">{t.slice(1, -1)}</code>
                : t,
            )}
          </span>
        ),
      )}
    </>
  );
}

export default function Asistente() {
  const ruta = usePathname();
  const proyecto = ruta?.startsWith("/p/") ? ruta.split("/")[2] : null;
  const [abierto, setAbierto] = useState(false);
  const [charla, setCharla] = useState<Charla | null>(null);
  const [texto, setTexto] = useState("");
  const [error, setError] = useState("");
  const fondo = useRef<HTMLDivElement>(null);

  const refrescar = useCallback(async (id: string) => {
    try {
      setCharla(await asistente.ver(id));
    } catch {
      guardarCharla(null);
      setCharla(null);
    }
  }, []);

  // Al abrir, recuperar la charla guardada en este navegador.
  function alternar() {
    if (!abierto && !charla) {
      const id = leerCharla();
      if (id) refrescar(id);
    }
    setAbierto((a) => !a);
  }

  // Mientras piensa, consultar.
  const pensando = !!charla?.pensando;
  useEffect(() => {
    if (!pensando || !charla) return;
    const t = setInterval(() => refrescar(charla.id), 1500);
    return () => clearInterval(t);
  }, [pensando, charla, refrescar]);

  useEffect(() => {
    fondo.current?.scrollTo({ top: fondo.current.scrollHeight, behavior: "smooth" });
  }, [charla?.turnos.length, pensando, abierto]);

  async function enviar(pregunta: string) {
    const q = pregunta.trim();
    if (!q || pensando) return;
    setTexto("");
    setError("");
    try {
      const c = await asistente.preguntar(q, charla?.id, proyecto);
      guardarCharla(c.id);
      setCharla(c);
    } catch (e) {
      setError(String((e as Error).message));
    }
  }

  function nueva() {
    guardarCharla(null);
    setCharla(null);
    setError("");
  }

  const abajo = proyecto ? "bottom-24" : "bottom-6";

  return (
    <>
      {abierto && (
        <div className={`fixed right-4 ${proyecto ? "bottom-40" : "bottom-24"} z-40 flex h-[560px] max-h-[70vh] w-[min(400px,calc(100vw-2rem))] flex-col overflow-hidden rounded-2xl border border-linea bg-tarjeta shadow-2xl`}>
          <div className="flex items-center gap-2 border-b border-linea px-4 py-3">
            <span className="grid h-7 w-7 place-items-center rounded-full bg-marca text-[#0b0d17]"><MessageCircle size={14} /></span>
            <div className="min-w-0 flex-1">
              <p className="text-sm font-semibold">Asistente</p>
              <p className="truncate text-[11px] text-tinta-3">
                {proyecto ? "Ve este proyecto, su estado y el codigo" : "Ve el estado del Estudio y el codigo"}
              </p>
            </div>
            <button onClick={nueva} className="boton boton-fantasma !p-1.5" title="Nueva charla"><RotateCcw size={14} /></button>
            <button onClick={() => setAbierto(false)} className="boton boton-fantasma !p-1.5" title="Cerrar"><X size={16} /></button>
          </div>

          <div ref={fondo} className="flex-1 space-y-3 overflow-y-auto px-4 py-4 text-sm">
            {!charla?.turnos.length && (
              <div>
                <p className="text-tinta-2">
                  Preguntame como usar el Estudio, por que algo fallo o que significa un estado.
                  Contesto con tu cuenta de Claude.
                </p>
                <div className="mt-3 flex flex-wrap gap-2">
                  {SUGERENCIAS.map((s) => (
                    <button key={s} onClick={() => enviar(s)} className="rounded-full border border-linea px-3 py-1 text-xs text-tinta-2 hover:border-acento hover:text-tinta">
                      {s}
                    </button>
                  ))}
                </div>
              </div>
            )}
            {charla?.turnos.map((t, i) => (
              <div key={i} className={t.rol === "persona" ? "flex justify-end" : ""}>
                <div className={`max-w-[92%] whitespace-pre-wrap rounded-2xl px-3.5 py-2.5 leading-relaxed ${
                  t.rol === "persona" ? "bg-acento text-sobre-acento" : "bg-hundido"}`}>
                  {t.rol === "persona" ? t.texto : <Texto texto={t.texto} />}
                </div>
              </div>
            ))}
            {pensando && (
              <div className="flex items-center gap-2 text-tinta-3">
                <Loader2 size={14} className="animate-spin" /> Pensando… (puede tardar un minuto si revisa el codigo)
              </div>
            )}
            {(charla?.error || error) && (
              <p className="rounded-xl bg-error-suave p-3 text-xs text-error">{charla?.error || error}</p>
            )}
          </div>

          <form
            onSubmit={(e) => { e.preventDefault(); enviar(texto); }}
            className="flex items-end gap-2 border-t border-linea p-3"
          >
            <textarea
              value={texto}
              onChange={(e) => setTexto(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); enviar(texto); }
              }}
              rows={2}
              placeholder="Escribe tu pregunta… (Enter para enviar)"
              className="campo max-h-32 flex-1 !text-sm"
            />
            <button className="boton boton-acento !p-2.5" disabled={pensando || !texto.trim()} title="Enviar">
              <Send size={15} />
            </button>
          </form>
        </div>
      )}

      <button
        onClick={alternar}
        className={`fixed right-4 ${abajo} z-40 grid h-12 w-12 place-items-center rounded-full bg-marca text-[#0b0d17] shadow-lg transition hover:scale-105`}
        title="Asistente"
        aria-label="Abrir asistente"
      >
        {abierto ? <X size={20} /> : <MessageCircle size={20} />}
      </button>
    </>
  );
}
