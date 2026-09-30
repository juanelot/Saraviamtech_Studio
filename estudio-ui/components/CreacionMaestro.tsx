"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import {
  ArrowLeft, Bot, CheckCircle2, Clapperboard, Download, FileText, Image as Imagen, Link2, Loader2, Merge, Pause, Play,
  RefreshCw, Send, Sparkles, Star, Trash2, Upload, Video, X,
} from "lucide-react";
import { AvisoError, Tarjeta } from "./ui";
import TextoRico from "./TextoRico";
import { Copiar } from "./paneles/PanelEscenas";
import {
  creaciones, maestros, ultimoFotograma, type Creacion, type EscenaEntregable, type Entregables, type FichaMaestro,
  type Narracion, type Referencia,
} from "@/lib/api";

export default function CreacionMaestro({ id, cid }: { id: string; cid: string }) {
  const router = useRouter();
  const [c, setC] = useState<Creacion | null>(null);
  const [nombreMaestro, setNombreMaestro] = useState("");
  const [ficha, setFicha] = useState<FichaMaestro | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [texto, setTexto] = useState("");
  const [titulo, setTitulo] = useState("");
  const [enviando, setEnviando] = useState(false);
  const fin = useRef<HTMLDivElement>(null);
  const temporizador = useRef<ReturnType<typeof setTimeout> | null>(null);

  const cargar = useCallback(async () => {
    try {
      const x = await creaciones.ver(id, cid);
      setC((previo) => {
        if (!previo) setTitulo(x.titulo);
        return x;
      });
    } catch (e) {
      setError(String((e as Error).message || e));
    }
  }, [id, cid]);

  useEffect(() => {
    // cargar es async: el setState ocurre tras el fetch.
    // eslint-disable-next-line react-hooks/set-state-in-effect
    cargar();
    maestros.ver(id).then((m) => { setNombreMaestro(m.nombre); setFicha(m.ficha); }).catch(() => {});
  }, [cargar, id]);

  const ocupado = !!c?.pensando;
  useEffect(() => {
    if (!ocupado) return;
    const t = setInterval(cargar, 2500);
    return () => clearInterval(t);
  }, [ocupado, cargar]);

  const nTurnos = c?.turnos.length ?? 0;
  useEffect(() => {
    fin.current?.scrollIntoView({ behavior: "smooth", block: "end" });
  }, [nTurnos, ocupado]);

  async function accion(f: () => Promise<Creacion>) {
    setError(null);
    setEnviando(true);
    try {
      setC(await f());
    } catch (e) {
      setError(String((e as Error).message || e));
    } finally {
      setEnviando(false);
    }
  }

  function enviar(mensaje: string) {
    if (!mensaje.trim()) return;
    accion(() => creaciones.enviar(id, cid, mensaje.trim())).then(() => setTexto(""));
  }

  function renombrar(v: string) {
    setTitulo(v);
    if (temporizador.current) clearTimeout(temporizador.current);
    temporizador.current = setTimeout(() => creaciones.cambiar(id, cid, { titulo: v }).catch(() => {}), 700);
  }

  if (!c) {
    return <main className="mx-auto max-w-6xl px-4 py-16">{error ? <AvisoError texto={error} /> : <Loader2 className="animate-spin text-tinta-3" />}</main>;
  }

  const ultimo = [...c.turnos].reverse().find((t) => t.rol === "claude");
  const app = ultimo?.app;
  const terminado = app?.tipo === "fin";
  const esperaPersona = !ocupado && c.turnos.length > 0 && c.turnos[c.turnos.length - 1].rol === "claude";
  const fallido = !ocupado && !!c.error && (c.turnos.length === 0 || c.turnos[c.turnos.length - 1].rol === "persona");
  const auto = c.modo === "auto";

  return (
    <main className="mx-auto max-w-7xl px-4 pb-10 pt-6">
      <div className="mb-5 flex flex-wrap items-center gap-3">
        <Link href={`/maestros/${id}`} className="boton boton-fantasma !px-2.5" aria-label="Volver"><ArrowLeft size={16} /></Link>
        <div className="min-w-0 flex-1">
          <p className="etiqueta truncate">{nombreMaestro || "Prompt maestro"}</p>
          <input value={titulo} aria-label="Titulo" onChange={(e) => renombrar(e.target.value)}
            className="w-full bg-transparent font-display text-2xl font-semibold tracking-tight outline-none" />
        </div>
        <button className={`boton ${auto ? "boton-acento" : "boton-linea"}`} disabled={enviando || terminado}
          title={auto ? "Parar el modo automatico" : "Que Claude avance solo con la opcion recomendada"}
          onClick={() => accion(() => creaciones.cambiar(id, cid, { modo: auto ? "guiado" : "auto" }))}>
          {auto ? <><Pause size={15} /> Parar automatico</> : <><Play size={15} /> Automatico</>}
        </button>
        <button className="boton boton-fantasma !px-2.5" title="Borrar esta creacion" disabled={ocupado}
          onClick={async () => {
            if (!confirm("¿Borrar esta creacion?")) return;
            await creaciones.borrar(id, cid);
            router.push(`/maestros/${id}`);
          }}>
          <Trash2 size={16} />
        </button>
      </div>

      <div className="grid gap-5 lg:grid-cols-[1fr_420px]">
        <section className="min-w-0">
          <div className="space-y-4">
            {c.turnos.map((t, i) =>
              t.rol === "persona" ? (
                <div key={i} className="flex justify-end">
                  <div className="max-w-[85%] whitespace-pre-wrap rounded-2xl rounded-br-md bg-acento-suave px-4 py-2.5 text-sm">
                    {t.auto && <span className="mb-1 flex items-center gap-1 text-[11px] font-semibold text-acento"><Bot size={11} /> respuesta automatica</span>}
                    {t.texto}
                  </div>
                </div>
              ) : (
                <div key={i} className="group rounded-2xl rounded-bl-md border border-linea bg-tarjeta px-4 py-3 text-sm">
                  <TextoRico texto={t.texto} />
                  <div className="mt-2 flex justify-end opacity-60 transition group-hover:opacity-100"><Copiar texto={t.texto} /></div>
                </div>
              ),
            )}

            {ocupado && (
              <div className="latido flex items-center gap-2 rounded-2xl border border-dashed border-linea px-4 py-3 text-sm text-tinta-2">
                <Loader2 size={15} className="animate-spin text-acento" />
                {c.entregables_estado === "preparando" ? "Ordenando los entregables…"
                  : auto ? "Modo automatico: Claude avanza paso a paso…"
                  : "Claude esta escribiendo… (los pasos con muchos prompts tardan 1-3 min)"}
              </div>
            )}

            <AvisoError texto={error || c.error} />
            {fallido && (
              <button className="boton boton-linea text-sm" disabled={enviando} onClick={() => accion(() => creaciones.reintentar(id, cid))}>
                <RefreshCw size={14} /> Reintentar
              </button>
            )}
            <div ref={fin} />
          </div>

          <div className="sticky bottom-0 mt-5 rounded-2xl border border-linea bg-papel/95 p-3 shadow-sm backdrop-blur">
            {terminado && (
              <p className="mb-2 flex items-center gap-2 text-sm text-ok"><CheckCircle2 size={15} /> El flujo del prompt maestro termino. Puedes pedir cambios igualmente.</p>
            )}
            {esperaPersona && !!app?.opciones.length && (
              <div className="mb-2 flex flex-wrap gap-1.5">
                {app.opciones.map((o) => {
                  const rec = o === app.recomendada;
                  return (
                    <button key={o} disabled={enviando} onClick={() => enviar(o)}
                      className={`boton !py-1.5 text-sm ${rec ? "boton-acento" : "boton-linea"}`}>
                      {rec && <Star size={12} />} {o}
                    </button>
                  );
                })}
              </div>
            )}
            <div className="flex items-end gap-2">
              <textarea className="campo max-h-40 min-h-[44px] flex-1 resize-y" rows={1} value={texto} disabled={ocupado}
                placeholder={ocupado ? "Espera a que Claude termine…" : "Escribe tu respuesta, o pide un cambio (Enter envia, Shift+Enter salta de linea)"}
                onChange={(e) => setTexto(e.target.value)}
                onKeyDown={(e) => {
                  if (e.key === "Enter" && !e.shiftKey) {
                    e.preventDefault();
                    enviar(texto);
                  }
                }} />
              <button className="boton boton-acento" disabled={ocupado || enviando || !texto.trim()} onClick={() => enviar(texto)} aria-label="Enviar">
                <Send size={15} />
              </button>
            </div>
          </div>
        </section>

        <aside className="lg:sticky lg:top-20 lg:max-h-[calc(100vh-6rem)] lg:overflow-y-auto">
          {c.entregables && c.entregables.escenas.length > 0 && (
            <CrearVideo c={c} mid={id} ficha={ficha} ocupado={ocupado || enviando} />
          )}
          <PanelEntregables c={c} mid={id} ocupado={ocupado || enviando} accion={accion}
            onPreparar={() => accion(() => creaciones.entregables(id, cid))}
            onEscenas={(escenas) => accion(() => creaciones.escenas(id, cid, escenas))} />
        </aside>
      </div>
    </main>
  );
}

// ------------------------------------------------------------------ entregables

function descargar(nombre: string, contenido: string, tipo = "text/plain") {
  const url = URL.createObjectURL(new Blob([contenido], { type: `${tipo};charset=utf-8` }));
  const a = document.createElement("a");
  a.href = url;
  a.download = nombre;
  a.click();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}

function slug(t: string) {
  return t.toLowerCase().normalize("NFD").replace(/[̀-ͯ]/g, "").replace(/[^a-z0-9]+/g, "-").replace(/^-|-$/g, "").slice(0, 50) || "creacion";
}

function scriptJson(e: Entregables) {
  return JSON.stringify({
    scenes: e.escenas.map((s) => ({
      scene_number: s.n, image_prompt: s.imagen || "", video_prompt: s.video || "", narration: s.narracion || "",
    })),
  }, null, 2);
}

const NARRACIONES: { v: Narracion; t: string; d: string }[] = [
  { v: "propia", t: "Su guion", d: "La narracion que escribio el prompt maestro, tal cual." },
  { v: "demostracion", t: "Guion demostracion", d: "Claude narra lo que se ve en cada escena, ajustado a su duracion." },
  { v: "libre", t: "Guion libre", d: "Claude redacta un guion del tema para la duracion total; lo puedes editar en Guion." },
  { v: "sin_voz", t: "Sin voz", d: "Sin locucion ni subtitulos: suena el audio de los clips (ASMR, efectos, dialogos de Veo)." },
];

function CrearVideo({ c, mid, ficha, ocupado }: { c: Creacion; mid: string; ficha: FichaMaestro | null; ocupado: boolean }) {
  const router = useRouter();
  const e = c.entregables as Entregables;
  const tieneGuion = !!e.guion || e.escenas.some((s) => s.narracion);
  const opciones = NARRACIONES.filter((n) => n.v !== "propia" || tieneGuion);
  const [narracion, setNarracion] = useState<Narracion>(tieneGuion ? "propia" : "demostracion");
  const aspectoFicha = ["9:16", "16:9", "1:1"].includes(ficha?.formato?.aspecto || "") ? (ficha?.formato?.aspecto as string) : "9:16";
  const [aspecto, setAspecto] = useState<string | null>(null);
  const [creando, setCreando] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const formato = aspecto || aspectoFicha;

  async function crear() {
    setCreando(true);
    setError(null);
    try {
      const r = await creaciones.video(mid, c.id, { narracion, aspecto: formato });
      router.push(`/p/${r.proyecto.id}`);
    } catch (err) {
      setError(String((err as Error).message || err));
      setCreando(false);
    }
  }

  return (
    <Tarjeta titulo="Crear video en el Estudio" className="mb-5 border-acento/40">
      <div className="space-y-4 text-sm">
        <div>
          <p className="etiqueta mb-2">Narracion</p>
          <div className="space-y-1.5">
            {opciones.map((n) => (
              <label key={n.v} className={`flex cursor-pointer gap-2.5 rounded-xl border px-3 py-2 transition ${narracion === n.v ? "border-acento bg-acento-suave" : "border-linea hover:bg-hundido"}`}>
                <input type="radio" name="narracion" className="mt-1 accent-[var(--acento)]" checked={narracion === n.v} onChange={() => setNarracion(n.v)} />
                <span><span className="font-semibold">{n.t}</span><span className="block text-xs text-tinta-2">{n.d}</span></span>
              </label>
            ))}
          </div>
        </div>
        <div>
          <p className="etiqueta mb-2">Formato</p>
          <div className="flex gap-1.5">
            {["9:16", "16:9", "1:1"].map((a) => (
              <button key={a} className={`boton !py-1 text-xs ${formato === a ? "boton-acento" : "boton-linea"}`} onClick={() => setAspecto(a)}>{a}</button>
            ))}
          </div>
        </div>
        <AvisoError texto={error} />
        <button className="boton boton-acento w-full justify-center" disabled={creando || ocupado} onClick={crear}>
          {creando ? <Loader2 size={15} className="animate-spin" /> : <Clapperboard size={15} />}
          {creando && narracion === "demostracion" ? "Claude escribe la narracion…" : "Crear proyecto"}
        </button>
        <p className="text-xs text-tinta-3">
          Se crea un video con {e.escenas.length === 1 ? "1 escena" : `las ${e.escenas.length} escenas`} y sus prompts ya
          puestos (si sobra o falta alguna, unelas o quitalas abajo en Entregables). Luego: genera la voz, sube lo que
          hagas en Flow en el paso Contenido (cada archivo con su numero de escena) y monta el video.
        </p>
        {!!c.proyectos?.length && (
          <div className="border-t border-linea pt-3">
            <p className="etiqueta mb-1.5">Videos creados</p>
            {c.proyectos.map((p) => (
              <Link key={p.id} href={`/p/${p.id}`} className="block rounded-lg px-2 py-1 text-tinta-2 hover:bg-hundido">
                {NARRACIONES.find((n) => n.v === p.narracion)?.t} · {new Date(p.t * 1000).toLocaleString()}
              </Link>
            ))}
          </div>
        )}
      </div>
    </Tarjeta>
  );
}

function juntar(a: string | null, b: string | null) {
  return a && b ? `${a}\n\n${b}` : a || b;
}

// Unir dos escenas en una. Si solo una trae video, la otra era su imagen de
// referencia (storyboard, primer fotograma): la duracion es la del video.
function unir(a: EscenaEntregable, b: EscenaEntregable): EscenaEntregable {
  const suma = a.duracion_s && b.duracion_s ? a.duracion_s + b.duracion_s : a.duracion_s || b.duracion_s;
  const duracion = a.video && !b.video ? a.duracion_s : b.video && !a.video ? b.duracion_s : suma;
  return {
    n: a.n, narracion: [a.narracion, b.narracion].filter(Boolean).join(" ") || null,
    imagen: juntar(a.imagen, b.imagen), video: juntar(a.video, b.video), duracion_s: duracion ?? null,
    continua: a.continua, refs: [...new Set([...(a.refs || []), ...(b.refs || [])])],
  };
}

type Accion = (f: () => Promise<Creacion>) => Promise<void>;

function PanelEntregables({ c, mid, ocupado, accion, onPreparar, onEscenas }: {
  c: Creacion; mid: string; ocupado: boolean; accion: Accion; onPreparar: () => void;
  onEscenas: (escenas: EscenaEntregable[]) => void;
}) {
  const e = c.entregables;
  const hayRespuestas = c.turnos.some((t) => t.rol === "claude");
  const base = slug(e?.titulo || c.titulo);
  const imagenes = e?.escenas.filter((s) => s.imagen).map((s) => s.imagen as string) || [];
  const videos = e?.escenas.filter((s) => s.video).map((s) => s.video as string) || [];

  return (
    <Tarjeta titulo="Entregables" extra={
      <button className="boton boton-linea !py-1 text-xs" disabled={ocupado || !hayRespuestas} onClick={onPreparar}>
        {c.entregables_estado === "preparando" ? <Loader2 size={12} className="animate-spin" /> : <Sparkles size={12} />}
        {e ? "Actualizar" : "Preparar"}
      </button>
    }>
      {c.entregables_estado === "error" && <AvisoError texto={`No se pudieron ordenar: ${c.entregables_error}`} />}
      {!e ? (
        <p className="text-sm text-tinta-3">
          {c.entregables_estado === "preparando" ? "Claude esta ordenando guion y prompts…"
            : "Cuando el flujo termine se ordenan solos: guion, prompts de imagen y video por escena, miniaturas. Tambien puedes prepararlos en cualquier momento."}
        </p>
      ) : (
        <div className="space-y-5 text-sm">
          <div className="flex flex-wrap gap-1.5">
            {e.guion && <Boton onClick={() => descargar(`${base}-guion.txt`, e.guion as string)}><FileText size={13} /> guion.txt</Boton>}
            {imagenes.length > 0 && <Boton onClick={() => descargar(`${base}-prompts-imagen.txt`, imagenes.join("\n\n"))}><Imagen size={13} /> prompts imagen</Boton>}
            {videos.length > 0 && <Boton onClick={() => descargar(`${base}-prompts-video.txt`, videos.join("\n\n"))}><Video size={13} /> prompts video</Boton>}
            {e.escenas.length > 0 && <Boton onClick={() => descargar(`${base}-script.json`, scriptJson(e), "application/json")}><Download size={13} /> script.json</Boton>}
          </div>
          <p className="-mt-3 text-xs text-tinta-3">Los .txt van separados por linea en blanco; script.json es el formato de la extension de Flow.</p>

          {e.guion && (
            <Bloque titulo="Guion" copiar={e.guion}>
              <p className="whitespace-pre-wrap text-tinta-2">{e.guion}</p>
            </Bloque>
          )}

          {e.escenas.length > 0 && <PanelReferencias c={c} mid={mid} ocupado={ocupado} accion={accion} />}

          {e.escenas.length > 0 && (
            <div>
              <p className="etiqueta mb-2">{e.escenas.length === 1 ? "1 escena" : `${e.escenas.length} escenas`}</p>
              <ol className="space-y-2">
                {e.escenas.map((s, k) => (
                  <li key={s.n}>
                    <details className="rounded-xl border border-linea bg-hundido/40 px-3 py-2">
                      <summary className="cursor-pointer list-none">
                        <span className="flex items-center gap-1.5">
                          <span className="font-semibold">Escena {s.n}</span>
                          <span className="text-tinta-3">·</span>
                          <input type="number" min={0.5} max={600} step={0.5} key={`${s.n}-${s.duracion_s}`}
                            defaultValue={s.duracion_s ?? ""} placeholder="—" disabled={ocupado}
                            title="Duracion de la escena en segundos"
                            className="w-14 rounded-md border border-linea bg-tarjeta px-1.5 py-0.5 text-xs"
                            onClick={(ev) => ev.stopPropagation()}
                            onBlur={(ev) => {
                              const v = ev.currentTarget.value === "" ? null : Number(ev.currentTarget.value);
                              if (v !== s.duracion_s && (v === null || (v >= 0.5 && v <= 600)))
                                onEscenas(e.escenas.map((x) => (x.n === s.n ? { ...x, duracion_s: v } : x)));
                            }} />
                          <span className="text-xs text-tinta-3">s</span>
                          <span className="ml-auto flex gap-1">
                            {k > 0 && (
                              <button className="rounded-md p-1 text-tinta-3 hover:bg-tarjeta hover:text-tinta" disabled={ocupado}
                                title="Unir con la escena anterior (p. ej. la imagen de referencia con su video)"
                                onClick={(ev) => {
                                  ev.preventDefault();
                                  onEscenas([...e.escenas.slice(0, k - 1), unir(e.escenas[k - 1], s), ...e.escenas.slice(k + 1)]);
                                }}><Merge size={13} /></button>
                            )}
                            {e.escenas.length > 1 && (
                              <button className="rounded-md p-1 text-tinta-3 hover:bg-tarjeta hover:text-red-500" disabled={ocupado}
                                title="Quitar esta escena"
                                onClick={(ev) => {
                                  ev.preventDefault();
                                  if (confirm(`¿Quitar la escena ${s.n}?`)) onEscenas(e.escenas.filter((x) => x.n !== s.n));
                                }}><X size={13} /></button>
                            )}
                          </span>
                        </span>
                        {s.narracion && <span className="mt-0.5 line-clamp-2 block text-tinta-2">{s.narracion}</span>}
                        {(s.continua || !!s.refs?.length) && (
                          <span className="mt-1.5 flex flex-wrap gap-1">
                            {s.continua && (
                              <span className="flex items-center gap-1 rounded-full bg-acento-suave px-2 py-0.5 text-[11px] font-semibold text-acento"
                                title="Crea este clip empezando por el ultimo fotograma del clip anterior">
                                <Link2 size={10} /> sigue a la escena {e.escenas[k - 1]?.n}
                              </span>
                            )}
                            {s.refs?.map((r) => (
                              <span key={r} className="rounded-full border border-linea px-2 py-0.5 text-[11px] text-tinta-2">{r}</span>
                            ))}
                          </span>
                        )}
                      </summary>
                      <div className="mt-2 space-y-2">
                        {s.imagen && <Prompt icono={<Imagen size={12} />} titulo="Imagen" texto={s.imagen} />}
                        {s.video && <Prompt icono={<Video size={12} />} titulo="Video" texto={s.video} />}
                      </div>
                    </details>
                  </li>
                ))}
              </ol>
              <UltimoFotograma destacado={e.escenas.some((s) => s.continua)} />
            </div>
          )}

          {e.miniaturas.length > 0 && (
            <div>
              <p className="etiqueta mb-2">Miniaturas</p>
              <div className="space-y-2">
                {e.miniaturas.map((m, i) => (
                  <details key={i} className="rounded-xl border border-linea bg-hundido/40 px-3 py-2">
                    <summary className="cursor-pointer list-none">
                      <span className="font-semibold">Miniatura {i + 1}</span>
                      <span className="mt-0.5 line-clamp-2 block text-tinta-2">{m}</span>
                    </summary>
                    <div className="mt-2"><Prompt titulo="Prompt" texto={m} /></div>
                  </details>
                ))}
              </div>
            </div>
          )}

          {e.bloques.map((b, i) => (
            <Bloque key={i} titulo={b.titulo} copiar={b.texto}>
              <pre className="max-h-60 overflow-auto whitespace-pre-wrap font-mono text-xs text-tinta-2">{b.texto}</pre>
            </Bloque>
          ))}

        </div>
      )}
    </Tarjeta>
  );
}

const TIPOS_REF: Record<Referencia["tipo"], string> = {
  personaje: "Personaje", vehiculo: "Vehiculo", objeto: "Objeto", lugar: "Lugar", estilo: "Estilo", otro: "Referencia",
};

function PanelReferencias({ c, mid, ocupado, accion }: { c: Creacion; mid: string; ocupado: boolean; accion: Accion }) {
  const refs = c.entregables?.referencias || [];
  const [proponiendo, setProponiendo] = useState(false);
  const [subiendo, setSubiendo] = useState<string | null>(null);

  async function proponer() {
    setProponiendo(true);
    await accion(() => creaciones.proponerReferencias(mid, c.id));
    setProponiendo(false);
  }

  async function subir(r: Referencia, archivo: File | undefined) {
    if (!archivo) return;
    setSubiendo(r.clave);
    await accion(() => creaciones.subirReferencia(mid, c.id, r.clave, archivo));
    setSubiendo(null);
  }

  return (
    <div>
      <div className="mb-2 flex items-center justify-between gap-2">
        <p className="etiqueta">Hojas de referencia</p>
        <button className="boton boton-linea !gap-1 !px-2.5 !py-1 text-xs" disabled={ocupado || proponiendo} onClick={proponer}
          title="Claude busca personajes, objetos y lugares que se repiten entre escenas y escribe su hoja">
          {proponiendo ? <Loader2 size={12} className="animate-spin" /> : <Sparkles size={12} />}
          {proponiendo ? "Claude lee las escenas…" : refs.length ? "Proponer mas" : "Proponer con Claude"}
        </button>
      </div>
      {!refs.length ? (
        <p className="text-xs text-tinta-3">
          Crea primero una imagen de cada personaje, vehiculo o lugar que se repite y adjuntala como ingrediente en cada
          clip de Flow: asi sale igual en todas las escenas.
        </p>
      ) : (
        <ul className="space-y-2">
          {refs.map((r) => (
            <li key={r.clave} className="rounded-xl border border-linea bg-hundido/40 p-2">
              <div className="flex gap-2.5">
                <label className={`relative flex h-16 w-16 shrink-0 cursor-pointer items-center justify-center overflow-hidden rounded-lg border border-dashed border-linea bg-tarjeta text-tinta-3 hover:border-acento ${ocupado ? "pointer-events-none opacity-60" : ""}`}
                  title={r.imagen ? "Cambiar la imagen" : "Subir la imagen que creaste"}>
                  {subiendo === r.clave ? <Loader2 size={16} className="animate-spin" />
                    // eslint-disable-next-line @next/next/no-img-element
                    : r.imagen ? <img src={creaciones.urlReferencia(mid, c.id, r)} alt={r.nombre} className="h-full w-full object-cover" />
                    : <Upload size={16} />}
                  <input type="file" accept="image/png,image/jpeg,image/webp" hidden
                    onChange={(ev) => { subir(r, ev.target.files?.[0]); ev.target.value = ""; }} />
                </label>
                <div className="min-w-0 flex-1">
                  <div className="flex items-center gap-1.5">
                    <span className="truncate font-semibold">{r.nombre}</span>
                    <span className="text-xs text-tinta-3">· {TIPOS_REF[r.tipo]}</span>
                    {r.origen === "claude" && <span title="Propuesta por Claude"><Sparkles size={11} className="text-acento" /></span>}
                    <span className="ml-auto flex gap-0.5">
                      {r.imagen && (
                        <a className="rounded-md p-1 text-tinta-3 hover:bg-tarjeta hover:text-tinta" title="Descargar la imagen"
                          href={creaciones.urlReferencia(mid, c.id, r)} download={r.archivo || r.imagen}><Download size={13} /></a>
                      )}
                      <button className="rounded-md p-1 text-tinta-3 hover:bg-tarjeta hover:text-red-500" disabled={ocupado}
                        title="Quitar esta referencia"
                        onClick={() => {
                          if (confirm(`¿Quitar la referencia "${r.nombre}"?`))
                            accion(() => creaciones.referencias(mid, c.id, refs.filter((x) => x.clave !== r.clave)));
                        }}><X size={13} /></button>
                    </span>
                  </div>
                  <p className="text-xs text-tinta-3">
                    {r.imagen ? "Imagen lista" : "Falta la imagen"}{r.archivo ? ` · guardala como ${r.archivo}` : ""}
                  </p>
                </div>
              </div>
              {r.prompt && (
                <details className="mt-1.5">
                  <summary className="cursor-pointer text-xs text-tinta-2">Prompt de la hoja</summary>
                  <div className="mt-1.5"><Prompt titulo="Prompt" texto={r.prompt} /></div>
                </details>
              )}
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

function UltimoFotograma({ destacado }: { destacado: boolean }) {
  const [trabajando, setTrabajando] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function sacar(archivo: File | undefined) {
    if (!archivo) return;
    setTrabajando(true);
    setError(null);
    try {
      const blob = await ultimoFotograma(archivo);
      const u = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = u;
      a.download = `${archivo.name.replace(/\.[^.]+$/, "")}-ultimo-fotograma.png`;
      a.click();
      setTimeout(() => URL.revokeObjectURL(u), 1000);
    } catch (err) {
      setError(String((err as Error).message || err));
    } finally {
      setTrabajando(false);
    }
  }

  return (
    <div className={`mt-3 rounded-xl border px-3 py-2 text-xs ${destacado ? "border-acento/50 bg-acento-suave" : "border-linea"}`}>
      <label className={`flex cursor-pointer items-center gap-2 ${trabajando ? "pointer-events-none opacity-70" : ""}`}>
        {trabajando ? <Loader2 size={14} className="animate-spin text-acento" /> : <Link2 size={14} className="text-acento" />}
        <span>
          <span className="font-semibold">Ultimo fotograma</span>
          <span className="block text-tinta-2">
            Elige el clip que acabas de crear y descarga su ultimo fotograma (PNG) para empezar el siguiente con el.
          </span>
        </span>
        <input type="file" accept="video/*" hidden onChange={(ev) => { sacar(ev.target.files?.[0]); ev.target.value = ""; }} />
      </label>
      <AvisoError texto={error} />
    </div>
  );
}

function Boton({ onClick, children }: { onClick: () => void; children: React.ReactNode }) {
  return <button className="boton boton-linea !gap-1 !px-2.5 !py-1 text-xs" onClick={onClick}>{children}</button>;
}

function Bloque({ titulo, copiar, children }: { titulo: string; copiar: string; children: React.ReactNode }) {
  return (
    <div>
      <div className="mb-1.5 flex items-center justify-between"><p className="etiqueta">{titulo}</p><Copiar texto={copiar} /></div>
      {children}
    </div>
  );
}

function Prompt({ titulo, texto, icono }: { titulo: string; texto: string; icono?: React.ReactNode }) {
  return (
    <div className="rounded-lg bg-tarjeta p-2.5">
      <div className="mb-1 flex items-center justify-between">
        <span className="flex items-center gap-1 text-xs font-semibold text-tinta-2">{icono} {titulo}</span>
        <Copiar texto={texto} />
      </div>
      <p className="whitespace-pre-wrap text-xs leading-relaxed text-tinta-2">{texto}</p>
    </div>
  );
}
