"use client";

// Video 3D: un apartado propio y sencillo para los videos con mundo 3D (escenario que se arma, camara de cine y lo
// dicho en gris). Por dentro es la Fabrica con el estilo "mundo3d": mismo guion, voz y montaje, sin sus mil opciones.
import { useCallback, useEffect, useMemo, useState } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { Box, Copy, Download, Eraser, Loader2, Pencil, Play, Sparkles, SquarePen, Trash2, X } from "lucide-react";
import { Accion, AvisoError, Campo, Segmentado } from "@/components/ui";
import { fabrica, mmss, type CatalogoFabrica, type FormatoFabrica, type ResumenFabrica } from "@/lib/api";
import { AZURE_VOICES } from "@/lib/voces";
import EscucharVoz from "@/components/EscucharVoz";

const ESTILO = "diorama3d";
const ESTILOS_3D = ["diorama3d", "mundo3d"];   // mundo3d: los primeros videos (iconos en 3D)
const TRABAJANDO = ["en cola", "guion", "voz", "render", "montaje"];
const DURACIONES = [30, 45, 60, 90].map((n) => ({ v: String(n), t: `${n} s` }));
const IDIOMAS = [
  { v: "es-MX", t: "Español (México)", nombre: "espanol" }, { v: "es-ES", t: "Español (España)", nombre: "espanol" },
  { v: "es-US", t: "Español (EE. UU.)", nombre: "espanol" }, { v: "en-US", t: "Inglés", nombre: "ingles" },
  { v: "pt-BR", t: "Portugués", nombre: "portugues" },
];

export default function Pagina3D() {
  const router = useRouter();
  const [cat, setCat] = useState<CatalogoFabrica | null>(null);
  const [lista, setLista] = useState<ResumenFabrica[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [enviando, setEnviando] = useState(false);
  const [viendo, setViendo] = useState<ResumenFabrica | null>(null);
  const [ocupado, setOcupado] = useState<string | null>(null);

  const [tema, setTema] = useState("");
  const [nicho, setNicho] = useState("curiosidades");
  const [serie, setSerie] = useState("");
  const [duracion, setDuracion] = useState("45");
  const [formato, setFormato] = useState<FormatoFabrica>("9:16");
  const [idioma, setIdioma] = useState("es-MX");
  const [fuente, setFuente] = useState<"gemini" | "microsoft">("gemini");
  const [vozGemini, setVozGemini] = useState("gemini:Kore");
  const [vozMs, setVozMs] = useState("es-MX-JorgeNeural-Male");
  const [musica, setMusica] = useState(true);

  const cargar = useCallback(() => fabrica.listar()
    .then((r) => setLista(r.videos.filter((s) => ESTILOS_3D.includes(s.opciones.estilo))))
    .catch((e) => setError(String(e.message || e))), []);
  useEffect(() => {
    fabrica.catalogo().then((c) => {
      setCat(c);
      if (!c.voces_gemini?.length) setFuente("microsoft");
    }).catch((e) => setError(String(e.message || e)));
    cargar();
  }, [cargar]);
  const trabajando = !!lista?.some((s) => TRABAJANDO.includes(s.estado));
  useEffect(() => {
    if (!trabajando) return;
    const k = setInterval(cargar, 3000);
    return () => clearInterval(k);
  }, [trabajando, cargar]);

  async function accion(s: ResumenFabrica, fn: () => Promise<unknown>) {
    setOcupado(s.id);
    setError(null);
    try {
      await fn();
      await cargar();
    } catch (e) { setError(String((e as Error).message || e)); }
    setOcupado(null);
  }
  const borrar = (s: ResumenFabrica) =>
    confirm(`¿Borrar «${s.titulo}» y todo lo generado?`) && accion(s, () => fabrica.borrar(s.id));
  const renombrar = (s: ResumenFabrica) => {
    const t = prompt("Nuevo titulo", s.titulo);
    if (t && t.trim() && t !== s.titulo) accion(s, () => fabrica.renombrar(s.id, t.trim()));
  };
  const duplicar = (s: ResumenFabrica) => accion(s, async () => router.push(`/fabrica/${(await fabrica.duplicar(s.id)).id}`));
  const liberar = (s: ResumenFabrica) =>
    confirm(`¿Liberar espacio de «${s.titulo}»? Se borran solo las escenas ya dibujadas (cache). ` +
      "El video, el guion y la voz se quedan; si rehaces o lo editas, se vuelven a dibujar.") &&
    accion(s, () => fabrica.liberar(s.id));

  const hayGemini = !!cat?.voces_gemini?.length;
  const vocesMs = useMemo(() => AZURE_VOICES.filter((v) => v.lang === idioma), [idioma]);
  const voz = fuente === "gemini" && hayGemini ? vozGemini : vozMs;

  async function crear() {
    if (!tema.trim()) return;
    setEnviando(true);
    setError(null);
    try {
      const { parecido } = await fabrica.parecido(tema.trim(), nicho).catch(() => ({ parecido: null }));
      if (parecido && !confirm(`Ya hiciste un video muy parecido: «${parecido.titulo}». ¿Hacerlo igualmente?`)) {
        setEnviando(false);
        return;
      }
      const s = await fabrica.crear({
        tema: tema.trim(), nicho, serie, estilo: ESTILO, formatos: [formato], voz, velocidad: 1, duracion: Number(duracion),
        musica: musica ? "random" : "", musica_volumen: 0.16, subtitulos: true, efectos: true, foco: true, nuevos: true,
        idioma: IDIOMAS.find((x) => x.v === idioma)?.nombre || "espanol",
      });
      router.push(`/fabrica/${s.id}`);
    } catch (e) {
      setError(String((e as Error).message || e));
      setEnviando(false);
    }
  }

  return (
    <main className="mx-auto max-w-5xl px-4 pb-24 pt-12">
      <div className="mb-8">
        <h1 className="flex items-center gap-2.5 font-display text-3xl font-semibold"><Box className="text-acento" /> Video 3D</h1>
        <p className="mt-2 max-w-2xl text-tinta-2">
          Cada momento del video es un pequeno mundo 3D, tipo juguete de plastilina, dibujado para lo que dice la voz.
          Escribe el tema y listo. Las imagenes se hacen gratis en Google Flow, asi que funciona en este PC.
        </p>
      </div>

      <AvisoError texto={error} />

      <section className="rounded-2xl border border-linea bg-tarjeta p-5 shadow-sm">
        <Campo etiqueta="Tema" ayuda="Una pregunta o una idea concreta funciona mejor: «Por que el pan se pone duro», «Como llega un pedido a tu casa».">
          <textarea className="campo min-h-20 w-full" value={tema} onChange={(e) => setTema(e.target.value)}
            placeholder="¿De que va el video?" />
        </Campo>

        <div className="mt-5 grid gap-5 sm:grid-cols-2">
          <Campo etiqueta="Nicho">
            <select className="campo w-full" value={nicho} onChange={(e) => setNicho(e.target.value)}>
              {(cat?.nichos || []).map((n) => <option key={n.id} value={n.id}>{n.nombre}</option>)}
            </select>
          </Campo>
          <Campo etiqueta="Serie (opcional)">
            <select className="campo w-full" value={serie} onChange={(e) => setSerie(e.target.value)}>
              <option value="">Ninguna</option>
              {(cat?.series || []).map((n) => <option key={n.id} value={n.id}>{n.nombre}</option>)}
            </select>
          </Campo>
          <Campo etiqueta="Duracion">
            <Segmentado valor={duracion} opciones={DURACIONES} onChange={setDuracion} />
          </Campo>
          <Campo etiqueta="Formato">
            <Segmentado valor={formato} onChange={(v) => setFormato(v as FormatoFabrica)}
              opciones={[{ v: "9:16", t: "Vertical (TikTok, Reels, Shorts)" }, { v: "16:9", t: "Horizontal (YouTube)" }]} />
          </Campo>
        </div>

        <div className="mt-5 grid gap-5 border-t border-linea pt-5 sm:grid-cols-2">
          <Campo etiqueta="Voz">
            <Segmentado valor={fuente} onChange={setFuente} opciones={[
              ...(hayGemini ? [{ v: "gemini" as const, t: "Gemini (mas natural)" }] : []),
              { v: "microsoft" as const, t: "Microsoft" },
            ]} />
            {!hayGemini && <p className="mt-1.5 text-xs text-tinta-3">Pon tu clave de Gemini en Configuracion para una voz mas natural.</p>}
          </Campo>
          <Campo etiqueta="Idioma">
            <select className="campo w-full" value={idioma} onChange={(e) => {
              setIdioma(e.target.value);
              const primera = AZURE_VOICES.find((v) => v.lang === e.target.value);
              if (primera) setVozMs(primera.value);
            }}>
              {IDIOMAS.map((l) => <option key={l.v} value={l.v}>{l.t}</option>)}
            </select>
          </Campo>
          <Campo etiqueta={fuente === "gemini" && hayGemini ? "Voz de Gemini (habla el idioma del guion)" : "Voz de Microsoft"}>
            {fuente === "gemini" && hayGemini ? (
              <div className="flex items-start gap-2">
                <select className="campo flex-1" value={vozGemini} onChange={(e) => setVozGemini(e.target.value)}>
                  {(cat?.voces_gemini || []).map((v) => <option key={v.value} value={v.value}>{v.label}</option>)}
                </select>
                <EscucharVoz voz={vozGemini} idioma={IDIOMAS.find((x) => x.v === idioma)?.nombre || "espanol"} />
              </div>
            ) : (
              <select className="campo w-full" value={vozMs} onChange={(e) => setVozMs(e.target.value)}>
                {vocesMs.map((v) => <option key={v.value} value={v.value}>{v.label}</option>)}
              </select>
            )}
          </Campo>
          <Campo etiqueta="Musica de fondo">
            <label className="flex items-center gap-2 text-sm">
              <input type="checkbox" checked={musica} onChange={(e) => setMusica(e.target.checked)} /> Con musica (una al azar)
            </label>
          </Campo>
        </div>

        <div className="mt-6 flex justify-end">
          <button className="boton boton-acento" onClick={crear} disabled={enviando || !tema.trim() || !!cat?.falta}>
            {enviando ? <Loader2 size={16} className="animate-spin" /> : <Sparkles size={16} />} Hacer el video 3D
          </button>
        </div>
        {cat?.falta && <p className="mt-2 text-right text-xs text-error">{cat.falta}</p>}
      </section>

      <h2 className="mb-4 mt-10 font-display text-xl font-semibold">Mis videos 3D</h2>
      {!lista ? <Loader2 className="animate-spin text-tinta-3" /> : !lista.length ? (
        <p className="text-sm text-tinta-3">Todavia no hay videos 3D. Escribe un tema arriba.</p>
      ) : (
        <ul className="grid grid-cols-2 gap-4 sm:grid-cols-3 lg:grid-cols-4">
          {lista.map((s) => {
            const v = (s.videos || [])[0];
            const enCurso = TRABAJANDO.includes(s.estado);
            return (
              <li key={s.id} className="group overflow-hidden rounded-2xl border border-linea bg-tarjeta">
                <button onClick={() => (v ? setViendo(s) : router.push(`/fabrica/${s.id}`))}
                  className={`relative block w-full overflow-hidden bg-hundido ${v?.formato === "16:9" ? "aspect-video" : "aspect-[9/16]"}`}>
                  {v ? (
                    <>
                      <video src={`${fabrica.urlVideo(s.id, v.formato, false, Math.round(v.creado))}#t=1`}
                        className="absolute inset-0 h-full w-full bg-black object-cover" muted preload="metadata" />
                      <span className="absolute inset-0 grid place-items-center bg-black/0 transition group-hover:bg-black/30">
                        <Play size={30} className="text-white opacity-0 drop-shadow transition group-hover:opacity-100" />
                      </span>
                      <span className="absolute bottom-2 right-2 rounded-md bg-black/70 px-1.5 py-0.5 text-xs text-white">{mmss(v.duracion)}</span>
                    </>
                  ) : (
                    <span className="grid h-full place-items-center p-3 text-center text-xs text-tinta-3">
                      {enCurso ? <span className="flex flex-col items-center gap-2"><Loader2 className="animate-spin" />{s.mensaje} ({s.progreso}%)</span>
                        : s.estado === "error" ? <span className="text-error">{s.error}</span> : "Abrir"}
                    </span>
                  )}
                </button>
                <Link href={`/fabrica/${s.id}`} className="block p-3">
                  <h3 className="line-clamp-2 text-sm font-semibold" title={s.titulo}>{s.titulo}</h3>
                  <p className="mt-1 text-xs text-tinta-3">{new Date(s.actualizado * 1000).toLocaleDateString()}</p>
                </Link>
                <div className="flex flex-wrap items-center gap-0.5 border-t border-linea px-1.5 py-1.5">
                  {ocupado === s.id ? (
                    <span className="flex items-center gap-2 px-2 py-1.5 text-xs text-tinta-3">
                      <Loader2 size={14} className="animate-spin" /> Un momento…
                    </span>
                  ) : (
                    <>
                      <Accion icono={<Play size={14} />} texto="Ver" soloIcono disabled={!v} onClick={() => setViendo(s)} />
                      <Accion icono={<Download size={14} />} texto="Descargar" soloIcono disabled={!v}
                        href={v ? fabrica.urlVideo(s.id, v.formato, true) : undefined} />
                      <Accion icono={<SquarePen size={14} />} texto="Editar" soloIcono derecha href={`/fabrica/${s.id}`} />
                      <Accion icono={<Copy size={14} />} texto="Duplicar" soloIcono disabled={enCurso} onClick={() => duplicar(s)} />
                      <Accion icono={<Pencil size={14} />} texto="Renombrar" soloIcono onClick={() => renombrar(s)} />
                      <Accion icono={<Eraser size={14} />} texto="Liberar espacio (cache de escenas)" soloIcono disabled={enCurso} onClick={() => liberar(s)} />
                      <Accion icono={<Trash2 size={14} />} texto="Borrar" soloIcono peligro disabled={enCurso} onClick={() => borrar(s)} />
                    </>
                  )}
                </div>
              </li>
            );
          })}
        </ul>
      )}

      {viendo && (() => {
        const v = (viendo.videos || [])[0];
        return (
          <div className="fixed inset-0 z-50 grid place-items-center bg-black/80 p-4" onClick={() => setViendo(null)}>
            <div className="relative max-h-full" onClick={(e) => e.stopPropagation()}>
              <video src={fabrica.urlVideo(viendo.id, v.formato, false, Math.round(v.creado))} controls autoPlay
                className="max-h-[85vh] rounded-xl bg-black" />
              <div className="mt-3 flex justify-center gap-2">
                <a href={fabrica.urlVideo(viendo.id, v.formato, true)} className="boton boton-acento !py-1.5 text-xs"><Download size={14} /> Descargar</a>
                <button className="boton boton-linea !py-1.5 text-xs text-white" onClick={() => setViendo(null)}><X size={14} /> Cerrar</button>
              </div>
            </div>
          </div>
        );
      })()}
    </main>
  );
}
