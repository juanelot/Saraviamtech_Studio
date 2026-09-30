"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import {
  ArrowLeft, BookOpen, Check, Copy, Film, Languages, Loader2, Lock, Mic, MicOff, RefreshCw, Sparkles, Trash2, TriangleAlert,
} from "lucide-react";
import { AvisoError, Tarjeta } from "./ui";
import { maestros, type Maestro } from "@/lib/api";

const ENTREGABLES: Record<string, string> = {
  ideas: "Ideas", guion: "Guion", beats: "Beats", prompts_imagen: "Prompts de imagen", prompts_video: "Prompts de video",
  voz_por_escena: "Voz por escena", miniaturas: "Miniaturas", referencias: "Hojas de referencia",
  biblia_serie: "Biblia de serie", storyboard: "Storyboard", otro: "Otro",
};

export default function FichaMaestro({ id }: { id: string }) {
  const router = useRouter();
  const [m, setM] = useState<Maestro | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [vista, setVista] = useState<"ficha" | "original">("ficha");
  const [original, setOriginal] = useState<string | null>(null);
  const [nombre, setNombre] = useState("");
  const [notas, setNotas] = useState("");
  const temporizador = useRef<ReturnType<typeof setTimeout> | null>(null);

  const cargar = useCallback(async () => {
    try {
      const x = await maestros.ver(id);
      setM((previo) => {
        if (!previo) {
          setNombre(x.nombre);
          setNotas(x.notas || "");
        }
        return x;
      });
    } catch (e) {
      setError(String((e as Error).message || e));
    }
  }, [id]);

  useEffect(() => {
    // cargar es async: el setState ocurre tras el fetch.
    // eslint-disable-next-line react-hooks/set-state-in-effect
    cargar();
  }, [cargar]);

  const analizando = !!m?.analizando;
  useEffect(() => {
    if (!analizando) return;
    const t = setInterval(cargar, 3000);
    return () => clearInterval(t);
  }, [analizando, cargar]);

  function guardar(cambios: { nombre?: string; notas?: string }) {
    if (temporizador.current) clearTimeout(temporizador.current);
    temporizador.current = setTimeout(() => maestros.editar(id, cambios).catch((e) => setError(String(e.message || e))), 700);
  }

  async function verOriginal() {
    setVista("original");
    if (original === null) setOriginal(await maestros.original(id));
  }

  if (!m) {
    return <main className="mx-auto max-w-6xl px-4 py-16">{error ? <AvisoError texto={error} /> : <Loader2 className="animate-spin text-tinta-3" />}</main>;
  }
  const f = m.ficha;

  return (
    <main className="mx-auto max-w-6xl px-4 pb-24 pt-6">
      <div className="mb-6 flex flex-wrap items-center gap-3">
        <Link href="/maestros" className="boton boton-fantasma !px-2.5"><ArrowLeft size={16} /></Link>
        <input value={nombre} aria-label="Nombre"
          onChange={(e) => { setNombre(e.target.value); guardar({ nombre: e.target.value }); }}
          className="min-w-0 flex-1 bg-transparent font-display text-2xl font-semibold tracking-tight outline-none md:text-3xl" />
        <button className="boton boton-acento" disabled title="Llega en la fase 2">
          <Sparkles size={15} /> Crear contenido
        </button>
      </div>

      <AvisoError texto={error || (m.estado === "error" && !analizando ? `No se pudo desglosar: ${m.error}` : null)} />

      <div className="grid gap-5 lg:grid-cols-[340px_1fr]">
        <aside className="space-y-4">
          <div className="overflow-hidden rounded-2xl border border-linea bg-tarjeta">
            {m.portada ? (
              // eslint-disable-next-line @next/next/no-img-element
              <img src={maestros.portada(m.id)} alt="" className="aspect-video w-full object-cover" />
            ) : (
              <div className="bg-marca grid aspect-video place-items-center opacity-80"><BookOpen size={30} className="text-[#0b0d17]" /></div>
            )}
            <div className="space-y-3 p-4 text-sm">
              {f ? (
                <>
                  <p className="text-tinta-2">{f.resumen}</p>
                  <div className="flex flex-wrap gap-1.5 text-xs">
                    {f.categoria && <Chip>{f.categoria}</Chip>}
                    {f.formato?.aspecto && <Chip>{f.formato.aspecto}</Chip>}
                    {f.formato?.duracion_total_s ? <Chip>{f.formato.duracion_total_s} s</Chip> : null}
                    {f.formato?.escenas ? <Chip>{f.formato.escenas} escenas</Chip> : null}
                    {f.formato?.clip_s ? <Chip>clips de {f.formato.clip_s} s</Chip> : null}
                    {f.formato?.duracion_variable && <Chip>duracion a elegir</Chip>}
                  </div>
                  <Dato icono={f.narracion?.tiene ? <Mic size={14} /> : <MicOff size={14} />} titulo={f.narracion?.tiene ? "Con narracion" : "Sin narracion"}>
                    {f.narracion?.como}
                  </Dato>
                  {!!f.herramientas?.length && <Dato icono={<Film size={14} />} titulo="Herramientas">{f.herramientas.join(", ")}</Dato>}
                  {f.idiomas && (
                    <Dato icono={<Languages size={14} />} titulo="Idiomas">
                      Prompts en {f.idiomas.prompts || "?"}
                      {f.narracion?.idioma ? ` · narracion en ${f.narracion.idioma}` : ""}
                      {f.idiomas.texto_en_imagen ? ` · texto en imagen en ${f.idiomas.texto_en_imagen}` : ""}
                    </Dato>
                  )}
                </>
              ) : (
                <p className="flex items-center gap-2 text-tinta-3">
                  {analizando ? <><Loader2 size={14} className="animate-spin" /> Claude lo esta desglosando (1-2 min)…</> : "Sin ficha todavia."}
                </p>
              )}
              <p className="text-xs text-tinta-3">{m.origen} · {Math.round(m.caracteres / 1000)} mil caracteres</p>
            </div>
          </div>

          <Tarjeta titulo="Mis notas">
            <textarea className="campo min-h-[90px]" placeholder="Apuntes para tus videos o tu clase…" value={notas}
              onChange={(e) => { setNotas(e.target.value); guardar({ notas: e.target.value }); }} />
          </Tarjeta>

          <div className="flex flex-wrap gap-2">
            <button className="boton boton-linea text-sm" disabled={analizando}
              onClick={() => maestros.analizar(id).then(setM).catch((e) => setError(String(e.message || e)))}>
              <RefreshCw size={14} /> Volver a desglosar
            </button>
            <button className="boton boton-fantasma text-sm"
              onClick={async () => {
                if (!confirm(`¿Borrar "${m.nombre}"?`)) return;
                await maestros.borrar(id);
                router.push("/maestros");
              }}>
              <Trash2 size={14} /> Borrar
            </button>
          </div>
        </aside>

        <section className="min-w-0 space-y-5">
          <div className="inline-flex rounded-full border border-linea bg-hundido p-1">
            {(["ficha", "original"] as const).map((v) => (
              <button key={v} onClick={() => (v === "original" ? verOriginal() : setVista("ficha"))}
                className={`rounded-full px-3.5 py-1.5 text-sm font-medium transition ${vista === v ? "bg-tarjeta text-tinta shadow-sm" : "text-tinta-2 hover:text-tinta"}`}>
                {v === "ficha" ? "Desglose" : "Prompt original"}
              </button>
            ))}
          </div>

          {vista === "original" ? (
            <Tarjeta extra={original ? <CopiarTexto texto={original} /> : null} titulo="Prompt original">
              {original === null ? <Loader2 className="animate-spin text-tinta-3" /> : (
                <pre className="max-h-[70vh] overflow-auto whitespace-pre-wrap font-mono text-xs leading-relaxed text-tinta-2">{original}</pre>
              )}
            </Tarjeta>
          ) : !f ? (
            <Tarjeta>
              <p className="flex items-center gap-2 text-tinta-3">
                {analizando ? <><Loader2 size={15} className="animate-spin" /> Claude esta leyendo el prompt maestro y armando la ficha…</> : "Sin desglose."}
              </p>
            </Tarjeta>
          ) : (
            <>
              <Tarjeta titulo="Como funciona, paso a paso">
                <ol className="space-y-3">
                  {f.pasos.map((p) => (
                    <li key={p.n} className="flex gap-3">
                      <span className="grid h-7 w-7 shrink-0 place-items-center rounded-full bg-tinta text-xs font-bold text-papel">{p.n}</span>
                      <div className="min-w-0 flex-1 text-sm">
                        <p className="font-semibold">{p.titulo}</p>
                        <p className="text-tinta-2">{p.que_hace}</p>
                        {p.pregunta && (
                          <p className="mt-1.5 rounded-lg bg-acento-suave px-3 py-2 text-[13px]">
                            <b>Te pregunta:</b> {p.pregunta}
                            {!!p.opciones?.length && (
                              <span className="mt-1.5 flex flex-wrap gap-1.5">
                                {p.opciones.map((o, i) => <span key={i} className="rounded-full bg-tarjeta px-2 py-0.5 text-xs">{o}</span>)}
                              </span>
                            )}
                          </p>
                        )}
                        {!!p.entrega?.length && <p className="mt-1 text-xs text-tinta-3">Entrega: {p.entrega.join(" · ")}</p>}
                      </div>
                    </li>
                  ))}
                </ol>
              </Tarjeta>

              <div className="grid gap-5 md:grid-cols-2">
                <Tarjeta titulo="Lo que entrega">
                  <ul className="space-y-2 text-sm">
                    {f.entregables.map((e, i) => (
                      <li key={i}>
                        <span className="font-semibold">{ENTREGABLES[e.tipo] || e.tipo}</span>
                        {e.cantidad ? <span className="text-tinta-3"> · {e.cantidad}</span> : null}
                        {e.idioma ? <span className="text-tinta-3"> · {e.idioma}</span> : null}
                        <span className="block text-tinta-2">{e.descripcion}</span>
                      </li>
                    ))}
                  </ul>
                </Tarjeta>
                <Tarjeta titulo="Bloques fijos">
                  {f.bloques_fijos?.length ? (
                    <ul className="space-y-2 text-sm">
                      {f.bloques_fijos.map((b, i) => (
                        <li key={i} className="flex gap-2">
                          <Lock size={14} className="mt-0.5 shrink-0 text-acento" />
                          <span><span className="font-semibold">{b.nombre}</span><span className="block text-tinta-2">{b.para_que}</span></span>
                        </li>
                      ))}
                    </ul>
                  ) : <p className="text-sm text-tinta-3">No usa bloques fijos.</p>}
                </Tarjeta>
              </div>

              <Tarjeta titulo="Reglas clave">
                <ul className="grid gap-2 text-sm md:grid-cols-2">
                  {f.reglas_clave.map((r, i) => (
                    <li key={i} className="flex gap-2"><Check size={14} className="mt-0.5 shrink-0 text-ok" /> {r}</li>
                  ))}
                </ul>
              </Tarjeta>

              <div className="grid gap-5 md:grid-cols-3">
                <Tarjeta titulo="Estilo visual"><p className="text-sm text-tinta-2">{f.estilo_visual}</p></Tarjeta>
                <Tarjeta titulo="Audio"><p className="text-sm text-tinta-2">{f.audio}</p></Tarjeta>
                <Tarjeta titulo="Evita"><p className="text-sm text-tinta-2">{f.negativos}</p></Tarjeta>
              </div>

              <Tarjeta titulo="Como encaja en el Estudio">
                <p className="text-sm text-tinta-2">{f.encaje_estudio}</p>
                {!!f.advertencias?.length && (
                  <ul className="mt-3 space-y-1.5 text-sm">
                    {f.advertencias.map((a, i) => (
                      <li key={i} className="flex gap-2 text-aviso"><TriangleAlert size={14} className="mt-0.5 shrink-0" /> {a}</li>
                    ))}
                  </ul>
                )}
              </Tarjeta>
            </>
          )}
        </section>
      </div>
    </main>
  );
}

function Chip({ children }: { children: React.ReactNode }) {
  return <span className="inline-flex items-center gap-1 rounded-full bg-hundido px-2.5 py-0.5 text-tinta-2">{children}</span>;
}

function Dato({ icono, titulo, children }: { icono: React.ReactNode; titulo: string; children?: React.ReactNode }) {
  return (
    <div className="flex gap-2">
      <span className="mt-0.5 text-acento">{icono}</span>
      <span><span className="font-semibold">{titulo}</span>{children ? <span className="block text-tinta-2">{children}</span> : null}</span>
    </div>
  );
}

function CopiarTexto({ texto }: { texto: string }) {
  const [hecho, setHecho] = useState(false);
  return (
    <button className="boton boton-fantasma !px-2 !py-1 text-xs"
      onClick={async () => { await navigator.clipboard.writeText(texto); setHecho(true); setTimeout(() => setHecho(false), 1500); }}>
      {hecho ? <Check size={12} /> : <Copy size={12} />} {hecho ? "Copiado" : "Copiar"}
    </button>
  );
}
