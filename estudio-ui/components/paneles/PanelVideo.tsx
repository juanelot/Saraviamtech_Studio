"use client";

import { useEffect, useRef, useState } from "react";
import { Download, Upload, Clapperboard, Trash2 } from "lucide-react";
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
  // Por las medidas del video YA montado (el formato elegido puede haber cambiado despues).
  const ancho = et.salida?.ancho || 0, alto = et.salida?.alto || 0;
  const vertical = ancho && alto ? alto > ancho * 1.05 : (r.aspecto || "16:9") === "9:16";
  const cuadrado = ancho > 0 && Math.abs(ancho - alto) <= ancho * 0.05;
  const intenso = r.edicion === "intenso";
  const editorial = r.edicion === "editorial" || intenso;
  // Clips de video del montaje (una vez cada uno, en orden) para elegir como suenan bajo la voz.
  const clips: { nombre: string; recurso: string; etiqueta: string }[] = [];
  for (const x of vista.etapas.asignacion.salida?.planos || []) {
    const nombre = (x.nombre || "").split("/").pop()!.replace(/\.[^.]+$/, "");
    if (x.tipo === "video" && nombre && !clips.some((c) => c.nombre === nombre))
      clips.push({ nombre, recurso: x.recurso!, etiqueta: x.escena ? `Escena ${x.escena}` : `#${x.i + 1}` });
  }
  const sonidoClips = (r.sonido_clips as Record<string, string>) || {};
  const sonidoDefecto = (r.sonido_defecto as string) || "silencio";
  const MODOS = [{ v: "completo", t: "Completo" }, { v: "solo_fuerte", t: "Solo fuertes" }, { v: "silencio", t: "Silencio" }];

  async function subirMusica(f: File | undefined) {
    if (!f) return;
    const fd = new FormData();
    fd.append("file", f);
    const res = await fetch("/api/motor/musics", { method: "POST", body: fd });
    const j = await res.json().catch(() => null);
    setCanciones(await listarMusica());
    if (j?.data?.file) set("render", "musica", j.data.file);
  }

  async function borrarMusica(c: string) {
    if (!confirm(`¿Borrar "${c}" del servidor? No se puede deshacer.`)) return;
    const res = await fetch(`/api/motor/musics/${encodeURIComponent(c)}`, { method: "DELETE" });
    if (!res.ok) {
      alert("No se pudo borrar la cancion");
      return;
    }
    if (r.musica === c) set("render", "musica", "random");
    setCanciones(await listarMusica());
  }

  return (
    <div className="grid gap-5 lg:grid-cols-[1fr_1.1fr]">
      <div className="space-y-5">
        <AvisoError texto={et.error} />
        <Tarjeta>
          {et.salida ? (
            <>
              <div className={`mx-auto overflow-hidden rounded-xl bg-black ${vertical ? "max-w-[320px]" : cuadrado ? "max-w-[480px]" : ""}`}>
                <video key={et.terminado} controls className="w-full" src={url.archivo(id, et.salida.mp4, et.terminado)} />
              </div>
              <div className="mt-4 flex flex-wrap items-center justify-between gap-3">
                <p className="text-sm text-tinta-2">
                  {mmss(et.salida.duracion)} · {et.salida.ancho}×{et.salida.alto} · {et.salida.tam_mb} MB ·{" "}
                  {et.salida.clips_reutilizados} clips reutilizados
                  {et.salida.edicion && <span className="block text-xs text-tinta-3">{et.salida.edicion.replace("edicion editorial: ", "Editorial: ").replace("edicion intensa: ", "Intenso: ")}</span>}
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
        {Array.isArray(p("escenas").fijas) && (p("escenas").fijas as unknown[]).length > 0 && p("asignacion").modo === "escenas" && p("voz").voz !== "ninguna" && (
          <Tarjeta titulo="Clips y voz">
            <Interruptor valor={r.voz_continua !== false} onChange={s("voz_continua")}
              titulo="Voz de corrido"
              detalle={r.voz_continua !== false
                ? "La narracion suena seguida, sin pausas. Cada clip dura lo que su texto: si sobra se corta y si falta se ralentiza un poco y se queda en su ultimo fotograma. Nunca se repite."
                : "Cada clip sale entero y su trozo de voz va al principio (hay pequenas pausas entre clips)."} />
          </Tarjeta>
        )}
        {clips.length > 0 && p("voz").voz !== "ninguna" && (
          <Tarjeta titulo="Sonido de los clips">
            <div className="space-y-4">
              <Campo etiqueta="Por defecto" ayuda="Completo: el audio entero del clip. Solo fuertes: golpes, gritos y efectos, sin la musica de fondo del clip. Silencio: solo tu narracion.">
                <Segmentado valor={sonidoDefecto} onChange={s("sonido_defecto")} opciones={MODOS} />
              </Campo>
              {sonidoDefecto !== "silencio" || Object.values(sonidoClips).some((m) => m !== "silencio") ? (
                <>
                  <Campo etiqueta="Volumen del sonido de los clips">
                    <Deslizador valor={Number(r.sonido_volumen ?? 0.8)} min={0} max={2} paso={0.05} onChange={s("sonido_volumen")}
                      formato={(x) => `${Math.round(x * 100)}%`} />
                  </Campo>
                  <Interruptor valor={r.sonido_bajo_voz !== false} onChange={s("sonido_bajo_voz")}
                    titulo="Bajar bajo la voz" detalle="El sonido de los clips baja solo mientras hablas y vuelve en las pausas." />
                </>
              ) : null}
              <details>
                <summary className="cursor-pointer text-xs text-tinta-2">
                  Elegir clip por clip ({clips.length} clips, {Object.keys(sonidoClips).length} cambiados)
                </summary>
                <ul className="mt-2 max-h-[28rem] space-y-2 overflow-y-auto pr-1">
                  {clips.map((c) => (
                    <li key={c.nombre} className="rounded-xl border border-linea p-2">
                      <div className="flex items-center justify-between gap-2">
                        <span className="truncate text-xs text-tinta-2" title={c.nombre}>
                          <b>{c.nombre}</b> · {c.etiqueta}
                        </span>
                        {sonidoClips[c.nombre] && (
                          <button className="boton boton-fantasma shrink-0 !px-2 !py-1 text-xs" title="Volver al de por defecto"
                            onClick={() => { const n = { ...sonidoClips }; delete n[c.nombre]; set("render", "sonido_clips", n); }}>
                            Por defecto
                          </button>
                        )}
                      </div>
                      <video controls preload="none" className="mt-1 max-h-40 w-full rounded-lg bg-black" src={url.original(id, c.recurso)} />
                      <div className="mt-1">
                        <Segmentado valor={sonidoClips[c.nombre] || sonidoDefecto} opciones={MODOS}
                          onChange={(v) => set("render", "sonido_clips", { ...sonidoClips, [c.nombre]: v })} />
                      </div>
                    </li>
                  ))}
                </ul>
              </details>
            </div>
          </Tarjeta>
        )}
        <Tarjeta titulo="Estilo de edicion">
          <div className="space-y-4">
            <Segmentado valor={intenso ? "intenso" : editorial ? "editorial" : "clasico"} onChange={s("edicion")}
              opciones={[{ v: "clasico", t: "Clasico" }, { v: "editorial", t: "Editorial" }, { v: "intenso", t: "Intenso" }]} />
            <p className="text-xs text-tinta-3">
              {intenso
                ? "Lleno de efectos y ritmo de redes: cortes en todo el video, palabra clave gigante con temblor en las revelaciones, flash en los cambios de plano, barra de progreso y mas sonido. El montaje tarda mas (mas clips)."
                : editorial
                ? "Efectos sobrios de documental que suben la retencion. Claude marca palabras clave, datos y momentos fuertes (unos segundos, una vez)."
                : "Subtitulos por frase, sin efectos."}
            </p>
            {editorial && (
              <div className="space-y-3">
                {intenso && (
                  <>
                    <Interruptor valor={r.ed_impacto !== false} onChange={s("ed_impacto")}
                      titulo="Impacto en las revelaciones" detalle="La palabra clave aparece gigante en el centro, la imagen tiembla y se desfasa el color un instante." />
                    <Interruptor valor={r.ed_flash !== false} onChange={s("ed_flash")}
                      titulo="Flash en los cambios de plano" detalle="Destello blanco breve al cambiar de imagen (como mucho uno cada 3,5 s)." />
                    <Interruptor valor={r.ed_progreso !== false} onChange={s("ed_progreso")}
                      titulo="Barra de progreso" detalle="Linea fina arriba que avanza con el video, en el color de resalte." />
                  </>
                )}
                <Interruptor valor={r.ed_palabras !== false} onChange={s("ed_palabras")}
                  titulo="Subtitulos palabra por palabra" detalle={intenso
                    ? "En mayusculas; la palabra que suena se ilumina y crece, y la clave de cada frase va en color."
                    : "La palabra que suena se ilumina y la clave de cada frase va en color."} />
                {r.ed_palabras !== false && (
                  <div className="grid grid-cols-2 gap-3 pl-7">
                    <Campo etiqueta="Palabras en pantalla">
                      <Deslizador valor={Number(r.palabras_max ?? 4)} min={2} max={6} paso={1} onChange={s("palabras_max")} />
                    </Campo>
                    <Campo etiqueta="Color de resalte">
                      <input type="color" className="h-10 w-full cursor-pointer rounded-lg border border-linea bg-tarjeta"
                        value={(r.color_resalte as string) || "#FFD447"} onChange={(e) => set("render", "color_resalte", e.target.value)} />
                    </Campo>
                  </div>
                )}
                <Interruptor valor={r.ed_rotulos !== false} onChange={s("ed_rotulos")}
                  titulo="Rotulos de datos" detalle="Cifras, fechas y nombres en pantalla, con fundido." />
                <Interruptor valor={r.ed_sonido !== false} onChange={s("ed_sonido")}
                  titulo="Diseno de sonido" detalle="Whoosh suave en los cortes, golpe grave en las revelaciones y la musica baja sola cuando habla la voz." />
                {r.ed_sonido !== false && (
                  <Campo etiqueta="Volumen de efectos" className="pl-7">
                    <Deslizador valor={Number(r.sfx_volumen ?? 1)} min={0} max={2} paso={0.1} onChange={s("sfx_volumen")}
                      formato={(x) => `${Math.round(x * 100)}%`} />
                  </Campo>
                )}
                <Interruptor valor={r.ed_ritmo === true} onChange={s("ed_ritmo")}
                  titulo={intenso ? "Ritmo" : "Ritmo de entrada"} detalle={intenso
                    ? "Un salto de encuadre a media imagen en todo el video (apagado: solo zoom suave)."
                    : "Un salto de encuadre a media imagen en los primeros 30 s (apagado: solo zoom suave)."} />
                <Interruptor valor={r.ed_zoom === true} onChange={s("ed_zoom")}
                  titulo="Zoom en las revelaciones" detalle="Salto de acercamiento justo en los momentos clave (apagado: solo zoom suave)." />
                <Interruptor valor={r.ed_color !== false} onChange={s("ed_color")}
                  titulo="Color unificado" detalle="Mismo tono, vineta leve y grano fino: todas las imagenes parecen de la misma pelicula." />
                {r.ed_color !== false && (
                  <Campo etiqueta="Tono" className="pl-7">
                    <Segmentado valor={(r.ed_look as string) || "natural"} onChange={s("ed_look")}
                      opciones={[{ v: "natural", t: "Natural" }, { v: "calido", t: "Calido" }, { v: "cine", t: "Cine" }, { v: "frio", t: "Frio" }]} />
                  </Campo>
                )}
                <Interruptor valor={r.ed_gancho !== false} onChange={s("ed_gancho")}
                  titulo="Gancho de entrada" detalle="Una frase corta sobreimpresa los primeros 2 segundos." />
                {r.ed_gancho !== false && (
                  <Campo etiqueta="Texto del gancho" ayuda="Vacio = lo propone Claude a partir del guion." className="pl-7">
                    <input className="campo" maxLength={60} placeholder="Ej.: Nadie te conto esto"
                      value={(r.gancho_texto as string) || ""} onChange={(e) => set("render", "gancho_texto", e.target.value)} />
                  </Campo>
                )}
                <Interruptor valor={r.ed_momentos !== false} onChange={s("ed_momentos")}
                  titulo="Efectos en momentos clave" detalle={`Solo donde Claude marque un momento fuerte, como mucho uno cada ${intenso ? 9 : 20} s.`} />
                {r.ed_momentos !== false && (
                  <div className="space-y-2.5 pl-7">
                    <Interruptor valor={r.ed_cita !== false} onChange={s("ed_cita")}
                      titulo="Cita destacada" detalle="La frase mas potente, grande en el centro sobre la imagen oscurecida (1-2 por video)." />
                    <Interruptor valor={r.ed_pausa !== false} onChange={s("ed_pausa")}
                      titulo="Pausa dramatica" detalle="Tras un remate, la imagen se congela 1 s, pierde color y se acerca." />
                    <Interruptor valor={r.ed_destello !== false} onChange={s("ed_destello")}
                      titulo="Destello" detalle="Fogonazo breve en las revelaciones, junto al golpe de sonido." />
                    <Interruptor valor={r.ed_pasado !== false} onChange={s("ed_pasado")}
                      titulo="Blanco y negro para el pasado" detalle="Cuando la narracion habla de otra epoca, esas escenas van en B/N calido." />
                  </div>
                )}
                {r.acabado === "clasico" && (
                  <p className="rounded-xl bg-aviso-suave p-3 text-sm text-aviso">El estilo {intenso ? "intenso" : "editorial"} necesita el acabado Rapido (en Motor).</p>
                )}
              </div>
            )}
          </div>
        </Tarjeta>

        <Tarjeta titulo="Imagen">
          <div className="space-y-4">
            <Campo etiqueta="Formato">
              <Segmentado valor={(r.aspecto as string) || "16:9"} onChange={s("aspecto")}
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
              {canciones.length > 0 && (
                <details className="mt-2">
                  <summary className="cursor-pointer text-xs text-tinta-2">Mis canciones ({canciones.length}): escuchar o borrar</summary>
                  <ul className="mt-2 max-h-72 space-y-2 overflow-y-auto pr-1">
                    {canciones.map((c) => (
                      <li key={c} className="rounded-xl border border-linea p-2">
                        <div className="flex items-center justify-between gap-2">
                          <span className="truncate text-xs text-tinta-2" title={c}>{c}</span>
                          <button className="boton boton-fantasma shrink-0 !px-2 !py-1 text-xs text-error" title="Borrar cancion"
                            onClick={() => borrarMusica(c)}>
                            <Trash2 size={13} /> Borrar
                          </button>
                        </div>
                        <audio controls preload="none" className="mt-1 h-8 w-full" src={`/api/motor/musics/${encodeURIComponent(c)}`} />
                      </li>
                    ))}
                  </ul>
                  <p className="mt-2 text-xs text-tinta-3">Se borra del servidor para todos los proyectos. Si un video la usaba, al volver a montarlo sale sin esa musica.</p>
                </details>
              )}
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

function Interruptor({ valor, onChange, titulo, detalle }: {
  valor: boolean; onChange: (v: boolean) => void; titulo: string; detalle: string;
}) {
  return (
    <label className="flex cursor-pointer items-start gap-3">
      <input type="checkbox" className="mt-0.5" checked={valor} onChange={(e) => onChange(e.target.checked)} />
      <span className="text-sm">
        <span className="font-medium">{titulo}</span>
        <span className="block text-xs text-tinta-3">{detalle}</span>
      </span>
    </label>
  );
}
