"use client";

import { useEffect, useRef, useState } from "react";
import { Download, Upload, Clapperboard } from "lucide-react";
import type { PanelProps } from "../Proyecto";
import { AvisoError, Campo, Deslizador, Segmentado, Tarjeta } from "../ui";
import { listarMusica, mmss, url } from "@/lib/api";

const FUENTES = [
  "STHeitiMedium.ttc", "STHeitiLight.ttc", "MicrosoftYaHeiBold.ttc", "MicrosoftYaHeiNormal.ttc",
  "Charm-Bold.ttf", "Charm-Regular.ttf", "UTM Kabel KT.ttf",
];

export default function PanelVideo({ id, vista, p, set, ejecutar, ocupado }: PanelProps) {
  const et = vista.etapas.render;
  const r = p("render");
  const [canciones, setCanciones] = useState<string[]>([]);
  const subida = useRef<HTMLInputElement>(null);
  useEffect(() => { listarMusica().then(setCanciones); }, []);

  const s = (k: string) => (v: unknown) => set("render", k, v);
  const vertical = r.aspecto === "9:16";

  async function subirMusica(f: File | undefined) {
    if (!f) return;
    const fd = new FormData();
    fd.append("file", f);
    const res = await fetch("/api/motor/musics", { method: "POST", body: fd });
    const j = await res.json().catch(() => null);
    setCanciones(await listarMusica());
    if (j?.data?.file) set("render", "musica", j.data.file);
  }

  return (
    <div className="grid gap-5 lg:grid-cols-[1fr_1.1fr]">
      <div className="space-y-5">
        <AvisoError texto={et.error} />
        <Tarjeta>
          {et.salida ? (
            <>
              <div className={`mx-auto overflow-hidden rounded-xl bg-black ${vertical ? "max-w-[320px]" : ""}`}>
                <video key={et.terminado} controls className="w-full" src={url.archivo(id, et.salida.mp4, et.terminado)} />
              </div>
              <div className="mt-4 flex flex-wrap items-center justify-between gap-3">
                <p className="text-sm text-tinta-2">
                  {mmss(et.salida.duracion)} · {et.salida.ancho}×{et.salida.alto} · {et.salida.tam_mb} MB ·{" "}
                  {et.salida.clips_reutilizados} clips reutilizados
                </p>
                <a href={url.descargar(id)} className="boton boton-acento"><Download size={15} /> Descargar MP4</a>
              </div>
              {et.estado === "obsoleta" && (
                <p className="mt-3 rounded-xl bg-aviso-suave p-3 text-sm text-aviso">
                  Hay cambios desde este montaje. Solo se rehace lo que cambio.
                </p>
              )}
            </>
          ) : (
            <div className="grid place-items-center py-16 text-center text-tinta-3">
              <Clapperboard size={34} />
              <p className="mt-3">Aun no hay video. Ajusta el acabado y pulsa <b>Montar video</b>.</p>
            </div>
          )}
          <button className="boton boton-linea mt-4" disabled={ocupado} onClick={() => ejecutar("render")}>
            {et.salida ? "Volver a montar" : "Montar video"}
          </button>
        </Tarjeta>
      </div>

      <div className="space-y-5">
        <Tarjeta titulo="Imagen">
          <div className="space-y-4">
            <Campo etiqueta="Formato">
              <Segmentado valor={(r.aspecto as string) || "9:16"} onChange={s("aspecto")}
                opciones={[{ v: "9:16", t: "Vertical 9:16" }, { v: "16:9", t: "Horizontal 16:9" }, { v: "1:1", t: "Cuadrado" }]} />
            </Campo>
            <Campo etiqueta="Si el recurso no encaja">
              <Segmentado valor={(r.encaje as string) || "desenfoque"} onChange={s("encaje")}
                opciones={[{ v: "desenfoque", t: "Fondo desenfocado" }, { v: "recortar", t: "Recortar" }, { v: "negro", t: "Bandas negras" }]} />
            </Campo>
            <Campo etiqueta="Zoom lento en imagenes">
              <Deslizador valor={Number(r.zoom ?? 0.08)} min={0} max={0.25} paso={0.01} onChange={s("zoom")}
                formato={(x) => (x ? `${Math.round(x * 100)}%` : "sin")} />
            </Campo>
          </div>
        </Tarjeta>

        <Tarjeta titulo="Subtitulos" extra={
          <label className="flex items-center gap-2 text-sm">
            <input type="checkbox" checked={r.subtitulos !== false} onChange={(e) => set("render", "subtitulos", e.target.checked)} /> Activados
          </label>
        }>
          {r.subtitulos !== false && (
            <div className="grid grid-cols-2 gap-3">
              <Campo etiqueta="Posicion">
                <select className="campo" value={(r.sub_posicion as string) || "bottom"} onChange={(e) => set("render", "sub_posicion", e.target.value)}>
                  <option value="bottom">Abajo</option><option value="center">Centro</option>
                  <option value="top">Arriba</option><option value="custom">Personalizada</option>
                </select>
              </Campo>
              {r.sub_posicion === "custom" ? (
                <Campo etiqueta="Altura (% desde arriba)">
                  <Deslizador valor={Number(r.sub_posicion_pct ?? 70)} min={5} max={95} paso={1} onChange={s("sub_posicion_pct")} formato={(x) => `${x}%`} />
                </Campo>
              ) : (
                <Campo etiqueta="Tamano">
                  <Deslizador valor={Number(r.tam_fuente ?? 60)} min={30} max={120} paso={2} onChange={s("tam_fuente")} />
                </Campo>
              )}
              <Campo etiqueta="Fuente" className="col-span-2">
                <select className="campo" value={(r.fuente as string) || FUENTES[0]} onChange={(e) => set("render", "fuente", e.target.value)}>
                  {FUENTES.map((f) => <option key={f} value={f}>{f.replace(/\.(ttf|ttc)$/, "")}</option>)}
                </select>
              </Campo>
              <Campo etiqueta="Color texto">
                <input type="color" className="h-10 w-full cursor-pointer rounded-lg border border-linea bg-tarjeta"
                  value={(r.color_texto as string) || "#FFFFFF"} onChange={(e) => set("render", "color_texto", e.target.value)} />
              </Campo>
              <Campo etiqueta="Fondo">
                <label className="flex h-10 items-center gap-2 text-sm">
                  <input type="checkbox" checked={r.sub_fondo !== false} onChange={(e) => set("render", "sub_fondo", e.target.checked)} /> Caja oscura
                </label>
              </Campo>
              {r.sub_fondo === false && (
                <>
                  <Campo etiqueta="Color contorno">
                    <input type="color" className="h-10 w-full cursor-pointer rounded-lg border border-linea bg-tarjeta"
                      value={(r.color_contorno as string) || "#000000"} onChange={(e) => set("render", "color_contorno", e.target.value)} />
                  </Campo>
                  <Campo etiqueta="Grosor contorno">
                    <Deslizador valor={Number(r.grosor_contorno ?? 1.5)} min={0} max={6} paso={0.5} onChange={s("grosor_contorno")} />
                  </Campo>
                </>
              )}
            </div>
          )}
        </Tarjeta>

        <Tarjeta titulo="Sonido">
          <div className="space-y-4">
            <Campo etiqueta="Musica de fondo">
              <div className="flex gap-2">
                <select className="campo" value={(r.musica as string) ?? "random"} onChange={(e) => set("render", "musica", e.target.value)}>
                  <option value="random">Aleatoria</option>
                  <option value="">Sin musica</option>
                  {canciones.map((c) => <option key={c} value={c}>{c}</option>)}
                </select>
                <button className="boton boton-linea shrink-0 !px-3" title="Subir MP3" onClick={() => subida.current?.click()}>
                  <Upload size={15} />
                </button>
                <input ref={subida} type="file" accept="audio/mpeg,.mp3" hidden onChange={(e) => subirMusica(e.target.files?.[0])} />
              </div>
            </Campo>
            <Campo etiqueta="Volumen musica">
              <Deslizador valor={Number(r.musica_volumen ?? 0.2)} min={0} max={1} paso={0.05} onChange={s("musica_volumen")}
                formato={(x) => `${Math.round(x * 100)}%`} />
            </Campo>
            <Campo etiqueta="Volumen voz">
              <Deslizador valor={Number(r.volumen_voz ?? 1)} min={0.3} max={2} paso={0.05} onChange={s("volumen_voz")}
                formato={(x) => `${Math.round(x * 100)}%`} />
            </Campo>
          </div>
        </Tarjeta>

        <Tarjeta titulo="Motor">
          <div className="grid grid-cols-2 gap-3">
            <Campo etiqueta="Acabado">
              <select className="campo" value={(r.acabado as string) || "rapido"} onChange={(e) => set("render", "acabado", e.target.value)}>
                <option value="rapido">Rapido (ffmpeg)</option>
                <option value="clasico">Clasico MPT (lento)</option>
              </select>
            </Campo>
            <Campo etiqueta="Codec">
              <select className="campo" value={(r.codec as string) || ""} onChange={(e) => set("render", "codec", e.target.value)}>
                <option value="">Por defecto</option>
                <option value="libx264">libx264 (CPU)</option>
                <option value="h264_nvenc">NVIDIA</option>
                <option value="h264_amf">AMD</option>
                <option value="h264_qsv">Intel</option>
              </select>
            </Campo>
          </div>
        </Tarjeta>
      </div>
    </div>
  );
}
