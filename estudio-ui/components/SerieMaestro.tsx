"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { ArrowLeft, CheckCircle2, Library, Loader2, MessagesSquare, Plus, RefreshCw, Sparkles, Trash2, Upload, X } from "lucide-react";
import { AvisoError, Segmentado, Tarjeta } from "./ui";
import { Copiar } from "./paneles/PanelEscenas";
import { maestros, series, type Creacion, type Referencia, type Serie } from "@/lib/api";

export default function SerieMaestro({ id, sid }: { id: string; sid: string }) {
  const router = useRouter();
  const [s, setS] = useState<Serie | null>(null);
  const [nombreMaestro, setNombreMaestro] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [titulo, setTitulo] = useState("");
  const [biblia, setBiblia] = useState("");
  const [nuevo, setNuevo] = useState(false);
  const temporizador = useRef<ReturnType<typeof setTimeout> | null>(null);

  const cargar = useCallback(async () => {
    try {
      const x = await series.ver(id, sid);
      setS((previo) => {
        // Titulo y biblia se sincronizan al cargar por primera vez o cuando Claude termina.
        if (!previo || (previo.preparando && !x.preparando)) {
          setTitulo(x.titulo);
          setBiblia(x.biblia);
        }
        return x;
      });
    } catch (e) {
      setError(String((e as Error).message || e));
    }
  }, [id, sid]);

  useEffect(() => {
    // cargar es async: el setState ocurre tras el fetch.
    // eslint-disable-next-line react-hooks/set-state-in-effect
    cargar();
    maestros.ver(id).then((m) => setNombreMaestro(m.nombre)).catch(() => {});
  }, [cargar, id]);

  const preparando = !!s?.preparando;
  useEffect(() => {
    if (!preparando) return;
    const t = setInterval(cargar, 3000);
    return () => clearInterval(t);
  }, [preparando, cargar]);

  function guardar(cambios: { titulo?: string; biblia?: string }) {
    if (temporizador.current) clearTimeout(temporizador.current);
    temporizador.current = setTimeout(() => series.cambiar(id, sid, cambios).catch((e) => setError(String(e.message || e))), 800);
  }

  async function accion(f: () => Promise<Serie>) {
    setError(null);
    try {
      setS(await f());
    } catch (e) {
      setError(String((e as Error).message || e));
    }
  }

  if (!s) {
    return <main className="mx-auto max-w-6xl px-4 py-16">{error ? <AvisoError texto={error} /> : <Loader2 className="animate-spin text-tinta-3" />}</main>;
  }

  return (
    <main className="mx-auto max-w-6xl px-4 pb-24 pt-6">
      <div className="mb-5 flex flex-wrap items-center gap-3">
        <Link href={`/maestros/${id}`} className="boton boton-fantasma !px-2.5" aria-label="Volver"><ArrowLeft size={16} /></Link>
        <div className="min-w-0 flex-1">
          <p className="etiqueta flex items-center gap-1.5 truncate"><Library size={12} /> Serie · {nombreMaestro || "Prompt maestro"}</p>
          <input value={titulo} aria-label="Titulo de la serie"
            onChange={(e) => { setTitulo(e.target.value); guardar({ titulo: e.target.value }); }}
            className="w-full bg-transparent font-display text-2xl font-semibold tracking-tight outline-none" />
        </div>
        <button className="boton boton-acento" disabled={preparando} onClick={() => setNuevo((v) => !v)}>
          <Plus size={15} /> Nuevo episodio
        </button>
        <button className="boton boton-fantasma !px-2.5" title="Borrar la serie (los episodios se conservan)" disabled={preparando}
          onClick={async () => {
            if (!confirm("¿Borrar la serie? Los episodios se conservan como creaciones sueltas.")) return;
            await series.borrar(id, sid);
            router.push(`/maestros/${id}`);
          }}>
          <Trash2 size={16} />
        </button>
      </div>

      {nuevo && <NuevoEpisodio mid={id} s={s} onCerrar={() => setNuevo(false)} onError={setError} />}
      <AvisoError texto={error || (s.error && !preparando ? `No se pudo escribir la biblia: ${s.error}` : null)} />

      <div className="grid gap-5 lg:grid-cols-[1fr_380px]">
        <Tarjeta titulo="Biblia de la serie" extra={
          <span className="flex gap-1">
            {biblia && <Copiar texto={biblia} />}
            <button className="boton boton-fantasma !gap-1 !px-2 !py-1 text-xs" disabled={preparando}
              title="Claude la vuelve a escribir a partir del episodio 1"
              onClick={() => { if (!biblia || confirm("¿Reescribir la biblia? Se pierden tus cambios.")) accion(() => series.rehacerBiblia(id, sid)); }}>
              <RefreshCw size={12} /> Reescribir
            </button>
          </span>
        }>
          {preparando ? (
            <p className="latido flex items-center gap-2 text-sm text-tinta-2">
              <Loader2 size={15} className="animate-spin text-acento" /> Claude esta escribiendo la biblia a partir del episodio 1 (~1 min)…
            </p>
          ) : (
            <>
              <p className="mb-2 text-xs text-tinta-3">
                Lo que NO cambia entre episodios. Cada episodio nuevo la recibe bloqueada. Puedes editarla: se guarda sola.
              </p>
              <textarea className="campo min-h-[60vh] font-mono !text-xs leading-relaxed" value={biblia}
                onChange={(e) => { setBiblia(e.target.value); guardar({ biblia: e.target.value }); }} />
            </>
          )}
        </Tarjeta>

        <aside className="space-y-5">
          <Tarjeta titulo={`Episodios (${s.episodios_info.length})`}>
            <ol className="-mx-2 space-y-0.5">
              {s.episodios_info.map((e) => (
                <li key={e.id}>
                  <Link href={`/maestros/${id}/crear/${e.id}`} className="flex gap-2 rounded-lg px-2 py-1.5 text-sm hover:bg-hundido">
                    <span className="grid h-6 w-6 shrink-0 place-items-center rounded-full bg-tinta text-[11px] font-bold text-papel">{e.episodio ?? "?"}</span>
                    <span className="min-w-0 flex-1">
                      <span className="flex items-center gap-1.5">
                        <span className="truncate font-medium">{e.titulo}</span>
                        {e.listo ? <CheckCircle2 size={13} className="shrink-0 text-ok" /> : <MessagesSquare size={13} className="shrink-0 text-tinta-3" />}
                      </span>
                      {e.resumen && <span className="line-clamp-2 text-xs text-tinta-3">{e.resumen}</span>}
                    </span>
                  </Link>
                </li>
              ))}
            </ol>
          </Tarjeta>
          <ReferenciasSerie mid={id} s={s} accion={accion} />
        </aside>
      </div>
    </main>
  );
}

function ReferenciasSerie({ mid, s, accion }: { mid: string; s: Serie; accion: (f: () => Promise<Serie>) => Promise<void> }) {
  const [subiendo, setSubiendo] = useState<string | null>(null);

  async function subir(r: Referencia, archivo: File | undefined) {
    if (!archivo) return;
    setSubiendo(r.clave);
    await accion(() => series.subirReferencia(mid, s.id, r.clave, archivo));
    setSubiendo(null);
  }

  return (
    <Tarjeta titulo="Hojas de referencia">
      {!s.referencias.length ? (
        <p className="text-sm text-tinta-3">
          La serie no tiene referencias todavia. Proponlas en el episodio 1 (Entregables → Hojas de referencia) antes de
          convertirlo, o crealas en cualquier episodio.
        </p>
      ) : (
        <>
          <p className="mb-2 text-xs text-tinta-3">Comunes a todos los episodios: sube la imagen una vez y la usas en todos.</p>
          <ul className="space-y-2">
            {s.referencias.map((r) => (
              <li key={r.clave} className="flex gap-2.5 rounded-xl border border-linea bg-hundido/40 p-2">
                <label className="relative flex h-14 w-14 shrink-0 cursor-pointer items-center justify-center overflow-hidden rounded-lg border border-dashed border-linea bg-tarjeta text-tinta-3 hover:border-acento"
                  title={r.imagen ? "Cambiar la imagen" : "Subir la imagen"}>
                  {subiendo === r.clave ? <Loader2 size={15} className="animate-spin" />
                    // eslint-disable-next-line @next/next/no-img-element
                    : r.imagen ? <img src={series.urlReferencia(mid, s.id, r)} alt={r.nombre} className="h-full w-full object-cover" />
                    : <Upload size={15} />}
                  <input type="file" accept="image/png,image/jpeg,image/webp" hidden
                    onChange={(ev) => { subir(r, ev.target.files?.[0]); ev.target.value = ""; }} />
                </label>
                <div className="min-w-0 flex-1 text-sm">
                  <div className="flex items-center gap-1">
                    <span className="truncate font-semibold">{r.nombre}</span>
                    <span className="ml-auto flex">
                      {r.prompt && <Copiar texto={r.prompt} etiqueta="Prompt" />}
                      <button className="rounded-md p-1 text-tinta-3 hover:bg-tarjeta hover:text-red-500" title="Quitar de la serie"
                        onClick={() => {
                          if (confirm(`¿Quitar "${r.nombre}" de la serie?`))
                            accion(() => series.cambiar(mid, s.id, { referencias: s.referencias.filter((x) => x.clave !== r.clave) }));
                        }}><X size={13} /></button>
                    </span>
                  </div>
                  <p className="text-xs text-tinta-3">{r.imagen ? "Imagen lista" : "Falta la imagen"}{r.archivo ? ` · ${r.archivo}` : ""}</p>
                </div>
              </li>
            ))}
          </ul>
        </>
      )}
    </Tarjeta>
  );
}

function NuevoEpisodio({ mid, s, onCerrar, onError }: { mid: string; s: Serie; onCerrar: () => void; onError: (e: string) => void }) {
  const router = useRouter();
  const [tema, setTema] = useState("");
  const [modo, setModo] = useState<Creacion["modo"]>("guiado");
  const [modelo, setModelo] = useState("sonnet");
  const [enviando, setEnviando] = useState(false);
  const n = Math.max(0, ...s.episodios_info.map((e) => e.episodio || 1)) + 1;

  async function ir() {
    setEnviando(true);
    try {
      const c = await series.episodio(mid, s.id, { tema, modo, modelo });
      router.push(`/maestros/${mid}/crear/${c.id}`);
    } catch (e) {
      onError(String((e as Error).message || e));
      setEnviando(false);
    }
  }

  return (
    <Tarjeta className="mb-5 border-acento/40" titulo={`Episodio ${n}`}
      extra={<button className="boton boton-fantasma !px-2" onClick={onCerrar} aria-label="Cerrar"><X size={16} /></button>}>
      <div className="grid gap-5 md:grid-cols-[1.4fr_1fr]">
        <label className="block">
          <span className="etiqueta">Tema de este episodio</span>
          <textarea className="campo mt-1.5 min-h-[96px]" value={tema} onChange={(e) => setTema(e.target.value)}
            placeholder="De que va este episodio (si lo dejas vacio, Claude te lo preguntara)" />
          <span className="mt-1 block text-xs text-tinta-3">
            Claude recibe la biblia bloqueada, las referencias y los {s.episodios_info.length} episodios anteriores para no repetirlos.
          </span>
        </label>
        <div className="space-y-4">
          <div>
            <span className="etiqueta mb-1.5 block">Modo</span>
            <Segmentado valor={modo} onChange={setModo} opciones={[{ v: "guiado", t: "Guiado" }, { v: "auto", t: "Automatico" }]} />
          </div>
          <div>
            <span className="etiqueta mb-1.5 block">Modelo</span>
            <Segmentado valor={modelo} onChange={setModelo} opciones={[{ v: "sonnet", t: "Sonnet (rapido)" }, { v: "opus", t: "Opus (mas fino)" }]} />
          </div>
          <button className="boton boton-acento w-full justify-center" disabled={enviando} onClick={ir}>
            {enviando ? <Loader2 size={15} className="animate-spin" /> : <Sparkles size={15} />} Empezar episodio {n}
          </button>
        </div>
      </div>
    </Tarjeta>
  );
}
