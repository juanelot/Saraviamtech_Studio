"use client";

// Tarjeta "Publicar" del paso Video (con el video ya montado): titulos, descripcion y
// hashtags; capitulos de YouTube; subtitulos (descargar y traducir); y analisis del
// gancho con ganchos alternativos que se pueden regrabar en el primer plano.

import { useEffect, useState } from "react";
import { Check, Copy, Download, Loader2, Mic, Sparkles } from "lucide-react";
import type { PanelProps } from "../Proyecto";
import { AvisoError, Segmentado, Tarjeta } from "../ui";
import { api, url, type DatosPublicar, type Gancho } from "@/lib/api";
import { frasesConTexto, ponerParche, type Parche } from "../editor/modelo";

type Pestana = "textos" | "capitulos" | "subtitulos" | "gancho";

export default function Publicar({ id, p, set }: Pick<PanelProps, "id" | "p" | "set">) {
  const [datos, setDatos] = useState<DatosPublicar | null>(null);
  const [pestana, setPestana] = useState<Pestana>("textos");
  const [plataforma, setPlataforma] = useState("youtube");
  const [ocupado, setOcupado] = useState("");
  const [error, setError] = useState("");
  useEffect(() => { api.publicar(id).then(setDatos).catch(() => {}); }, [id]);

  async function hacer(accion: string, body: Record<string, string> = {}) {
    setOcupado(accion + (body.idioma || "")); setError("");
    try {
      await api.hacerPublicar(id, accion, { plataforma, ...body });
      setDatos(await api.publicar(id));
    } catch (e) { setError(String((e as Error).message)); } finally { setOcupado(""); }
  }
  if (!datos) return null;
  const boton = (accion: string, texto: string, hecho: boolean) => (
    <button className="boton boton-acento !py-1.5 text-sm" disabled={!!ocupado} onClick={() => hacer(accion)}>
      {ocupado === accion ? <Loader2 size={14} className="animate-spin" /> : <Sparkles size={14} />} {hecho ? "Otra vez" : texto}
    </button>
  );

  return (
    <Tarjeta titulo="Publicar">
      <div className="space-y-4">
        <Segmentado valor={pestana} onChange={setPestana}
          opciones={[{ v: "textos", t: "Titulo y descripcion" }, { v: "capitulos", t: "Capitulos" }, { v: "subtitulos", t: "Subtitulos" }, { v: "gancho", t: "Gancho" }]} />
        {(pestana === "textos" || pestana === "gancho") && (
          <label className="flex items-center gap-2 text-sm text-tinta-2">
            Para
            <select className="campo !w-auto !py-1 text-sm" value={plataforma} onChange={(e) => setPlataforma(e.target.value)}>
              {Object.entries(datos.plataformas).map(([v, t]) => <option key={v} value={v}>{t}</option>)}
            </select>
          </label>
        )}
        <AvisoError texto={error} />

        {pestana === "textos" && (
          <div className="space-y-3">
            {boton("metadatos", "Proponer titulo, descripcion y hashtags", !!datos.metadatos)}
            {datos.metadatos && (
              <>
                <div>
                  <p className="etiqueta mb-1">Titulos ({datos.plataformas[datos.metadatos.plataforma]})</p>
                  <ul className="space-y-1">
                    {datos.metadatos.titulos.map((t) => <Copiable key={t} texto={t} />)}
                  </ul>
                </div>
                <div>
                  <div className="mb-1 flex items-center justify-between"><p className="etiqueta">Descripcion</p><BotonCopiar texto={datos.metadatos.descripcion} /></div>
                  <p className="whitespace-pre-wrap rounded-lg border border-linea bg-hundido p-2 text-sm">{datos.metadatos.descripcion}</p>
                </div>
                <div>
                  <div className="mb-1 flex items-center justify-between"><p className="etiqueta">Hashtags</p><BotonCopiar texto={datos.metadatos.hashtags.join(" ")} /></div>
                  <p className="text-sm text-acento">{datos.metadatos.hashtags.join(" ")}</p>
                </div>
                {datos.metadatos.etiquetas.length > 0 && (
                  <div>
                    <div className="mb-1 flex items-center justify-between"><p className="etiqueta">Etiquetas de YouTube</p><BotonCopiar texto={datos.metadatos.etiquetas.join(", ")} /></div>
                    <p className="text-xs text-tinta-2">{datos.metadatos.etiquetas.join(", ")}</p>
                  </div>
                )}
              </>
            )}
          </div>
        )}

        {pestana === "capitulos" && (
          <div className="space-y-3">
            <p className="text-xs text-tinta-3">Para la descripcion de YouTube: los tiempos son los del video montado. YouTube pide al menos 3 capitulos de 10 s o mas.</p>
            {boton("capitulos", "Proponer capitulos", !!datos.capitulos)}
            {datos.capitulos && (
              <div>
                <div className="mb-1 flex items-center justify-between"><p className="etiqueta">{datos.capitulos.lista.length} capitulos</p><BotonCopiar texto={datos.capitulos.texto} /></div>
                <pre className="whitespace-pre-wrap rounded-lg border border-linea bg-hundido p-2 text-sm">{datos.capitulos.texto}</pre>
              </div>
            )}
          </div>
        )}

        {pestana === "subtitulos" && (
          <Subtitulos id={id} datos={datos} ocupado={ocupado} traducir={(idioma) => hacer("traducir", { idioma })} />
        )}

        {pestana === "gancho" && (
          <div className="space-y-3">
            <p className="text-xs text-tinta-3">Claude juzga los primeros segundos (lo que hace que la gente se quede) y propone otros ganchos que caben en el primer plano.</p>
            {boton("gancho", "Analizar el gancho", !!datos.gancho)}
            {datos.gancho && <VerGancho id={id} g={datos.gancho} p={p} set={set} />}
          </div>
        )}
      </div>
    </Tarjeta>
  );
}

function Subtitulos({ id, datos, ocupado, traducir }: {
  id: string; datos: DatosPublicar; ocupado: string; traducir: (idioma: string) => void;
}) {
  const [idioma, setIdioma] = useState("en");
  const hechas = datos.traducciones || [];
  return (
    <div className="space-y-3">
      <p className="text-xs text-tinta-3">SRT con los tiempos del video montado (con tus frases corregidas), para subirlo a YouTube como subtitulos.</p>
      <a className="boton boton-linea !py-1.5 text-sm" href={url.srtVideo(id)}><Download size={14} /> Descargar SRT</a>
      <div className="flex flex-wrap items-center gap-2 border-t border-linea pt-3">
        <span className="text-sm text-tinta-2">Traducir a</span>
        <select className="campo !w-auto !py-1 text-sm" value={idioma} onChange={(e) => setIdioma(e.target.value)}>
          {Object.entries(datos.idiomas).map(([v, t]) => <option key={v} value={v}>{t}</option>)}
        </select>
        <button className="boton boton-acento !py-1.5 text-sm" disabled={!!ocupado} onClick={() => traducir(idioma)}>
          {ocupado === "traducir" + idioma ? <Loader2 size={14} className="animate-spin" /> : <Sparkles size={14} />} {hechas.includes(idioma) ? "Traducir otra vez" : "Traducir"}
        </button>
      </div>
      {hechas.length > 0 && (
        <ul className="flex flex-wrap gap-2">
          {hechas.map((x) => (
            <li key={x}>
              <a className="boton boton-linea !px-2.5 !py-1 text-xs" href={url.srtVideo(id, x)}><Download size={12} /> {datos.idiomas[x] || x}</a>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

function VerGancho({ id, g, p, set }: { id: string; g: Gancho } & Pick<PanelProps, "p" | "set">) {
  const [ocupado, setOcupado] = useState("");
  const [aviso, setAviso] = useState("");
  const r = p("render");
  const voz = String(p("voz").voz ?? "es-ES-AlvaroNeural-Male");
  const regrabable = !voz.startsWith("propia:") && voz !== "ninguna" && !!g.plano;
  const color = g.nota == null ? "text-tinta-2" : g.nota >= 8 ? "text-ok" : g.nota >= 5 ? "text-aviso" : "text-error";

  async function usar(texto: string) {
    if (!g.plano) return;
    setOcupado(texto); setAviso("");
    try {
      const x = await api.grabarParte(id, { desde: g.plano.desde, hasta: g.plano.hasta, texto });
      if (!x.cabe) { setAviso(`No cabe en el primer plano: quita unas ${x.sobran} palabras (o editalo en el Editor).`); return; }
      const datos = await api.editor(id);
      const parche: Parche = { desde: x.desde, hasta: x.hasta, archivo: x.archivo, texto: x.texto };
      set("render", "voz_parches", ponerParche((r.voz_parches as Parche[]) || [], parche));
      set("render", "subs_texto", { ...((r.subs_texto as Record<string, string>) || {}), ...frasesConTexto(datos.lineas || [], x.desde, x.hasta, x.texto) });
      setAviso("ok");
    } catch (e) { setAviso(String((e as Error).message)); } finally { setOcupado(""); }
  }

  return (
    <div className="space-y-3">
      <div className="flex items-baseline gap-2">
        <span className={`font-display text-4xl font-bold ${color}`}>{g.nota ?? "?"}</span>
        <span className="text-sm text-tinta-3">/ 10 de retencion esperada</span>
      </div>
      {g.bien.length > 0 && <Lista titulo="Funciona" items={g.bien} clase="text-ok" />}
      {g.mal.length > 0 && <Lista titulo="Falla" items={g.mal} clase="text-error" />}
      {g.alternativas.length > 0 && (
        <div>
          <p className="etiqueta mb-1">Otros ganchos (caben unas {g.palabras} palabras)</p>
          <ul className="space-y-1.5">
            {g.alternativas.map((a) => (
              <li key={a} className="rounded-lg border border-linea p-2 text-sm">
                <p>{a}</p>
                <div className="mt-1.5 flex gap-1.5">
                  <BotonCopiar texto={a} />
                  {regrabable && (
                    <button className="boton boton-linea !px-2.5 !py-1 text-xs" disabled={!!ocupado} onClick={() => usar(a)}
                      title="Regraba el primer plano con este texto (en el Editor lo ves marcado y lo puedes deshacer)">
                      {ocupado === a ? <Loader2 size={12} className="animate-spin" /> : <Mic size={12} />} Regrabar el inicio con este
                    </button>
                  )}
                </div>
              </li>
            ))}
          </ul>
        </div>
      )}
      {aviso === "ok" ? (
        <p className="rounded-lg bg-ok-suave p-2 text-sm text-ok">Listo: el primer plano dice el gancho nuevo. Pulsa <b>Volver a montar</b> para verlo en el video (en el Editor sale marcado como «regrabado»).</p>
      ) : aviso ? <p className="rounded-lg bg-error-suave p-2 text-sm text-error">{aviso}</p> : null}
      {!regrabable && g.plano && <p className="text-xs text-tinta-3">Con una narracion propia no se puede regrabar: copia el gancho y grabalo tu.</p>}
    </div>
  );
}

function Lista({ titulo, items, clase }: { titulo: string; items: string[]; clase: string }) {
  return (
    <div>
      <p className={`etiqueta mb-1 ${clase}`}>{titulo}</p>
      <ul className="list-disc space-y-0.5 pl-5 text-sm text-tinta-2">{items.map((x) => <li key={x}>{x}</li>)}</ul>
    </div>
  );
}

function Copiable({ texto }: { texto: string }) {
  return (
    <li className="flex items-center justify-between gap-2 rounded-lg border border-linea px-2 py-1.5 text-sm">
      <span>{texto}</span>
      <BotonCopiar texto={texto} />
    </li>
  );
}

function BotonCopiar({ texto }: { texto: string }) {
  const [hecho, setHecho] = useState(false);
  return (
    <button className="boton boton-fantasma shrink-0 !px-2 !py-1 text-xs" title="Copiar"
      onClick={() => { navigator.clipboard?.writeText(texto).then(() => { setHecho(true); setTimeout(() => setHecho(false), 1500); }); }}>
      {hecho ? <Check size={12} /> : <Copy size={12} />} {hecho ? "Copiado" : "Copiar"}
    </button>
  );
}
