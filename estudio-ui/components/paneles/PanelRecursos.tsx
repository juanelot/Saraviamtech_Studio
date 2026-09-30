"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { Eye, Film, FolderOpen, ImageIcon, Loader2, Trash2, Upload } from "lucide-react";
import type { PanelProps } from "../Proyecto";
import { AvisoError, Campo, Tarjeta } from "../ui";
import { api, mini, url, type Recurso, type Subido } from "@/lib/api";

// En que subcarpeta cae un archivo segun su ruta dentro de la carpeta elegida
// (formato de la extension: images/ y videos/).
function subDe(f: File): "" | "images" | "videos" {
  const partes = ((f as File & { webkitRelativePath?: string }).webkitRelativePath || "").toLowerCase().split("/");
  if (partes.includes("videos")) return "videos";
  if (partes.includes("images")) return "images";
  return "";
}

export default function PanelRecursos({ id, vista, p, set, ejecutar, ocupado, recargar }: PanelProps) {
  const et = vista.etapas.recursos;
  const r = p("recursos");
  const [subidos, setSubidos] = useState<Subido[]>([]);
  const [subiendo, setSubiendo] = useState(false);
  const [arrastrando, setArrastrando] = useState(false);
  const [aviso, setAviso] = useState("");
  const entrada = useRef<HTMLInputElement>(null);
  const carpetaEntrada = useRef<HTMLInputElement>(null);
  const modoEscenas = p("asignacion").modo === "escenas";

  const cargar = useCallback(() => api.subidos(id).then((x) => setSubidos(x.archivos)), [id]);
  useEffect(() => { cargar(); }, [cargar, et.terminado]);

  const catalogo = new Map<string, Recurso>();
  for (const x of et.salida?.recursos || []) catalogo.set(`${x.origen}:${x.nombre}`, x);
  const deCarpeta = (et.salida?.recursos || []).filter((x) => x.origen === "carpeta");
  const descripciones = (r.descripciones as Record<string, string>) || {};

  async function subir(archivos: File[]) {
    archivos = archivos.filter((f) => !/(^|\/)(script\.json|\.ds_store|thumbs\.db)$/i.test(f.name));
    if (!archivos.length) return;
    setSubiendo(true);
    setAviso("");
    try {
      // Agrupado por subcarpeta (images/ videos/) para conservar el formato de la extension.
      const grupos: Record<string, File[]> = {};
      for (const f of archivos) (grupos[subDe(f)] ||= []).push(f);
      const rechazados: string[] = [];
      // Tandas de hasta 20 archivos o ~200 MB (el proxy corta a 1 GB y lo guarda en memoria).
      const TOPE = 200 * 1024 * 1024;
      let hechos = 0;
      for (const [sub, lista] of Object.entries(grupos)) {
        let tanda: File[] = [];
        let peso = 0;
        const enviar = async () => {
          if (!tanda.length) return;
          const res = await api.subir(id, tanda, sub as "" | "images" | "videos");
          rechazados.push(...res.rechazados);
          hechos += tanda.length;
          setAviso(`Subiendo… ${hechos}/${archivos.length}`);
          tanda = [];
          peso = 0;
        };
        for (const f of lista) {
          if (tanda.length && (tanda.length >= 20 || peso + f.size > TOPE)) await enviar();
          tanda.push(f);
          peso += f.size;
        }
        await enviar();
      }
      setAviso("");
      if (rechazados.length) setAviso(`No son imagen ni video: ${rechazados.join(", ")}`);
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

  const tarjeta = (clave: string, nombre: string, tipo: "imagen" | "video", cat: Recurso | undefined, borrar?: () => void, escena?: number | null) => (
    <li key={clave} className="overflow-hidden rounded-xl border border-linea bg-tarjeta">
      <div className="relative aspect-[4/3] bg-hundido">
        {cat ? (
          // eslint-disable-next-line @next/next/no-img-element
          <img src={url.miniatura(mini(cat))} alt={nombre} className="h-full w-full object-cover" loading="lazy" />
        ) : tipo === "imagen" ? (
          // eslint-disable-next-line @next/next/no-img-element
          <img src={url.archivo(id, `recursos/${nombre.split("/").map(encodeURIComponent).join("/")}`)} alt={nombre} className="h-full w-full object-cover" loading="lazy" />
        ) : (
          <div className="grid h-full place-items-center text-tinta-3"><Film size={26} /></div>
        )}
        <span className="absolute left-2 top-2 inline-flex items-center gap-1 rounded-md bg-black/65 px-1.5 py-0.5 text-[11px] text-white">
          {tipo === "video" ? <Film size={11} /> : <ImageIcon size={11} />}
          {tipo === "video" && cat ? `${cat.duracion.toFixed(1)}s` : tipo}
        </span>
        {modoEscenas && (
          <span className={`absolute bottom-2 left-2 rounded-md px-1.5 py-0.5 text-[11px] font-semibold ${
            escena != null ? "bg-acento text-sobre-acento" : "bg-error text-white"}`}>
            {escena != null ? `Escena ${escena}` : "sin numero"}
          </span>
        )}
        {borrar && (
          <button onClick={borrar} title="Quitar" className="absolute right-2 top-2 rounded-md bg-black/65 p-1 text-white hover:bg-error">
            <Trash2 size={13} />
          </button>
        )}
      </div>
      <div className="p-2.5">
        <p className="truncate text-xs font-medium" title={nombre}>{nombre}</p>
        {modoEscenas ? null : cat ? (
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
          <input ref={entrada} type="file" multiple accept="image/*,video/*,.zip" hidden
            onChange={(e) => { subir(Array.from(e.target.files || [])); e.target.value = ""; }} />
          <input ref={carpetaEntrada} type="file" multiple hidden
            {...({ webkitdirectory: "", directory: "" } as Record<string, string>)}
            onChange={(e) => { subir(Array.from(e.target.files || [])); e.target.value = ""; }} />
          {subiendo ? <Loader2 className="animate-spin text-acento" /> : <Upload className="text-tinta-3" />}
          <p className="mt-2 font-semibold">
            {modoEscenas ? "Arrastra lo que creaste (imagenes, videos o un ZIP), o haz clic" : "Arrastra imagenes y videos, o haz clic"}
          </p>
          <p className="text-sm text-tinta-3">
            {modoEscenas
              ? "Cada archivo va a su escena por el numero del nombre: 1.png, scene_2.mp4…"
              : "JPG, PNG, WEBP, MP4, MOV, WEBM o ZIP · se pueden mezclar"}
          </p>
          <button
            type="button"
            className="boton boton-linea mt-4 text-sm"
            onClick={(e) => { e.stopPropagation(); carpetaEntrada.current?.click(); }}
          >
            <FolderOpen size={15} /> {modoEscenas ? "Importar carpeta de la extension" : "Subir una carpeta"}
          </button>
          {modoEscenas && (
            <p className="mt-2 max-w-sm text-xs text-tinta-3">
              La carpeta con script.json, images/ y videos/ que crea la extension. Se respetan las dos subcarpetas.
            </p>
          )}
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
            <label className={`flex items-center gap-2 text-sm ${modoEscenas ? "hidden" : ""}`}>
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
          <Eye size={15} /> {et.estado === "ok" ? (modoEscenas ? "Contenido leido" : "Catalogo al dia") : (modoEscenas ? "Leer contenido" : "Catalogar recursos")}
        </button>
      </div>

      <ul className="grid grid-cols-2 gap-3 sm:grid-cols-3 lg:grid-cols-5">
        {(modoEscenas ? [...subidos].sort((x, y) => (x.escena ?? 1e9) - (y.escena ?? 1e9) || x.nombre.localeCompare(y.nombre)) : subidos)
          .map((s) => tarjeta(`s:${s.nombre}`, s.nombre, s.tipo, catalogo.get(`subido:${s.nombre}`), () => quitar(s.nombre), s.escena))}
        {deCarpeta.map((c) => tarjeta(`c:${c.nombre}`, c.nombre, c.tipo, c, undefined, c.escena))}
      </ul>
    </div>
  );
}
