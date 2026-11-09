"use client";

import CuentasFlow from "@/components/CuentasFlow";
import { useCallback, useEffect, useRef, useState } from "react";
import { Check, ExternalLink, Loader2, LogIn, LogOut, RefreshCw, Trash2, Upload } from "lucide-react";
import { ajustes, type EstadoClaude, type EstadoFlowAjustes, type EstadoTelegram, type EstadoYoutube, type OpcionesAjustes } from "@/lib/api";
import { AvisoError, Campo, Segmentado, Tarjeta } from "@/components/ui";

const MODELOS_CLAUDE = [{ v: "haiku", t: "Haiku" }, { v: "sonnet", t: "Sonnet" }, { v: "opus", t: "Opus" }];
const ESFUERZOS = [
  { v: "low", t: "Bajo" }, { v: "medium", t: "Medio" }, { v: "high", t: "Alto" }, { v: "xhigh", t: "Muy alto" }, { v: "max", t: "Maximo" },
];
const MODELOS_FLOW = [{ v: "lite", t: "Lite" }, { v: "2", t: "Nano Banana 2" }, { v: "pro", t: "Pro" }];

function Punto({ color, texto }: { color: "ok" | "aviso" | "error" | "gris"; texto: string }) {
  const c = { ok: "bg-ok", aviso: "bg-aviso", error: "bg-error", gris: "bg-tinta-3" }[color];
  return (
    <span className="inline-flex items-center gap-2 text-sm font-medium">
      <span className={`h-2.5 w-2.5 rounded-full ${c}`} /> {texto}
    </span>
  );
}

function Interruptor({ si, onChange, disabled }: { si: boolean; onChange: (v: boolean) => void; disabled?: boolean }) {
  return (
    <button type="button" role="switch" aria-checked={si} disabled={disabled} onClick={() => onChange(!si)}
      className={`relative h-6 w-11 shrink-0 rounded-full transition disabled:opacity-45 ${si ? "bg-marca" : "bg-hundido border border-linea"}`}>
      <span className={`absolute top-0.5 h-5 w-5 rounded-full bg-white shadow transition-all ${si ? "left-[22px]" : "left-0.5"}`} />
    </button>
  );
}

export default function Configuracion() {
  const [op, setOp] = useState<OpcionesAjustes | null>(null);
  const [claude, setClaude] = useState<EstadoClaude | null>(null);
  const [flow, setFlow] = useState<EstadoFlowAjustes | null>(null);
  const [tg, setTg] = useState<EstadoTelegram | null>(null);
  const [yt, setYt] = useState<EstadoYoutube | null>(null);
  const archivoYt = useRef<HTMLInputElement>(null);
  const [token, setToken] = useState("");
  const [claveGemini, setClaveGemini] = useState("");
  const [claveStock, setClaveStock] = useState({ pexels: "", pixabay: "" });
  const [error, setError] = useState<string | null>(null);
  const [ocupado, setOcupado] = useState<string | null>(null);
  const [guardado, setGuardado] = useState(false);
  const [carpetas, setCarpetas] = useState("");
  const temporizador = useRef<ReturnType<typeof setTimeout> | null>(null);

  useEffect(() => {
    ajustes.ver().then((d) => {
      setOp(d.opciones); setClaude(d.claude); setFlow(d.flow); setTg(d.telegram);
      setCarpetas(d.opciones.estudio_carpetas_permitidas.join("\n"));
      if (d.flow.habilitado) ajustes.flow().then(setFlow).catch(() => {});
      ajustes.youtube().then(setYt).catch(() => {});
    }).catch((e) => setError(e.message));
  }, []);

  // El bot arranca en segundo plano y los chats nuevos llegan solos: mirar cada 4 s.
  useEffect(() => {
    if (!op?.telegram_habilitado) return;
    const t = setInterval(() => ajustes.telegram().then(setTg).catch(() => {}), 4000);
    return () => clearInterval(t);
  }, [op?.telegram_habilitado]);

  // Mientras se inicia sesion en Claude (en el navegador), mirar cada 2 s si ya entro.
  useEffect(() => {
    if (!claude?.iniciando) return;
    const t = setInterval(() => ajustes.claude().then(setClaude).catch(() => {}), 2000);
    return () => clearInterval(t);
  }, [claude?.iniciando]);

  const guardar = useCallback(async (cambios: Partial<OpcionesAjustes>) => {
    setError(null);
    try {
      const d = await ajustes.guardar(cambios);
      setOp(d.opciones);
      setGuardado(true);
      if (temporizador.current) clearTimeout(temporizador.current);
      temporizador.current = setTimeout(() => setGuardado(false), 1800);
      return true;
    } catch (e) {
      setError((e as Error).message);
      return false;
    }
  }, []);

  async function accion(nombre: string, fn: () => Promise<unknown>) {
    setError(null); setOcupado(nombre);
    try { await fn(); } catch (e) { setError((e as Error).message); } finally { setOcupado(null); }
  }

  const conectarClaude = () => accion("claude", async () => {
    const r = await ajustes.claudeConectar();
    setClaude((c) => c && { ...c, iniciando: r.iniciando, url_login: r.url_login });
    if (!r.iniciando) setClaude(await ajustes.claude());
  });
  const cancelarClaude = () => accion("claude", async () => { await ajustes.claudeCancelar(); setClaude(await ajustes.claude()); });
  const desconectarClaude = () => {
    if (!confirm("Se cerrara la sesion de Claude en este equipo (tambien la de Claude Code en la terminal). Sin sesion no se pueden escribir guiones. ¿Seguir?")) return;
    accion("claude", async () => { await ajustes.claudeDesconectar(); setClaude(await ajustes.claude()); });
  };

  const activarFlow = (si: boolean) => accion("flow", async () => {
    if (await guardar({ estudio_flow_habilitado: si })) setFlow(si ? await ajustes.flow() : await ajustes.ver().then((d) => d.flow));
  });
  const conectarFlow = () => accion("flow", async () => {
    await ajustes.flowConectar();
    setOp((o) => o && { ...o, estudio_flow_habilitado: true });
    setFlow(await ajustes.flow());
  });
  const desconectarFlow = () => accion("flow", async () => { await ajustes.flowDesconectar(); setFlow(await ajustes.flow()); });
  const comprobarFlow = () => accion("flow", async () => setFlow(await ajustes.flow()));

  if (!op || !claude || !flow) {
    return (
      <main className="mx-auto max-w-4xl px-4 pt-12">
        {error ? <AvisoError texto={error} /> : <Loader2 className="animate-spin text-tinta-3" />}
      </main>
    );
  }

  const estadoClaude = !claude.instalado
    ? <Punto color="error" texto="Claude Code no esta instalado" />
    : claude.iniciando
      ? <Punto color="aviso" texto="Esperando que inicies sesion en el navegador..." />
      : claude.sesion
        ? <Punto color="ok" texto={`Conectado${claude.email ? ` como ${claude.email}` : ""}`} />
        : <Punto color="error" texto="Sin sesion" />;

  const estadoFlow = !flow.disponible
    ? <Punto color="gris" texto="No disponible en este equipo" />
    : !flow.habilitado
    ? <Punto color="gris" texto="Desactivado" />
    : flow.corriendo
      ? <Punto color="ok" texto="Generando imagenes ahora" />
      : flow.chrome === false
        ? <Punto color="aviso" texto="Chrome de Flow cerrado" />
        : flow.sesion === true
          ? <Punto color="ok" texto="Conectado (sesion de Google iniciada)" />
          : flow.sesion === false
            ? <Punto color="error" texto="Chrome abierto, pero sin sesion de Google" />
            : <Punto color="gris" texto="Sin comprobar" />;

  return (
    <main className="mx-auto max-w-4xl px-4 pb-24 pt-12">
      <div className="mb-8 flex items-end justify-between gap-4">
        <div>
          <h1 className="font-display text-3xl font-semibold">Configuracion</h1>
          <p className="mt-2 text-tinta-2">Conexiones y opciones del estudio. Se guarda al momento y no hace falta reiniciar.</p>
        </div>
        {guardado && <span className="inline-flex items-center gap-1.5 text-sm text-ok"><Check size={15} /> Guardado</span>}
      </div>

      <div className="space-y-5">
        <AvisoError texto={error} />

        <Tarjeta titulo="Claude" extra={estadoClaude}>
          <p className="text-sm text-tinta-2">
            Escribe guiones, ideas y propuestas usando tu suscripcion (Claude Code), sin clave de API.
            {claude.plan && <> Plan <b className="text-tinta">{claude.plan}</b>.</>}
            {claude.version && <> Version {claude.version}.</>}
          </p>
          {claude.motivo && !claude.sesion && <p className="mt-2 text-xs text-tinta-3">{claude.motivo}</p>}
          {claude.token_servidor ? (
            <p className="mt-4 text-sm text-tinta-3">En este servidor Claude entra con un token (CLAUDE_CODE_OAUTH_TOKEN). Se cambia en Portainer, no aqui.</p>
          ) : (
          <div className="mt-4 flex flex-wrap items-center gap-2">
            {claude.iniciando ? (
              <>
                {claude.url_login && (
                  <a href={claude.url_login} target="_blank" rel="noreferrer" className="boton boton-acento">
                    <ExternalLink size={15} /> Abrir la pagina de inicio de sesion
                  </a>
                )}
                <button className="boton boton-linea" onClick={cancelarClaude} disabled={ocupado === "claude"}>Cancelar</button>
              </>
            ) : claude.sesion ? (
              <button className="boton boton-linea hover:!text-error" onClick={desconectarClaude} disabled={ocupado === "claude"}>
                <LogOut size={15} /> Desconectar
              </button>
            ) : (
              <button className="boton boton-acento" onClick={conectarClaude} disabled={!claude.instalado || ocupado === "claude"}>
                {ocupado === "claude" ? <Loader2 size={15} className="animate-spin" /> : <LogIn size={15} />} Conectar
              </button>
            )}
          </div>
          )}
          {claude.iniciando && (
            <p className="mt-2 text-xs text-tinta-3">
              Se abre el navegador de este equipo. Si no se abre solo, usa el boton. Esta pagina se actualiza sola al terminar.
            </p>
          )}

          <div className="mt-6 grid gap-5 border-t border-linea pt-5 sm:grid-cols-2">
            <Campo etiqueta="Modelo" ayuda="Sonnet va bien para casi todo. Opus gasta bastante mas del plan.">
              <Segmentado valor={op.claude_cli_model} opciones={MODELOS_CLAUDE} onChange={(v) => guardar({ claude_cli_model: v })} />
            </Campo>
            <Campo etiqueta="Esfuerzo" ayuda="Bajo es el mas rapido y el que menos gasta. Subirlo cuesta mucho mas por video.">
              <Segmentado valor={op.claude_cli_effort} opciones={ESFUERZOS} onChange={(v) => guardar({ claude_cli_effort: v })} />
            </Campo>
            <Campo etiqueta="Tiempo maximo por llamada (s)" ayuda="0 = automatico segun modelo y esfuerzo.">
              <input type="number" min={0} max={3600} className="campo w-32" defaultValue={op.claude_cli_timeout}
                onBlur={(e) => Number(e.target.value) !== op.claude_cli_timeout && guardar({ claude_cli_timeout: Number(e.target.value) || 0 })} />
            </Campo>
          </div>
        </Tarjeta>

        <Tarjeta titulo="Google Flow (Nano Banana)" extra={estadoFlow}>
          {!flow.disponible ? (
            <p className="text-sm text-tinta-2">
              Flow solo funciona en el PC local (necesita Chrome y tu sesion de Google). Aqui no esta instalado: los dibujos nuevos se hacen desde el PC.
            </p>
          ) : (<>
          <div className="flex items-start justify-between gap-4">
            <p className="text-sm text-tinta-2">
              Dibuja las imagenes gratis con tu cuenta de Google en un Chrome aparte. Solo en este PC: en el servidor (VPS) dejalo desactivado.
            </p>
            <Interruptor si={op.estudio_flow_habilitado} onChange={activarFlow} disabled={ocupado === "flow"} />
          </div>
          {flow.motivo && <p className="mt-2 text-xs text-tinta-3">{flow.motivo}</p>}
          <div className="mt-4 flex flex-wrap items-center gap-2">
            {flow.habilitado && flow.chrome ? (
              <button className="boton boton-linea hover:!text-error" onClick={desconectarFlow} disabled={ocupado === "flow" || flow.corriendo}>
                <LogOut size={15} /> Desconectar (cerrar Chrome)
              </button>
            ) : (
              <button className="boton boton-acento" onClick={conectarFlow} disabled={ocupado === "flow"}>
                {ocupado === "flow" ? <Loader2 size={15} className="animate-spin" /> : <LogIn size={15} />} Conectar
              </button>
            )}
            {flow.habilitado && (
              <button className="boton boton-fantasma" onClick={comprobarFlow} disabled={ocupado === "flow"}>
                <RefreshCw size={15} /> Comprobar sesion
              </button>
            )}
          </div>
          {flow.habilitado && flow.chrome && flow.sesion === false && (
            <p className="mt-2 text-xs text-tinta-3">Inicia sesion con tu cuenta de Google en la ventana de Chrome que se abrio y pulsa Comprobar sesion.</p>
          )}

          {op.estudio_flow_habilitado && (
            <div className="mt-6 grid gap-5 border-t border-linea pt-5 sm:grid-cols-2">
              <Campo etiqueta="Modelo de imagen" ayuda="Nano Banana 2 es el equilibrio. Pro tarda mas y tiene menos cupo diario.">
                <Segmentado valor={op.estudio_flow_modelo} opciones={MODELOS_FLOW} onChange={(v) => guardar({ estudio_flow_modelo: v })} />
              </Campo>
              <Campo etiqueta="Repasos de imagenes fallidas" ayuda="Cuantas veces se reintentan las que fallaron (0 a 5).">
                <Segmentado valor={String(op.estudio_flow_pasadas_extra)}
                  opciones={[0, 1, 2, 3, 4, 5].map((n) => ({ v: String(n), t: String(n) }))}
                  onChange={(v) => guardar({ estudio_flow_pasadas_extra: Number(v) })} />
              </Campo>
            </div>
          )}
          {op.estudio_flow_habilitado && <CuentasFlow />}
          </>)}
        </Tarjeta>

        <Tarjeta titulo="Telegram" extra={
          !op.telegram_habilitado ? <Punto color="gris" texto="Desactivado" />
            : tg?.activo && tg.usuario ? <Punto color="ok" texto={`Conectado: @${tg.usuario}`} />
              : tg?.error ? <Punto color="error" texto="No conecta" />
                : <Punto color="aviso" texto="Arrancando..." />
        }>
          <div className="flex items-start justify-between gap-4">
            <p className="text-sm text-tinta-2">
              Maneja el estudio desde el celular: pide videos, revisa el guion, manda tu voz y recibe el MP4. Cada equipo (este PC y el VPS) necesita su propio bot.
            </p>
            <Interruptor si={op.telegram_habilitado} disabled={!op.telegram_token_puesto && !token}
              onChange={(si) => guardar({ telegram_habilitado: si })} />
          </div>
          {tg?.error && op.telegram_habilitado && <p className="mt-2 text-xs text-error">{tg.error}</p>}
          <div className="mt-5 grid gap-5 border-t border-linea pt-5 sm:grid-cols-2">
            <Campo etiqueta="Token del bot" ayuda={op.telegram_token_puesto ? `Guardado (termina en ${op.telegram_token_final}). Escribe otro para cambiarlo.` : "Te lo da @BotFather al crear el bot."}>
              <div className="flex gap-2">
                <input type="password" className="campo flex-1" placeholder={op.telegram_token_puesto ? "••••••••" : "123456:ABC..."} value={token}
                  onChange={(e) => setToken(e.target.value)} autoComplete="off" />
                <button className="boton boton-linea" disabled={!token.trim()} onClick={async () => {
                  if (await guardar({ telegram_token: token.trim() })) setToken("");
                }}>Guardar</button>
              </div>
            </Campo>
            <div>
              <span className="etiqueta">Chats permitidos</span>
              <div className="mt-1.5 flex flex-wrap gap-2">
                {op.telegram_chats.length === 0 && <span className="text-sm text-tinta-3">Ninguno. Escribe /start al bot y aparecera abajo para permitirlo.</span>}
                {op.telegram_chats.map((c) => (
                  <span key={c} className="inline-flex items-center gap-1.5 rounded-full border border-linea px-2.5 py-1 text-xs">
                    {c}
                    <button className="text-tinta-3 hover:text-error" title="Quitar" onClick={() => {
                      if (confirm(`¿Quitar el chat ${c}? Ya no podra usar el bot.`)) guardar({ telegram_chats: op.telegram_chats.filter((x) => x !== c) });
                    }}>✕</button>
                  </span>
                ))}
              </div>
            </div>
          </div>
          {!!tg?.pendientes.length && (
            <div className="mt-5 rounded-xl border border-aviso/40 bg-aviso-suave p-3">
              <p className="text-sm font-medium">Piden usar el bot:</p>
              <ul className="mt-2 space-y-2">
                {tg.pendientes.map((p) => (
                  <li key={p.chat} className="flex flex-wrap items-center gap-2 text-sm">
                    <span className="font-medium">{p.nombre || "Sin nombre"}</span>
                    {p.usuario && <span className="text-tinta-3">@{p.usuario}</span>}
                    <span className="font-mono text-xs text-tinta-3">{p.chat}</span>
                    <button className="boton boton-acento ml-auto !py-1 text-xs" onClick={() => accion("tg", async () => {
                      const d = await ajustes.telegramPermitir(p.chat);
                      setOp(d.opciones); setTg(await ajustes.telegram());
                    })}>Permitir</button>
                    <button className="boton boton-fantasma !py-1 text-xs" onClick={() => accion("tg", async () => {
                      await ajustes.telegramRechazar(p.chat); setTg(await ajustes.telegram());
                    })}>Ignorar</button>
                  </li>
                ))}
              </ul>
            </div>
          )}
        </Tarjeta>

        <Tarjeta titulo="Voz de Gemini" extra={
          op.gemini_clave_puesta ? <Punto color="ok" texto="Clave guardada" /> : <Punto color="gris" texto="Sin clave" />
        }>
          <p className="text-sm text-tinta-2">
            Una voz mas natural que la de Microsoft para la Fabrica, con tu clave gratis de Google AI Studio. La clave gratis
            tiene un cupo de voz por dia: si se acaba, usa la de Microsoft hasta el dia siguiente.
          </p>
          <div className="mt-5 border-t border-linea pt-5">
            <Campo etiqueta="Clave de API de Gemini" ayuda={op.gemini_clave_puesta
              ? `Guardada (termina en ${op.gemini_clave_final}). Escribe otra para cambiarla.`
              : "La creas gratis en aistudio.google.com > Get API key."}>
              <div className="flex gap-2">
                <input type="password" className="campo flex-1" placeholder={op.gemini_clave_puesta ? "••••••••" : "AIza..."} value={claveGemini}
                  onChange={(e) => setClaveGemini(e.target.value)} autoComplete="off" />
                <button className="boton boton-linea" disabled={!claveGemini.trim()} onClick={async () => {
                  if (await guardar({ gemini_api_key: claveGemini.trim() })) setClaveGemini("");
                }}>Guardar</button>
                {op.gemini_clave_puesta && (
                  <button className="boton boton-linea hover:!text-error" onClick={() => {
                    if (confirm("¿Quitar la clave de Gemini? La Fabrica dejara de ofrecer sus voces.")) guardar({ gemini_api_key: "" });
                  }}>Quitar</button>
                )}
              </div>
            </Campo>
          </div>
        </Tarjeta>

        <Tarjeta titulo="Videos de stock (Pexels / Pixabay)" extra={
          op.pexels_claves.length || op.pixabay_claves.length
            ? <Punto color="ok" texto={`${op.pexels_claves.length + op.pixabay_claves.length} clave(s)`} />
            : <Punto color="gris" texto="Sin claves" />
        }>
          <p className="text-sm text-tinta-2">
            Claves gratis para buscar videos de fondo (B-roll). Si pones varias de la misma pagina se turnan para no gastar el
            cupo de una sola.
          </p>
          {(["pexels", "pixabay"] as const).map((prov) => {
            const claves = prov === "pexels" ? op.pexels_claves : op.pixabay_claves;
            return (
              <div key={prov} className="mt-5 border-t border-linea pt-5">
                <Campo etiqueta={prov === "pexels" ? "Pexels" : "Pixabay"} ayuda={prov === "pexels"
                  ? "La creas gratis en pexels.com/api."
                  : "La creas gratis en pixabay.com/api/docs (aparece al iniciar sesion)."}>
                  {claves.length > 0 && (
                    <ul className="mb-2 flex flex-wrap gap-2">
                      {claves.map((fin, i) => (
                        <li key={i} className="flex items-center gap-2 rounded border border-linea px-2 py-1 text-xs">
                          <span className="font-mono">••••{fin}</span>
                          <button className="hover:text-error" title="Quitar" onClick={() => {
                            if (confirm(`¿Quitar la clave de ${prov} que termina en ${fin}?`))
                              accion("stock", async () => setOp((await ajustes.stock(prov, { quitar: i })).opciones));
                          }}>✕</button>
                        </li>
                      ))}
                    </ul>
                  )}
                  <div className="flex gap-2">
                    <input type="password" className="campo flex-1" placeholder="Pega la clave" autoComplete="off"
                      value={claveStock[prov]} onChange={(e) => setClaveStock({ ...claveStock, [prov]: e.target.value })} />
                    <button className="boton boton-linea" disabled={!claveStock[prov].trim() || ocupado === "stock"}
                      onClick={() => accion("stock", async () => {
                        setOp((await ajustes.stock(prov, { agregar: claveStock[prov].trim() })).opciones);
                        setClaveStock((c) => ({ ...c, [prov]: "" }));
                      })}>Añadir</button>
                  </div>
                </Campo>
              </div>
            );
          })}
        </Tarjeta>

        <Tarjeta titulo="YouTube (descargas)" extra={
          !yt ? null
            : yt.ok === false ? <Punto color="error" texto="YouTube bloquea este equipo" />
              : yt.ok ? <Punto color="ok" texto="Descargas funcionando" />
                : yt.cookies ? <Punto color="ok" texto="Cookies subidas" />
                  : <Punto color="gris" texto="Sin cookies (normal en el PC)" />
        }>
          <p className="text-sm text-tinta-2">
            Clonar video, el banco de clips e Ideas virales bajan de YouTube sin cuenta. En el servidor (VPS) YouTube a veces lo bloquea
            ("confirma que no eres un bot"): ahi sube un <b className="text-tinta">cookies.txt</b> de una cuenta de YouTube. Usa una cuenta secundaria, no la principal.
          </p>
          {yt?.mensaje && <p className={`mt-2 text-xs ${yt.ok ? "text-tinta-3" : "text-error"}`}>{yt.mensaje}</p>}
          {yt?.cookies && yt.fecha && <p className="mt-2 text-xs text-tinta-3">Cookies subidas el {yt.fecha}. Si un dia vuelve el bloqueo, exportalas otra vez.</p>}
          <input ref={archivoYt} type="file" accept=".txt,text/plain" className="hidden" onChange={(e) => {
            const f = e.target.files?.[0]; e.target.value = "";
            if (f) accion("yt", async () => { await ajustes.youtubeSubir(f); setYt(await ajustes.youtubeProbar()); });
          }} />
          <div className="mt-4 flex flex-wrap items-center gap-2">
            <button className="boton boton-acento" onClick={() => archivoYt.current?.click()} disabled={ocupado === "yt"}>
              {ocupado === "yt" ? <Loader2 size={15} className="animate-spin" /> : <Upload size={15} />} {yt?.cookies ? "Cambiar cookies.txt" : "Subir cookies.txt"}
            </button>
            <button className="boton boton-fantasma" onClick={() => accion("yt", async () => setYt(await ajustes.youtubeProbar()))} disabled={ocupado === "yt"}>
              <RefreshCw size={15} /> Probar descarga
            </button>
            {yt?.cookies && (
              <button className="boton boton-linea hover:!text-error" disabled={ocupado === "yt"} onClick={() => {
                if (confirm("¿Quitar las cookies de YouTube? Las descargas seguiran sin cuenta.")) accion("yt", async () => setYt(await ajustes.youtubeBorrar()));
              }}><Trash2 size={15} /> Quitar</button>
            )}
          </div>
          <p className="mt-3 text-xs text-tinta-3">
            Como sacarlas: en Chrome instala la extension &quot;Get cookies.txt LOCALLY&quot;, entra a youtube.com con la sesion iniciada y exporta.
          </p>
        </Tarjeta>

        <Tarjeta titulo="Carpetas del servidor">
          <Campo etiqueta="Carpetas permitidas como fuente de recursos"
            ayuda="Una por linea. Vacio = cualquiera (uso local). En el VPS conviene limitarlo, por ejemplo /recursos.">
            <textarea className="campo min-h-24 w-full font-mono text-sm" value={carpetas} onChange={(e) => setCarpetas(e.target.value)}
              onBlur={() => {
                const lista = carpetas.split("\n").map((x) => x.trim()).filter(Boolean);
                if (lista.join("\n") !== op.estudio_carpetas_permitidas.join("\n")) guardar({ estudio_carpetas_permitidas: lista });
              }} />
          </Campo>
        </Tarjeta>
      </div>
    </main>
  );
}
