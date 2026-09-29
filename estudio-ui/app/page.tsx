"use client";

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import Link from "next/link";
import { Plus, Film, Trash2, Loader2 } from "lucide-react";
import { api, mmss, url, type ResumenProyecto } from "@/lib/api";
import { MARCA } from "@/lib/marca";

export default function Inicio() {
  const router = useRouter();
  const [proyectos, setProyectos] = useState<ResumenProyecto[] | null>(null);
  const [error, setError] = useState("");
  const [titulo, setTitulo] = useState("");
  const [creando, setCreando] = useState(false);

  const cargar = () =>
    api.listar().then((r) => setProyectos(r.proyectos)).catch((e) => setError(String(e.message || e)));

  useEffect(() => {
    cargar();
  }, []);

  async function crear(e: React.FormEvent) {
    e.preventDefault();
    setCreando(true);
    try {
      const v = await api.crear(titulo.trim() || "Video sin titulo");
      router.push(`/p/${v.proyecto.id}`);
    } catch (err) {
      setError(String((err as Error).message));
      setCreando(false);
    }
  }

  async function borrar(p: ResumenProyecto) {
    if (!confirm(`¿Borrar «${p.titulo}» y todo lo generado?`)) return;
    await api.borrar(p.id);
    cargar();
  }

  return (
    <main className="mx-auto max-w-6xl px-4 pb-24 pt-12">
      <section className="mb-12 grid gap-8 md:grid-cols-[1.2fr_1fr] md:items-end">
        <div>
          <p className="etiqueta mb-3">Estudio de video</p>
          <h1 className="font-display text-4xl font-semibold leading-tight tracking-tight md:text-5xl">
            {MARCA.eslogan}
          </h1>
          <p className="mt-4 max-w-xl text-tinta-2">
            Escribe el material, Claude redacta el guion, eliges la voz, subes tus imagenes y videos,
            y Claude decide que va en cada frase. Cada etapa se puede revisar y solo se rehace lo que cambia.
          </p>
        </div>
        <form onSubmit={crear} className="rounded-2xl border border-linea bg-tarjeta p-5 shadow-sm">
          <label className="etiqueta" htmlFor="titulo">Nuevo video</label>
          <input
            id="titulo"
            className="campo mt-2"
            placeholder="Titulo (p. ej. Mundial 2026 en 60 segundos)"
            value={titulo}
            onChange={(e) => setTitulo(e.target.value)}
          />
          <button className="boton boton-acento mt-3 w-full justify-center" disabled={creando}>
            {creando ? <Loader2 size={16} className="animate-spin" /> : <Plus size={16} />} Empezar
          </button>
        </form>
      </section>

      <div className="mb-4 flex items-baseline justify-between">
        <h2 className="font-display text-2xl font-semibold">Mis videos</h2>
        {proyectos && <span className="text-sm text-tinta-3">{proyectos.length} proyectos</span>}
      </div>

      {error && <p className="mb-4 rounded-xl bg-error-suave p-3 text-sm text-error">{error}</p>}

      {proyectos === null ? (
        <p className="text-tinta-3">Cargando…</p>
      ) : proyectos.length === 0 ? (
        <div className="rounded-2xl border border-dashed border-linea p-12 text-center text-tinta-2">
          Aun no hay videos. Crea el primero arriba.
        </div>
      ) : (
        <ul className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
          {proyectos.map((p) => (
            <li key={p.id} className="group overflow-hidden rounded-2xl border border-linea bg-tarjeta transition hover:shadow-md">
              <Link href={`/p/${p.id}`} className="block">
                <div className="relative aspect-video bg-hundido">
                  {p.mp4 ? (
                    <video
                      src={`${url.archivo(p.id, p.mp4, p.actualizado)}#t=1`}
                      className="h-full w-full object-cover"
                      muted
                      preload="metadata"
                    />
                  ) : (
                    <div className="grid h-full place-items-center text-tinta-3">
                      <Film size={28} />
                    </div>
                  )}
                  {p.trabajando && (
                    <span className="latido absolute left-3 top-3 rounded-full bg-acento px-2.5 py-0.5 text-xs font-semibold text-white">
                      trabajando
                    </span>
                  )}
                  {p.duracion ? (
                    <span className="absolute bottom-2 right-2 rounded-md bg-black/70 px-1.5 py-0.5 text-xs text-white">
                      {mmss(p.duracion)}
                    </span>
                  ) : null}
                </div>
                <div className="p-4">
                  <h3 className="line-clamp-1 font-semibold">{p.titulo}</h3>
                  <p className="mt-1 text-xs text-tinta-3">
                    Editado {new Date(p.actualizado * 1000).toLocaleString()}
                  </p>
                </div>
              </Link>
              <div className="flex justify-end border-t border-linea px-2 py-1.5">
                <button onClick={() => borrar(p)} className="boton boton-fantasma !px-2.5 !py-1.5 text-xs" title="Borrar">
                  <Trash2 size={14} /> Borrar
                </button>
              </div>
            </li>
          ))}
        </ul>
      )}
    </main>
  );
}
