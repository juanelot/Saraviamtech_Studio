"use client";

import { useState } from "react";
import { Check, Copy, FileJson, FileText, Film, ImageIcon, Sparkles } from "lucide-react";
import type { PanelProps } from "../Proyecto";
import { AvisoError, Campo, Deslizador, Segmentado, Tarjeta } from "../ui";
import { mmss, url, type Escena } from "@/lib/api";
import { ESFUERZOS, MODELOS } from "./PanelMaterial";

export function Copiar({ texto, etiqueta = "Copiar" }: { texto: string; etiqueta?: string }) {
  const [hecho, setHecho] = useState(false);
  return (
    <button
      type="button"
      className="boton boton-fantasma !gap-1 !px-2 !py-1 text-xs"
      disabled={!texto}
      onClick={async () => {
        try {
          await navigator.clipboard.writeText(texto);
          setHecho(true);
          setTimeout(() => setHecho(false), 1500);
        } catch {}
      }}
    >
      {hecho ? <Check size={12} /> : <Copy size={12} />} {hecho ? "Copiado" : etiqueta}
    </button>
  );
}

export default function PanelEscenas({ id, vista, p, set, ejecutar, ocupado }: PanelProps) {
  const et = vista.etapas.escenas;
  const e = p("escenas");
  const a = p("asignacion");
  const modoEscenas = a.modo === "escenas";
  const generar = (e.generar as string) || "imagenes";
  const ediciones = (e.ediciones as Record<string, { image_prompt?: string; video_prompt?: string }>) || {};
  const escenas = et.salida?.escenas || [];
  const fijas = (e.fijas as unknown[]) || [];

  // Que escenas ya tienen contenido subido (por numero de archivo).
  const recursos = vista.etapas.recursos.salida?.recursos || [];
  const conImagen = new Set(recursos.filter((r) => r.tipo === "imagen" && r.escena != null).map((r) => r.escena));
  const conVideo = new Set(recursos.filter((r) => r.tipo === "video" && r.escena != null).map((r) => r.escena));

  function editar(n: number, campo: "image_prompt" | "video_prompt", valor: string) {
    const actual = ediciones[String(n)] || {};
    set("escenas", "ediciones", { ...ediciones, [String(n)]: { ...actual, [campo]: valor } });
  }

  function valor(x: Escena, campo: "image_prompt" | "video_prompt") {
    const ed = ediciones[String(x.scene_number)]?.[campo];
    return typeof ed === "string" ? ed : x[campo];
  }

  const todos = (campo: "image_prompt" | "video_prompt") =>
    escenas.map((x) => `${x.scene_number}. ${valor(x, campo)}`).filter((t) => t.length > 4).join("\n\n");

  return (
    <div className="space-y-5">
      <Tarjeta titulo="¿De donde salen las imagenes de este video?">
        <Segmentado
          valor={modoEscenas ? "escenas" : "recursos"}
          onChange={(v) => set("asignacion", "modo", v === "escenas" ? "escenas" : "claude")}
          opciones={[
            { v: "escenas", t: "Las creo yo en Flow / extension, escena por escena" },
            { v: "recursos", t: "Ya tengo mis recursos (Claude elige)" },
          ]}
        />
        <p className="mt-3 text-sm text-tinta-2">
          {modoEscenas && fijas.length
            ? "Tu generas el contenido de cada escena en Flow (o con la extension, usando el script.json) y lo subes en el paso Contenido: cada archivo va a su escena por su numero."
            : modoEscenas
            ? "Claude corta el guion en escenas y escribe los prompts. Tu generas el contenido en Flow (o con la extension, usando el script.json) y lo subes en el paso Contenido: cada archivo va a su escena por su numero."
            : "Este paso no hace falta: en Contenido subes tus imagenes y videos y Claude elige cual va en cada frase."}
        </p>
      </Tarjeta>

      {modoEscenas && fijas.length > 0 && (
        <Tarjeta titulo="Escenas del prompt maestro">
          <p className="text-sm text-tinta-2">
            Este video sale de un prompt maestro: sus {fijas.length} escenas y sus prompts ya vienen hechos. Aqui solo se
            colocan sobre la voz (cuando empieza y acaba cada una). Puedes corregir cualquier prompt abajo.
          </p>
          <button className="boton boton-acento mt-4" disabled={ocupado} onClick={() => ejecutar("escenas")}>
            <Sparkles size={15} /> {et.salida ? (et.estado === "ok" ? "Escenas al dia" : "Volver a colocar") : "Colocar escenas"}
          </button>
        </Tarjeta>
      )}

      {modoEscenas && (
        <>
          <AvisoError texto={et.error} />
          <div className={`grid gap-5 lg:grid-cols-[1.4fr_1fr] ${fijas.length ? "hidden" : ""}`}>
            <Tarjeta titulo="Escenas y prompts">
              <div className="space-y-4">
                <Campo etiqueta="Que prompts quieres">
                  <Segmentado
                    valor={generar}
                    onChange={(v) => set("escenas", "generar", v)}
                    opciones={[
                      { v: "imagenes", t: "Imagenes" },
                      { v: "imagenes_videos", t: "Imagenes + videos" },
                      { v: "no", t: "Solo cortar escenas" },
                    ]}
                  />
                </Campo>
                <Campo etiqueta="Duracion de cada escena" ayuda="Se agrupan frases hasta esta duracion. Un clip de Flow dura 8 s.">
                  <Deslizador valor={Number(e.segundos ?? 6)} min={0} max={15} paso={0.5}
                    onChange={(x) => set("escenas", "segundos", x)} formato={(x) => (x ? `${x}s` : "1 frase")} />
                </Campo>
                <Campo etiqueta="Estilo visual (se aplica a todas)" ayuda="Ej.: fotografia documental, luz natural · animacion 3D estilo Pixar · ilustracion editorial">
                  <input className="campo" value={(e.estilo as string) || ""} onChange={(ev) => set("escenas", "estilo", ev.target.value)} />
                </Campo>
                <Campo etiqueta="Indicaciones (opcional)" ayuda="Personajes fijos, epoca, colores, cosas a evitar…">
                  <textarea className="campo min-h-[70px]" value={(e.indicaciones as string) || ""}
                    onChange={(ev) => set("escenas", "indicaciones", ev.target.value)} />
                </Campo>
              </div>
            </Tarjeta>
            <Tarjeta titulo="Claude">
              <div className="space-y-3">
                <Campo etiqueta="Idioma de los prompts" ayuda="Flow entiende mejor el ingles. La narracion queda en su idioma.">
                  <select className="campo" value={(e.idioma_prompts as string) || "en"} onChange={(ev) => set("escenas", "idioma_prompts", ev.target.value)}>
                    <option value="en">Ingles</option>
                    <option value="es">Espanol</option>
                    <option value="pt">Portugues</option>
                  </select>
                </Campo>
                <div className="grid grid-cols-2 gap-3">
                  <Campo etiqueta="Modelo">
                    <select className="campo" value={(e.modelo as string) || "sonnet"} onChange={(ev) => set("escenas", "modelo", ev.target.value)}>
                      {MODELOS.map((m) => <option key={m.v} value={m.v}>{m.t}</option>)}
                    </select>
                  </Campo>
                  <Campo etiqueta="Esfuerzo">
                    <select className="campo" value={(e.esfuerzo as string) || "low"} onChange={(ev) => set("escenas", "esfuerzo", ev.target.value)}>
                      {ESFUERZOS.map((m) => <option key={m.v} value={m.v}>{m.t}</option>)}
                    </select>
                  </Campo>
                </div>
                <button className="boton boton-acento w-full justify-center" disabled={ocupado} onClick={() => ejecutar("escenas")}>
                  <Sparkles size={15} /> {et.salida ? (et.estado === "ok" ? "Escenas al dia" : "Aplicar cambios") : "Generar escenas y prompts"}
                </button>
              </div>
            </Tarjeta>
          </div>

          {et.salida && (
            <>
              <Tarjeta>
                <div className="flex flex-wrap items-center gap-2">
                  <p className="mr-auto text-sm text-tinta-2">
                    {et.salida.total} escenas · {et.salida.con_prompt} con prompt ·{" "}
                    {conImagen.size} con imagen y {conVideo.size} con video subidos
                  </p>
                  <a href={url.scriptJson(id)} className="boton boton-acento !py-1.5 text-sm" title="Para la extension AI Content Generator">
                    <FileJson size={15} /> Descargar script.json
                  </a>
                  <a href={url.promptsTxt(id)} className="boton boton-linea !py-1.5 text-sm"><FileText size={15} /> prompts.txt</a>
                  <Copiar texto={todos("image_prompt")} etiqueta="Copiar prompts de imagen" />
                  {(generar === "imagenes_videos" || fijas.length > 0) && <Copiar texto={todos("video_prompt")} etiqueta="Copiar prompts de video" />}
                </div>
                <p className="mt-3 text-xs text-tinta-3">
                  Extension: guarda el archivo como <code>script.json</code> en una carpeta vacia, genera con ella y luego
                  sube esa carpeta (o su ZIP) en <b>Contenido</b>. A mano: nombra cada archivo con su numero de escena
                  (1.png, scene_2.mp4…).
                </p>
              </Tarjeta>

              {et.estado === "obsoleta" && (
                <p className="rounded-xl bg-aviso-suave p-3 text-sm text-aviso">
                  Algo cambio (guion, voz, estilo o formato). Pulsa «Aplicar cambios» para actualizar las escenas.
                </p>
              )}

              <ol className="space-y-3">
                {escenas.map((x) => (
                  <li key={x.scene_number} className="rounded-2xl border border-linea bg-tarjeta p-4">
                    <div className="mb-2 flex flex-wrap items-center gap-2 text-xs">
                      <span className="rounded-full bg-tinta px-2.5 py-0.5 font-bold text-papel">Escena {x.scene_number}</span>
                      <span className="tabular-nums text-tinta-3">{mmss(x.inicio)} · {x.duracion.toFixed(1)}s</span>
                      <span className={`inline-flex items-center gap-1 rounded-full px-2 py-0.5 ${conImagen.has(x.scene_number) ? "bg-ok-suave text-ok" : "bg-hundido text-tinta-3"}`}>
                        <ImageIcon size={11} /> {conImagen.has(x.scene_number) ? "imagen subida" : "sin imagen"}
                      </span>
                      {generar === "imagenes_videos" && (
                        <span className={`inline-flex items-center gap-1 rounded-full px-2 py-0.5 ${conVideo.has(x.scene_number) ? "bg-ok-suave text-ok" : "bg-hundido text-tinta-3"}`}>
                          <Film size={11} /> {conVideo.has(x.scene_number) ? "video subido" : "sin video"}
                        </span>
                      )}
                    </div>
                    <p className="mb-3 text-sm text-tinta-2">«{x.narration}»</p>
                    {generar !== "no" && (
                      <div className={`grid gap-3 ${generar === "imagenes_videos" ? "md:grid-cols-2" : ""}`}>
                        {(["image_prompt", "video_prompt"] as const)
                          .filter((c) => c === "image_prompt" || generar === "imagenes_videos")
                          .map((campo) => (
                            <div key={campo}>
                              <div className="mb-1 flex items-center justify-between">
                                <span className="etiqueta">{campo === "image_prompt" ? "Prompt de imagen" : "Prompt de video"}
                                  {ediciones[String(x.scene_number)]?.[campo] !== undefined && " · editado"}</span>
                                <Copiar texto={valor(x, campo)} />
                              </div>
                              <textarea className="campo min-h-[110px] !text-[13px]" value={valor(x, campo)}
                                onChange={(ev) => editar(x.scene_number, campo, ev.target.value)} />
                            </div>
                          ))}
                      </div>
                    )}
                  </li>
                ))}
              </ol>
            </>
          )}
        </>
      )}
    </div>
  );
}
