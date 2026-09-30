"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { BookOpen, FileText, Loader2, Mic, MicOff, Upload } from "lucide-react";
import { AvisoError } from "@/components/ui";
import { maestros, type ResumenMaestro } from "@/lib/api";

export default function PaginaMaestros() {
  const router = useRouter();
  const [lista, setLista] = useState<ResumenMaestro[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [subiendo, setSubiendo] = useState(false);
  const [pegar, setPegar] = useState(false);
  const [texto, setTexto] = useState("");
  const [nombre, setNombre] = useState("");
  const input = useRef<HTMLInputElement>(null);

  const cargar = useCallback(() => {
    return maestros.listar().then((r) => setLista(r.maestros)).catch((e) => setError(String(e.message || e)));
  }, []);

  useEffect(() => {
    cargar();
  }, [cargar]);

  // Mientras alguno se analiza, se refresca la lista.
  const analizando = !!lista?.some((m) => m.analizando);
  useEffect(() => {
    if (!analizando) return;
    const t = setInterval(cargar, 3000);
    return () => clearInterval(t);
  }, [analizando, cargar]);

  async function subir(archivo: File | null) {
    setSubiendo(true);
    setError(null);
    try {
      const m = await maestros.subir(archivo, archivo ? "" : texto, nombre);
      router.push(`/maestros/${m.id}`);
    } catch (e) {
      setError(String((e as Error).message || e));
      setSubiendo(false);
    }
  }

  return (
    <main className="mx-auto max-w-6xl px-4 pb-24 pt-12">
      <section className="mb-10 grid gap-8 md:grid-cols-[1.2fr_1fr] md:items-end">
        <div>
          <p className="etiqueta mb-3 flex items-center gap-2"><BookOpen size={15} /> Biblioteca de estilos</p>
          <h1 className="font-display text-4xl font-semibold leading-tight tracking-tight md:text-5xl">Prompts maestros</h1>
          <p className="mt-4 max-w-xl text-tinta-2">
            Sube un prompt maestro y Claude lo desglosa: que pregunta, que entrega, su formato y sus reglas. Queda
            guardado como estilo para crear contenido con el cuando quieras.
          </p>
        </div>
        <div className="rounded-2xl border border-linea bg-tarjeta p-5 shadow-sm">
          <p className="etiqueta mb-3">Nuevo prompt maestro</p>
          {!pegar ? (
            <>
              <button className="boton boton-acento w-full justify-center" disabled={subiendo} onClick={() => input.current?.click()}>
                {subiendo ? <Loader2 size={15} className="animate-spin" /> : <Upload size={15} />} Subir .docx, .txt o .md
              </button>
              <input ref={input} type="file" accept=".docx,.txt,.md" hidden onChange={(e) => subir(e.target.files?.[0] || null)} />
              <button className="boton boton-fantasma mt-2 w-full justify-center text-sm" onClick={() => setPegar(true)}>
                <FileText size={14} /> o pegar el texto
              </button>
            </>
          ) : (
            <div className="space-y-2">
              <input className="campo" placeholder="Nombre (opcional)" value={nombre} onChange={(e) => setNombre(e.target.value)} />
              <textarea className="campo min-h-[160px] font-mono !text-xs" placeholder="Pega aqui el prompt maestro completo"
                value={texto} onChange={(e) => setTexto(e.target.value)} />
              <div className="flex gap-2">
                <button className="boton boton-acento flex-1 justify-center" disabled={subiendo || texto.trim().length < 200}
                  onClick={() => subir(null)}>
                  {subiendo ? <Loader2 size={15} className="animate-spin" /> : null} Guardar y desglosar
                </button>
                <button className="boton boton-linea" onClick={() => setPegar(false)}>Cancelar</button>
              </div>
            </div>
          )}
        </div>
      </section>

      <AvisoError texto={error} />

      {!lista ? (
        <Loader2 className="animate-spin text-tinta-3" />
      ) : lista.length === 0 ? (
        <p className="rounded-2xl border border-dashed border-linea p-10 text-center text-tinta-3">
          Todavia no hay prompts maestros. Sube el primero.
        </p>
      ) : (
        <ul className="grid gap-5 sm:grid-cols-2 lg:grid-cols-3">
          {lista.map((m) => (
            <li key={m.id}>
              <Link href={`/maestros/${m.id}`}
                className="group block overflow-hidden rounded-2xl border border-linea bg-tarjeta transition hover:border-tinta-3 hover:shadow-sm">
                <div className="relative aspect-video overflow-hidden bg-hundido">
                  {m.portada ? (
                    // eslint-disable-next-line @next/next/no-img-element
                    <img src={maestros.portada(m.id, m.actualizado)} alt="" className="absolute inset-0 h-full w-full object-cover" loading="lazy" />
                  ) : (
                    <div className="bg-marca grid h-full place-items-center opacity-80"><BookOpen size={30} className="text-[#0b0d17]" /></div>
                  )}
                  {m.analizando && (
                    <span className="latido absolute left-3 top-3 inline-flex items-center gap-1 rounded-full bg-acento px-2.5 py-0.5 text-xs font-semibold text-sobre-acento">
                      <Loader2 size={11} className="animate-spin" /> Claude lo esta desglosando
                    </span>
                  )}
                  {m.estado === "error" && !m.analizando && (
                    <span className="absolute left-3 top-3 rounded-full bg-error px-2.5 py-0.5 text-xs font-semibold text-white">Error al analizar</span>
                  )}
                </div>
                <div className="p-4">
                  <p className="font-display font-semibold leading-snug">{m.nombre}</p>
                  {m.resumen && <p className="mt-1 line-clamp-2 text-sm text-tinta-2">{m.resumen}</p>}
                  <div className="mt-3 flex flex-wrap gap-1.5 text-xs">
                    {m.categoria && <Chip>{m.categoria}</Chip>}
                    {m.formato?.aspecto && <Chip>{m.formato.aspecto}</Chip>}
                    {m.formato?.duracion_total_s ? <Chip>{m.formato.duracion_total_s} s</Chip> : null}
                    {m.narracion === true && <Chip><Mic size={11} /> con narracion</Chip>}
                    {m.narracion === false && <Chip><MicOff size={11} /> sin narracion</Chip>}
                  </div>
                </div>
              </Link>
            </li>
          ))}
        </ul>
      )}
    </main>
  );
}

function Chip({ children }: { children: React.ReactNode }) {
  return <span className="inline-flex items-center gap-1 rounded-full bg-hundido px-2.5 py-0.5 text-tinta-2">{children}</span>;
}
