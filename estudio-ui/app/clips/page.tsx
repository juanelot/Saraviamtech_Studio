"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { FolderOpen, Loader2, Pencil, Scissors, Trash2, Upload } from "lucide-react";
import { Accion, AvisoError } from "@/components/ui";
import { clipStudio, mmss, type SesionClips } from "@/lib/api";

import Paginacion, { usePaginas } from "@/components/Paginacion";
export default function PaginaClips() {
  const router = useRouter();
  const [lista, setLista] = useState<SesionClips[] | null>(null);
  const paginas = usePaginas(lista, 12);
  const [error, setError] = useState<string | null>(null);
  const [subiendo, setSubiendo] = useState(false);
  const input = useRef<HTMLInputElement>(null);

  const cargar = useCallback(() => clipStudio.listar().then((r) => setLista(r.sesiones)).catch((e) => setError(String(e.message || e))), []);
  useEffect(() => { cargar(); }, [cargar]);

  const ocupada = (s: SesionClips) => !["listo", "error"].includes(s.estado);
  async function renombrar(s: SesionClips) {
    const titulo = prompt("Nuevo nombre", s.titulo)?.trim();
    if (!titulo || titulo === s.titulo) return;
    try { await clipStudio.renombrar(s.id, titulo); cargar(); } catch (e) { setError(String((e as Error).message || e)); }
  }
  async function borrar(s: SesionClips) {
    if (!confirm(`¿Borrar "${s.titulo}" con el video largo y todos sus shorts?`)) return;
    try { await clipStudio.borrar(s.id); cargar(); } catch (e) { setError(String((e as Error).message || e)); }
  }

  async function subir(archivo: File | undefined) {
    if (!archivo) return;
    setSubiendo(true);
    setError(null);
    try {
      const s = await clipStudio.subir(archivo);
      router.push(`/clips/${s.id}`);
    } catch (e) {
      setError(String((e as Error).message || e));
      setSubiendo(false);
    }
  }

  return (
    <main className="mx-auto max-w-6xl px-4 pb-24 pt-12">
      <section className="mb-10 grid gap-8 md:grid-cols-[1.2fr_1fr] md:items-end">
        <div>
          <p className="etiqueta mb-3 flex items-center gap-2"><Scissors size={15} /> De un video largo a shorts</p>
          <h1 className="font-display text-4xl font-semibold leading-tight tracking-tight md:text-5xl">Clip Studio</h1>
          <p className="mt-4 max-w-xl text-tinta-2">
            Sube un video largo (podcast, entrevista, directo). Se transcribe solo, Claude propone los mejores momentos
            y cada uno sale como short vertical con subtitulos palabra por palabra.
          </p>
        </div>
        <div className="rounded-2xl border border-linea bg-tarjeta p-5 shadow-sm">
          <p className="etiqueta mb-3">Nuevo video</p>
          <button className="boton boton-acento w-full justify-center" disabled={subiendo} onClick={() => input.current?.click()}>
            {subiendo ? <Loader2 size={15} className="animate-spin" /> : <Upload size={15} />} {subiendo ? "Subiendo…" : "Subir MP4, MOV, MKV o WEBM"}
          </button>
          <input ref={input} type="file" accept="video/*,.mkv" hidden onChange={(e) => { subir(e.target.files?.[0]); e.target.value = ""; }} />
          <p className="mt-2 text-xs text-tinta-3">La transcripcion corre en esta maquina: en un PC normal, entre 15 y 40 s por minuto de video.</p>
        </div>
      </section>

      <AvisoError texto={error} />

      {!lista ? (
        <Loader2 className="animate-spin text-tinta-3" />
      ) : lista.length === 0 ? (
        <p className="rounded-2xl border border-dashed border-linea p-10 text-center text-tinta-3">Todavia no hay videos. Sube el primero.</p>
      ) : (
        <ul className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
          {paginas.items.map((s) => (
            <li key={s.id}>
              <div className="rounded-2xl border border-linea bg-tarjeta transition hover:border-tinta-3 hover:shadow-sm">
                <Link href={`/clips/${s.id}`} className="block p-4 pb-2">
                  <p className="truncate font-display font-semibold" title={s.titulo}>{s.titulo}</p>
                  <p className="mt-1 text-sm text-tinta-3">{mmss(s.duracion)} · {s.ancho}×{s.alto}</p>
                  <p className={`mt-2 text-xs ${s.estado === "error" ? "text-error" : "text-tinta-2"}`}>
                    {s.estado === "error" ? s.error : s.estado === "listo" ? s.mensaje : `${s.mensaje} (${s.progreso}%)`}
                  </p>
                </Link>
                <div className="flex items-center gap-1 border-t border-linea px-2 py-1">
                  <Accion icono={<FolderOpen size={14} />} texto="Abrir" href={`/clips/${s.id}`} />
                  <Accion icono={<Pencil size={14} />} texto="Renombrar" soloIcono derecha onClick={() => renombrar(s)} />
                  <Accion icono={<Trash2 size={14} />} texto="Borrar" soloIcono peligro disabled={ocupada(s)} onClick={() => borrar(s)} />
                </div>
              </div>
            </li>
          ))}
        </ul>
      )}
      <Paginacion {...paginas} />
    </main>
  );
}
