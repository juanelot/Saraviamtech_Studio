"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { Eye, Film, ImageIcon, Loader2, Trash2, Upload } from "lucide-react";
import type { PanelProps } from "../Proyecto";
import { AvisoError, Campo, Tarjeta } from "../ui";
import { api, url, type Recurso } from "@/lib/api";

type Subido = { nombre: string; tipo: "imagen" | "video"; tam: number };

export default function PanelRecursos({ id, vista, p, set, ejecutar, ocupado, recargar }: PanelProps) {
  const et = vista.etapas.recursos;
  const r = p("recursos");
  const [subidos, setSubidos] = useState<Subido[]>([]);
  const [subiendo, setSubiendo] = useState(false);
  const [arrastrando, setArrastrando] = useState(false);
  const [aviso, setAviso] = useState("");
  const entrada = useRef<HTMLInputElement>(null);

  const cargar = useCallback(() => api.subidos(id).then((x) => setSubidos(x.archivos)), [id]);
  useEffect(() => { cargar(); }, [cargar, et.terminado]);

  const catalogo = new Map<string, Recurso>();
  for (const x of et.salida?.recursos || []) catalogo.set(`${x.origen}:${x.nombre}`, x);
  const deCarpeta = (et.salida?.recursos || []).filter((x) => x.origen === "carpeta");
  const descripciones = (r.descripciones as Record<string, string>) || {};

  async function subir(archivos: File[]) {
    if (!archivos.length) return;
    setSubiendo(true);
    setAviso("");
    try {
      const res = await api.subir(id, archivos);
      if (res.rechazados.length) setAviso(`No son imagen ni video: ${res.rechazados.join(", ")}`);
      await cargar();
      await recargar();
    } catch (e) {
      setAviso(String((e as Error).message));
    } finally {
      setSubiendo(false);
    }
  }

  async function quitar(nombre: string) {
    await api.quitar(id, nombre);
    await cargar();
    await recargar();
  }

  function describir(h: string, texto: string) {
    set("recursos", "descripciones", { ...descripciones, [h]: texto });
  }

  const tarjeta = (clave: string, nombre: string, tipo: "imagen" | "video", cat: Recurso | undefined, borrar?: () => void) => (
    <li key={clave} className="overflow-hidden rounded-xl border border-linea bg-tarjeta">
      <div className="relative aspect-[4/3] bg-hundido">
        {cat ? (
          // eslint-disable-next-line @next/next/no-img-element
          <img src={url.miniatura(cat.id)} alt={nombre} className="h-full w-full object-cover" loading="lazy" />
        ) : tipo === "imagen" ? (
          // eslint-disable-next-line @next/next/no-img-element
          <img src={url.archivo(id, `recursos/${encodeURIComponent(nombre)}`)} alt={nombre} className="h-full w-full object-cover" loading="lazy" />
        ) : (
          <div className="grid h-full place-items-center text-tinta-3"><Film size={26} /></div>
        )}
        <span className="absolute left-2 top-2 inline-flex items-center gap-1 rounded-md bg-black/65 px-1.5 py-0.5 text-[11px] text-white">
          {tipo === "video" ? <Film size={11} /> : <ImageIcon size={11} />}
          {tipo === "video" && cat ? `${cat.duracion.toFixed(1)}s` : tipo}
        </span>
        {borrar && (
          <button onClick={borrar} title="Quitar" className="absolute right-2 top-2 rounded-md bg-black/65 p-1 text-white hover:bg-error">
            <Trash2 size={13} />
          </button>
        )}
      </div>
      <div className="p-2.5">
        <p className="truncate text-xs font-medium" title={nombre}>{nombre}</p>
        {cat ? (
          <textarea
            className="campo mt-1.5 min-h-[64px] !p-2 !text-xs"
            value={descripciones[cat.id] ?? cat.descripcion}
            placeholder="Sin descripcion: escribe que se ve"
            onChange={(e) => describir(cat.id, e.target.value)}
          />
        ) : (
          <p className="mt-1.5 text-xs text-tinta-3">Sin catalogar todavia</p>
        )}
      </div>
    </li>
  );

  return (
    <div className="space-y-5">
      <AvisoError texto={et.error} />
      <div className="grid gap-5 lg:grid-cols-[1.4fr_1fr]">
        <div
          onDragOver={(e) => { e.preventDefault(); setArrastrando(true); }}
          onDragLeave={() => setArrastrando(false)}
          onDrop={(e) => { e.preventDefault(); setArrastrando(false); subir(Array.from(e.dataTransfer.files)); }}
          onClick={() => entrada.current?.click()}
          className={`grid cursor-pointer place-items-center rounded-2xl border-2 border-dashed p-8 text-center transition ${
            arrastrando ? "border-acento bg-acento-suave" : "border-linea hover:border-tinta-3"}`}
        >
          <input ref={entrada} type="file" multiple accept="image/*,video/*" hidden
            onChange={(e) => subir(Array.from(e.target.files || []))} />
          {subiendo ? <Loader2 className="animate-spin text-acento" /> : <Upload className="text-tinta-3" />}
          <p className="mt-2 font-semibold">Arrastra imagenes y videos, o haz clic</p>
          <p className="text-sm text-tinta-3">JPG, PNG, WEBP, MP4, MOV, WEBM · se pueden mezclar</p>
        </div>

        <Tarjeta titulo="Otras fuentes">
          <div className="space-y-3">
            <Campo etiqueta="Carpeta del servidor" ayuda="Ruta local o montada (NAS, Drive sincronizado…). Se lee entera.">
              <input className="campo" value={(r.carpeta as string) || ""} placeholder="C:\videos\mi-canal  o  /root/mpt-data/recursos"
                onChange={(e) => set("recursos", "carpeta", e.target.value)} />
            </Campo>
            <Campo etiqueta="URLs directas" ayuda="Una por linea. Se descargan al catalogar.">
              <textarea className="campo min-h-[70px]" value={((r.urls as string[]) || []).join("\n")}
                onChange={(e) => set("recursos", "urls", e.target.value.split("\n"))} />
            </Campo>
            <label className="flex items-center gap-2 text-sm">
              <input type="checkbox" checked={r.vision !== false} onChange={(e) => set("recursos", "vision", e.target.checked)} />
              Claude mira cada recurso y lo describe
            </label>
          </div>
        </Tarjeta>
      </div>

      {aviso && <p className="rounded-xl bg-aviso-suave p-3 text-sm text-aviso">{aviso}</p>}

      <div className="flex flex-wrap items-center justify-between gap-3">
        <p className="text-sm text-tinta-2">
          {subidos.length} subidos{deCarpeta.length ? ` · ${deCarpeta.length} de la carpeta` : ""}
          {et.salida ? ` · ${et.salida.imagenes} imagenes y ${et.salida.videos} videos catalogados` : ""}
        </p>
        <button className="boton boton-linea" disabled={ocupado} onClick={() => ejecutar("recursos")}>
          <Eye size={15} /> {et.estado === "ok" ? "Catalogo al dia" : "Catalogar recursos"}
        </button>
      </div>

      <ul className="grid grid-cols-2 gap-3 sm:grid-cols-3 lg:grid-cols-5">
        {subidos.map((s) => tarjeta(`s:${s.nombre}`, s.nombre, s.tipo, catalogo.get(`subido:${s.nombre}`), () => quitar(s.nombre)))}
        {deCarpeta.map((c) => tarjeta(`c:${c.nombre}`, c.nombre, c.tipo, c))}
      </ul>
    </div>
  );
}
