"use client";

import { useCallback, useEffect, useState } from "react";
import { Download, ImageIcon, Loader2, Sparkles, Trash2, Upload } from "lucide-react";
import type { PanelProps } from "../Proyecto";
import { AvisoError, Campo, Segmentado, Tarjeta } from "../ui";
import { miniatura, mini, url, type EstadoMiniatura } from "@/lib/api";
import { ESFUERZOS, MODELOS } from "./PanelMaterial";
import { Copiar } from "./PanelEscenas";

type Params = EstadoMiniatura["params"];

export default function PanelMiniatura({ id, vista, p }: PanelProps) {
  const [est, setEst] = useState<EstadoMiniatura | null>(null);
  const [params, setParams] = useState<Params | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [subiendo, setSubiendo] = useState<"" | "referencia" | "final">("");

  const cargar = useCallback(async () => {
    try {
      const e = await miniatura.ver(id);
      setEst(e);
      setParams((x) => x || e.params);
    } catch (err) {
      setError(String((err as Error).message));
    }
  }, [id]);

  useEffect(() => {
    // cargar es async: el setState ocurre tras el fetch.
    // eslint-disable-next-line react-hooks/set-state-in-effect
    cargar();
  }, [cargar]);

  const generando = !!est?.generando;
  useEffect(() => {
    if (!generando) return;
    const t = setInterval(cargar, 2000);
    return () => clearInterval(t);
  }, [generando, cargar]);

  async function subir(tipo: "referencia" | "final", f?: File) {
    if (!f) return;
    setSubiendo(tipo);
    setError(null);
    try {
      setEst(await miniatura.subir(id, tipo, f));
    } catch (err) {
      setError(String((err as Error).message));
    } finally {
      setSubiendo("");
    }
  }

  async function quitar(tipo: "referencia" | "final") {
    try {
      setEst(await miniatura.quitar(id, tipo));
    } catch (err) {
      setError(String((err as Error).message));
    }
  }

  async function proponer() {
    if (!params) return;
    setError(null);
    try {
      setEst(await miniatura.generar(id, params));
    } catch (err) {
      setError(String((err as Error).message));
    }
  }

  if (!est || !params) return <Loader2 className="animate-spin text-tinta-3" />;

  const vertical = ["9:16", "4:5"].includes(String(p("render").aspecto || "16:9"));
  const aspecto = vertical ? "aspect-[9/16] max-w-[260px]" : "aspect-video";
  const recursos = vista.etapas.recursos.salida?.recursos || [];
  const hayGuion = !!vista.etapas.guion.salida?.texto;
  const estilo = String(p("escenas").estilo || "").trim();
  const v = est.version ? `?v=${est.version}` : "";
  const cambiar = (k: keyof Params, x: unknown) => setParams({ ...params, [k]: x } as Params);

  return (
    <div className="grid gap-5 lg:grid-cols-[1fr_1.35fr]">
      <div className="space-y-5">
        <Tarjeta titulo="Tu miniatura">
          {est.final ? (
            <div className="space-y-3">
              {/* eslint-disable-next-line @next/next/no-img-element */}
              <img src={url.archivo(id, est.final) + v} alt="Miniatura final"
                className={`${aspecto} w-full rounded-xl border border-linea object-cover`} />
              <div className="flex flex-wrap gap-2">
                <a href={url.descargarMiniatura(id)} className="boton boton-acento !py-1.5 text-sm"><Download size={14} /> Descargar</a>
                <Subir etiqueta="Cambiar" cargando={subiendo === "final"} onArchivo={(f) => subir("final", f)} />
                <button className="boton boton-fantasma !py-1.5 text-sm" onClick={() => quitar("final")}><Trash2 size={14} /> Quitar</button>
              </div>
              <p className="text-xs text-tinta-3">Es la portada del proyecto en Mis videos.</p>
            </div>
          ) : (
            <div className="space-y-3">
              <div className={`${aspecto} grid w-full place-items-center rounded-xl border border-dashed border-linea bg-hundido text-center text-sm text-tinta-3`}>
                <div className="px-4">
                  <ImageIcon className="mx-auto mb-2" size={22} />
                  ¿Ya la tienes? Subela aqui. Si no, pide conceptos a Claude, generala en Flow y subela.
                </div>
              </div>
              <Subir etiqueta="Subir miniatura" cargando={subiendo === "final"} onArchivo={(f) => subir("final", f)} />
            </div>
          )}
        </Tarjeta>

        <Tarjeta titulo="Referencia (opcional)">
          <p className="mb-3 text-sm text-tinta-2">
            Una miniatura que te guste (tuya o de otro canal). Claude copia su estilo: encuadre, colores, tipo de
            texto. No copia su contenido.
          </p>
          {est.referencia ? (
            <div className="flex items-start gap-3">
              {/* eslint-disable-next-line @next/next/no-img-element */}
              <img src={url.archivo(id, est.referencia) + v} alt="Referencia" className="h-28 rounded-lg border border-linea object-cover" />
              <div className="flex flex-col gap-2">
                <Subir etiqueta="Cambiar" cargando={subiendo === "referencia"} onArchivo={(f) => subir("referencia", f)} />
                <button className="boton boton-fantasma !py-1.5 text-sm" onClick={() => quitar("referencia")}><Trash2 size={14} /> Quitar</button>
              </div>
            </div>
          ) : (
            <Subir etiqueta="Subir referencia" cargando={subiendo === "referencia"} onArchivo={(f) => subir("referencia", f)} />
          )}
        </Tarjeta>
      </div>

      <div className="space-y-5">
        <AvisoError texto={error || est.error} />
        <Tarjeta titulo="Conceptos con Claude">
          <div className="space-y-4">
            <div className="flex flex-wrap gap-1.5 text-xs">
              <Uso ok={hayGuion} texto="Guion" />
              <Uso ok={!!estilo} texto="Estilo de las escenas" />
              <Uso ok={!!est.referencia} texto="Referencia" />
              <Uso ok={recursos.length > 0} texto={`Imagenes del proyecto${recursos.length ? ` (${Math.min(4, recursos.length)})` : ""}`} />
            </div>
            <Campo etiqueta="Texto">
              <Segmentado
                valor={params.texto_en_imagen ? "si" : "no"}
                onChange={(x) => cambiar("texto_en_imagen", x === "si")}
                opciones={[{ v: "si", t: "Dentro de la imagen" }, { v: "no", t: "Sin texto (lo pongo yo)" }]}
              />
            </Campo>
            <Campo etiqueta="Indicaciones (opcional)" ayuda="Ej.: mi cara sorprendida a la derecha · texto amarillo · fondo de Wall Street de noche">
              <textarea className="campo min-h-[70px]" value={params.indicaciones}
                onChange={(e) => cambiar("indicaciones", e.target.value)} />
            </Campo>
            <div className="grid grid-cols-3 gap-3">
              <Campo etiqueta="Conceptos">
                <select className="campo" value={params.cantidad} onChange={(e) => cambiar("cantidad", Number(e.target.value))}>
                  {[1, 2, 3, 4, 5].map((n) => <option key={n} value={n}>{n}</option>)}
                </select>
              </Campo>
              <Campo etiqueta="Modelo">
                <select className="campo" value={params.modelo} onChange={(e) => cambiar("modelo", e.target.value)}>
                  {MODELOS.map((m) => <option key={m.v} value={m.v}>{m.t}</option>)}
                </select>
              </Campo>
              <Campo etiqueta="Esfuerzo">
                <select className="campo" value={params.esfuerzo} onChange={(e) => cambiar("esfuerzo", e.target.value)}>
                  {ESFUERZOS.map((m) => <option key={m.v} value={m.v}>{m.t}</option>)}
                </select>
              </Campo>
            </div>
            <button className="boton boton-acento w-full justify-center" disabled={generando} onClick={proponer}>
              {generando ? <><Loader2 size={15} className="animate-spin" /> Claude esta pensando…</> : <><Sparkles size={15} /> {est.conceptos.length ? "Proponer otras" : "Proponer miniaturas"}</>}
            </button>
          </div>
        </Tarjeta>

        {est.analisis_referencia && (
          <p className="rounded-xl bg-acento-suave p-3 text-sm"><b>De tu referencia:</b> {est.analisis_referencia}</p>
        )}

        {est.conceptos.map((c, i) => {
          const refEsc = c.referencia_escena != null ? recursos.find((r) => r.escena === c.referencia_escena) : undefined;
          return (
            <Tarjeta key={i}>
              <div className="mb-2 flex flex-wrap items-center gap-2">
                <span className="rounded-full bg-tinta px-2.5 py-0.5 text-xs font-bold text-papel">{i + 1}</span>
                <span className="font-display font-semibold">{c.nombre}</span>
              </div>
              <p className="mb-3 text-sm text-tinta-2">{c.idea}</p>
              {c.texto && (
                <p className="mb-3 inline-block rounded-lg bg-tinta px-3 py-1.5 font-display text-lg font-bold uppercase tracking-tight text-papel">
                  {c.texto}
                </p>
              )}
              <Prompt titulo={params.texto_en_imagen ? "Prompt (con texto)" : "Prompt"} texto={c.prompt} />
              {params.texto_en_imagen && c.prompt_sin_texto && (
                <details className="mt-2">
                  <summary className="cursor-pointer text-xs text-tinta-3">Version sin texto (para ponerlo en Canva)</summary>
                  <div className="mt-2"><Prompt titulo="Prompt sin texto" texto={c.prompt_sin_texto} /></div>
                </details>
              )}
              {c.referencia_escena != null && (
                <div className="mt-3 flex items-center gap-3 rounded-xl bg-hundido p-2.5 text-xs text-tinta-2">
                  {refEsc && (
                    // eslint-disable-next-line @next/next/no-img-element
                    <img src={url.miniatura(mini(refEsc))} alt="" className="h-12 w-16 rounded-md object-cover" />
                  )}
                  <span>En Flow, añade la imagen de la <b>escena {c.referencia_escena}</b> como referencia para mantener el personaje y el estilo.</span>
                </div>
              )}
            </Tarjeta>
          );
        })}
      </div>
    </div>
  );
}

function Uso({ ok, texto }: { ok: boolean; texto: string }) {
  return (
    <span className={`rounded-full px-2.5 py-0.5 ${ok ? "bg-ok-suave text-ok" : "bg-hundido text-tinta-3"}`}>
      {ok ? "✓" : "–"} {texto}
    </span>
  );
}

function Prompt({ titulo, texto }: { titulo: string; texto: string }) {
  return (
    <div>
      <div className="mb-1 flex items-center justify-between">
        <span className="etiqueta">{titulo}</span>
        <Copiar texto={texto} />
      </div>
      <p className="whitespace-pre-wrap rounded-xl border border-linea bg-hundido p-3 text-[13px] leading-relaxed">{texto}</p>
    </div>
  );
}

function Subir({ etiqueta, cargando, onArchivo }: { etiqueta: string; cargando: boolean; onArchivo: (f?: File) => void }) {
  return (
    <label className={`boton boton-linea cursor-pointer !py-1.5 text-sm ${cargando ? "pointer-events-none opacity-50" : ""}`}>
      {cargando ? <Loader2 size={14} className="animate-spin" /> : <Upload size={14} />} {etiqueta}
      <input type="file" accept="image/png,image/jpeg,image/webp" className="hidden"
        onChange={(e) => { onArchivo(e.target.files?.[0]); e.target.value = ""; }} />
    </label>
  );
}
