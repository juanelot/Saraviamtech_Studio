"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import { Mic, Square, Upload } from "lucide-react";
import type { PanelProps } from "../Proyecto";
import { AvisoError, Campo, Deslizador, Segmentado, Tarjeta } from "../ui";
import { AZURE_VOICES } from "@/lib/voces";
import { clonadas, mmss, url, vozPropia, type VocesClonadas } from "@/lib/api";

export default function PanelVoz({ id, vista, p, set, ejecutar, ocupado, recargar }: PanelProps) {
  const et = vista.etapas.voz;
  const v = p("voz");
  const voz = (v.voz as string) || "es-ES-AlvaroNeural-Male";
  const [idioma, setIdioma] = useState(() => voz.split("-").slice(0, 2).join("-"));
  const idiomas = useMemo(() => Array.from(new Set(AZURE_VOICES.map((x) => x.lang))).sort(), []);
  const voces = AZURE_VOICES.filter((x) => x.lang === idioma);
  const [tipo, setTipo] = useState<"microsoft" | "clonada" | "propia">(
    voz.startsWith("clon:") ? "clonada" : voz.startsWith("propia:") ? "propia" : "microsoft");

  if (voz === "ninguna") {
    const tramos = (v.tramos as number[]) || [];
    return (
      <div className="grid gap-5 lg:grid-cols-[1fr_1.3fr]">
        <Tarjeta titulo="Sin voz">
          <p className="text-sm text-tinta-2">
            Este video no lleva narracion: suena el audio de los propios clips (ASMR, efectos o dialogos generados en Flow),
            con {tramos.length} escenas de duracion fija ({mmss(tramos.reduce((a, b) => a + b, 0))} en total).
          </p>
          <div className="mt-4 flex flex-wrap gap-2">
            <button className="boton boton-acento" disabled={ocupado} onClick={() => ejecutar("voz")}>
              {et.salida ? "Rehacer la pista" : "Preparar la pista"}
            </button>
            <button className="boton boton-linea" disabled={ocupado}
              title="Escribe antes el guion en el paso Guion"
              onClick={() => set("voz", "voz", "es-MX-JorgeNeural-Male")}>
              <Mic size={15} /> Prefiero narrarlo
            </button>
          </div>
          <p className="mt-2 text-xs text-tinta-3">Para narrarlo, escribe el guion en el paso Guion y luego elige aqui una voz.</p>
        </Tarjeta>
        <AvisoError texto={et.error} />
      </div>
    );
  }

  return (
    <div className="grid gap-5 lg:grid-cols-[1fr_1.3fr]">
      <Tarjeta titulo="Voz">
        <div className="space-y-4">
          <Segmentado
            valor={tipo}
            opciones={[{ v: "microsoft", t: "Microsoft" }, { v: "clonada", t: "Voz clonada" }, { v: "propia", t: "Mi audio" }]}
            onChange={(t) => {
              setTipo(t);
              if (t === "microsoft" && !voz.startsWith("es-") && voz.includes(":")) set("voz", "voz", "es-ES-AlvaroNeural-Male");
            }}
          />
          {tipo === "microsoft" ? (
            <>
              <div className="grid grid-cols-2 gap-3">
                <Campo etiqueta="Idioma">
                  <select className="campo" value={idioma} onChange={(e) => setIdioma(e.target.value)}>
                    {idiomas.map((l) => <option key={l} value={l}>{l}</option>)}
                  </select>
                </Campo>
                <Campo etiqueta="Locutor">
                  <select className="campo" value={voz} onChange={(e) => set("voz", "voz", e.target.value)}>
                    {!voces.some((x) => x.value === voz) && <option value={voz}>{voz}</option>}
                    {voces.map((x) => (
                      <option key={x.value} value={x.value}>
                        {x.value.split("-")[2].replace("Neural", "")} · {x.gender === "Female" ? "mujer" : "hombre"}
                      </option>
                    ))}
                  </select>
                </Campo>
              </div>
            </>
          ) : tipo === "clonada" ? (
            <VozClonada voz={voz} elegir={(v) => set("voz", "voz", v)} />
          ) : (
            <AudioPropio id={id} voz={voz} nombre={(v.propia_nombre as string) || ""} ocupado={ocupado}
              subido={async () => { await recargar(); await ejecutar("voz"); }} />
          )}
          {tipo !== "propia" && (
            <Campo etiqueta="Velocidad">
              <Deslizador valor={Number(v.velocidad) || 1} min={0.7} max={1.5} paso={0.05}
                onChange={(x) => set("voz", "velocidad", x)} formato={(x) => `${x.toFixed(2)}×`} />
            </Campo>
          )}
          <div className="border-t border-linea pt-4">
            <p className="etiqueta mb-2">Planos</p>
            <p className="mb-3 text-xs text-tinta-3">
              La narracion se corta en planos por sus pausas; cada plano lleva un recurso.
            </p>
            <Campo etiqueta="Duracion minima de un plano">
              <Deslizador valor={Number(v.plano_min_s) || 2.5} min={1} max={8} paso={0.5}
                onChange={(x) => set("voz", "plano_min_s", x)} formato={(x) => `${x}s`} />
            </Campo>
            <Campo etiqueta="Duracion maxima de un plano" className="mt-3">
              <Deslizador valor={Number(v.plano_max_s) || 6} min={2} max={15} paso={0.5}
                onChange={(x) => set("voz", "plano_max_s", x)} formato={(x) => `${x}s`} />
            </Campo>
          </div>
          <button className="boton boton-linea" disabled={ocupado} onClick={() => ejecutar("voz")}>
            {voz.startsWith("propia:")
              ? (et.salida ? "Volver a sincronizar" : "Sincronizar audio")
              : (et.salida ? "Volver a sintetizar" : "Sintetizar voz")}
          </button>
        </div>
      </Tarjeta>

      <div className="space-y-4">
        <AvisoError texto={et.error} />
        {et.salida ? (
          <>
            <Tarjeta titulo="Escuchar" extra={<span className="text-sm text-tinta-3">{mmss(et.salida.duracion)}</span>}>
              <audio controls className="w-full" src={url.archivo(id, et.salida.audio, et.terminado)} />
              {et.salida.texto_de && (
                <p className="mt-3 text-xs text-tinta-3">
                  {et.salida.texto_de === "guion"
                    ? `Subtitulos con el texto del guion (${Math.round((et.salida.coincidencia || 0) * 100)}% de las palabras se oyen igual) y los tiempos de tu audio.`
                    : "Subtitulos con lo que entendio Whisper (no habia guion o no coincidia con el audio)."}
                </p>
              )}
            </Tarjeta>
            <Tarjeta titulo={`${et.salida.planos.length} planos`}>
              <ol className="max-h-[420px] space-y-1.5 overflow-auto pr-1">
                {et.salida.planos.map((x) => (
                  <li key={x.i} className="flex gap-3 rounded-lg px-2 py-1.5 text-sm hover:bg-hundido">
                    <span className="w-20 shrink-0 tabular-nums text-xs text-tinta-3">
                      {mmss(x.inicio)} · {(x.fin - x.inicio).toFixed(1)}s
                    </span>
                    <span>{x.texto}</span>
                  </li>
                ))}
              </ol>
            </Tarjeta>
          </>
        ) : (
          <Tarjeta><p className="text-tinta-2">Elige la voz y sintetiza para escucharla y ver los planos.</p></Tarjeta>
        )}
      </div>
    </div>
  );
}

function VozClonada({ voz, elegir }: { voz: string; elegir: (v: string) => void }) {
  const [datos, setDatos] = useState<VocesClonadas | null>(null);
  const [nombre, setNombre] = useState("");
  const [transcripcion, setTranscripcion] = useState("");
  const [audio, setAudio] = useState<{ blob: Blob; archivo: string } | null>(null);
  const [grabando, setGrabando] = useState(false);
  const [guardando, setGuardando] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const grabadora = useRef<MediaRecorder | null>(null);
  const escucha = useMemo(() => (audio ? URL.createObjectURL(audio.blob) : null), [audio]);
  const actual = voz.startsWith("clon:") ? voz.slice(5) : "";

  function cargar() {
    return clonadas.listar().then(setDatos).catch((e) => setError(String(e.message || e)));
  }
  useEffect(() => {
    cargar();
  }, []);

  async function grabar() {
    if (grabando) {
      grabadora.current?.stop();
      return;
    }
    setError(null);
    try {
      const flujo = await navigator.mediaDevices.getUserMedia({ audio: true });
      const rec = new MediaRecorder(flujo);
      const trozos: Blob[] = [];
      rec.ondataavailable = (e) => trozos.push(e.data);
      rec.onstop = () => {
        flujo.getTracks().forEach((t) => t.stop());
        setAudio({ blob: new Blob(trozos, { type: rec.mimeType }), archivo: "grabacion.webm" });
        setGrabando(false);
      };
      rec.start();
      grabadora.current = rec;
      setGrabando(true);
    } catch {
      setError("No se pudo usar el microfono (revisa el permiso del navegador).");
    }
  }

  async function guardar() {
    if (!audio) return;
    setGuardando(true);
    setError(null);
    try {
      const v = await clonadas.crear(audio.blob, nombre.trim() || "Mi voz", transcripcion, audio.archivo);
      await cargar();
      elegir(`clon:${v.id}`);
      setAudio(null);
      setNombre("");
      setTranscripcion("");
    } catch (e) {
      setError(String((e as Error).message || e));
    } finally {
      setGuardando(false);
    }
  }

  if (!datos) return <p className="text-sm text-tinta-3">Buscando el servidor de voz clonada…</p>;
  if (!datos.activo)
    return (
      <p className="rounded-xl bg-hundido p-3 text-sm text-tinta-2">
        No hay un servidor de voz clonada conectado. Arranca <b>Clonar-voz</b> en esta u otra maquina (mejor con
        GPU) y pon su direccion en <code>config.toml</code> → <code>estudio_voz_clonada_url</code>.
      </p>
    );

  return (
    <div className="space-y-4">
      <AvisoError texto={datos.error || error} />
      {datos.voces.length > 0 && (
        <Campo etiqueta="Voz" ayuda="Se genera en el servidor de clonacion: en CPU tarda de 5 a 12 veces lo que dura el audio (con GPU, casi al momento). Puedes cerrar la pagina; lo ya generado se guarda.">
          <select className="campo" value={actual} onChange={(e) => elegir(`clon:${e.target.value}`)}>
            {!actual && <option value="">Elige una voz…</option>}
            {actual && !datos.voces.some((v) => v.id === actual) && <option value={actual}>(voz borrada del servidor)</option>}
            {datos.voces.map((v) => <option key={v.id} value={v.id}>{v.nombre}</option>)}
          </select>
        </Campo>
      )}
      {actual && datos.voces.some((v) => v.id === actual) && (
        <audio controls className="w-full" src={url.muestraClonada(actual)} />
      )}
      <div className="space-y-3 rounded-xl border border-linea p-3">
        <p className="etiqueta">Anadir una voz</p>
        <p className="text-xs text-tinta-3">
          10-15 segundos de una sola persona, sin musica ni eco. Solo tu voz o una con permiso.
        </p>
        <div className="flex flex-wrap gap-2">
          <button type="button" className={`boton ${grabando ? "boton-acento" : "boton-linea"} !py-1.5 text-sm`} onClick={grabar}>
            {grabando ? <><Square size={14} /> Parar</> : <><Mic size={14} /> Grabar</>}
          </button>
          <label className="boton boton-linea cursor-pointer !py-1.5 text-sm">
            <Upload size={14} /> Subir audio
            <input type="file" accept="audio/*" className="hidden"
              onChange={(e) => { const f = e.target.files?.[0]; if (f) setAudio({ blob: f, archivo: f.name }); e.target.value = ""; }} />
          </label>
        </div>
        {audio && (
          <>
            <audio controls className="w-full" src={escucha || undefined} />
            <input className="campo" placeholder="Nombre (ej.: Mi voz)" value={nombre} onChange={(e) => setNombre(e.target.value)} />
            <textarea className="campo min-h-[60px]" placeholder="Lo que dices en la muestra (opcional, mejora el parecido)"
              value={transcripcion} onChange={(e) => setTranscripcion(e.target.value)} />
            <button type="button" className="boton boton-acento !py-1.5 text-sm" disabled={guardando} onClick={guardar}>
              {guardando ? "Guardando…" : "Guardar voz"}
            </button>
          </>
        )}
      </div>
    </div>
  );
}

function AudioPropio({ id, voz, nombre, ocupado, subido }: {
  id: string; voz: string; nombre: string; ocupado: boolean; subido: () => Promise<void>;
}) {
  const [subiendo, setSubiendo] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const tiene = voz.startsWith("propia:");

  async function subir(f: File | undefined) {
    if (!f) return;
    setSubiendo(true);
    setError(null);
    try {
      await vozPropia(id, f);
      await subido();
    } catch (e) {
      setError(String((e as Error).message || e));
    } finally {
      setSubiendo(false);
    }
  }

  return (
    <div className="space-y-3">
      <AvisoError texto={error} />
      <p className="text-xs text-tinta-3">
        Sube la narracion ya grabada (tu voz, o la que hiciste con Clonar-voz). Whisper saca el tiempo de cada palabra
        para los subtitulos y los planos. Si el guion coincide con lo que se oye, los subtitulos usan el texto del guion.
      </p>
      {tiene && (
        <>
          <p className="text-sm text-tinta-2">Audio actual: <b>{nombre || voz.slice(7)}</b></p>
          <audio controls className="w-full" src={url.archivo(id, `voz_propia/${voz.slice(7)}`)} />
        </>
      )}
      <label className={`boton boton-linea cursor-pointer !py-1.5 text-sm ${subiendo || ocupado ? "pointer-events-none opacity-60" : ""}`}>
        <Upload size={14} /> {subiendo ? "Subiendo…" : tiene ? "Cambiar audio" : "Subir audio"}
        <input type="file" accept="audio/*,.wav,.mp3,.m4a,.ogg,.opus,.flac,.webm" className="hidden"
          onChange={(e) => { subir(e.target.files?.[0]); e.target.value = ""; }} />
      </label>
      <p className="text-xs text-tinta-3">Al subirlo se sincroniza solo (unos 8 s por minuto de audio).</p>
    </div>
  );
}
