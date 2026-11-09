"use client";

// Cuentas de Google para Flow: un perfil de Chrome por cuenta. Los clips de video (Veo, novelas) gastan creditos
// (10 por clip); cuando una cuenta se queda sin ellos, la generacion pasa sola a la siguiente.
import { useEffect, useState } from "react";
import { ExternalLink, Loader2, Plus, RefreshCw, Trash2 } from "lucide-react";
import { ajustes, type CuentasFlow as Datos } from "@/lib/api";

export default function CuentasFlow() {
  const [d, setD] = useState<Datos | null>(null);
  const [ocupado, setOcupado] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  const cargar = () => ajustes.flowCuentas().then(setD).catch((e) => setError(e.message));
  useEffect(() => { cargar(); }, []);
  // mientras revisa (en segundo plano) se refresca solo
  useEffect(() => {
    if (!d?.revisando) return;
    const t = setInterval(cargar, 4000);
    return () => clearInterval(t);
  }, [d?.revisando]);

  async function hacer(nombre: string, accion: "nueva" | "abrir" | "quitar" | "revisar", perfil?: number) {
    setError(null); setOcupado(nombre);
    try { setD(await ajustes.flowCuentasAccion(accion, perfil)); }
    catch (e) { setError((e as Error).message); }
    finally { setOcupado(null); }
  }

  if (!d) return error ? <p className="text-xs text-error">{error}</p> : null;
  const total = d.perfiles.reduce((n, p) => n + (p.sin_sesion ? 0 : Math.floor((p.creditos ?? 0) / d.coste_video)), 0);
  const bloqueado = d.ocupado || d.revisando || !!ocupado;

  return (
    <div className="mt-6 border-t border-linea pt-5">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <div>
          <p className="text-sm font-medium">Cuentas para video (Veo)</p>
          <p className="text-xs text-tinta-3">
            Cada clip de video gasta {d.coste_video} creditos. Al acabarse en una cuenta se pasa a la siguiente.
            Quedan unos <b>{total}</b> clips entre todas.
          </p>
        </div>
        <div className="flex gap-2">
          <button className="boton boton-fantasma !py-1 text-xs" disabled={bloqueado} onClick={() => hacer("revisar", "revisar")}>
            {d.revisando ? <Loader2 size={13} className="animate-spin" /> : <RefreshCw size={13} />} Revisar creditos
          </button>
          <button className="boton boton-linea !py-1 text-xs" disabled={bloqueado} onClick={() => hacer("nueva", "nueva")}>
            {ocupado === "nueva" ? <Loader2 size={13} className="animate-spin" /> : <Plus size={13} />} Anadir cuenta
          </button>
        </div>
      </div>
      {ocupado === "nueva" || d.perfiles.some((p) => !p.email && !p.visto) ? (
        <p className="mt-2 text-xs text-tinta-3">
          Se abre un Chrome nuevo: inicia sesion con la otra cuenta de Google, ciérralo y pulsa Revisar creditos.
        </p>
      ) : null}
      <ul className="mt-3 divide-y divide-linea rounded border border-linea text-sm">
        {d.perfiles.map((p, i) => (
          <li key={i} className="flex items-center gap-3 px-3 py-2">
            <span className="w-5 text-xs text-tinta-3">{i + 1}</span>
            <span className="min-w-0 flex-1 truncate">
              {p.email || <span className="text-tinta-3">sin revisar</span>}
              {i === d.actual && <span className="ml-2 text-xs text-tinta-3">(en uso)</span>}
            </span>
            <span className="text-xs">
              {p.sin_sesion ? <span className="text-error">sin sesion</span>
                : p.creditos == null ? <span className="text-tinta-3">—</span>
                  : <>{p.creditos} creditos · {Math.floor(p.creditos / d.coste_video)} clips</>}
            </span>
            <button className="text-tinta-3 hover:text-tinta" title="Abrir su Chrome (iniciar sesion)" disabled={bloqueado}
              onClick={() => hacer(`abrir${i}`, "abrir", i)}>
              {ocupado === `abrir${i}` ? <Loader2 size={14} className="animate-spin" /> : <ExternalLink size={14} />}
            </button>
            {i > 0 && (
              <button className="text-tinta-3 hover:text-error" title="Quitar esta cuenta" disabled={bloqueado}
                onClick={() => { if (confirm(`¿Quitar la cuenta ${p.email || i + 1}? Se borra su perfil de Chrome.`)) hacer(`quitar${i}`, "quitar", i); }}>
                <Trash2 size={14} />
              </button>
            )}
          </li>
        ))}
      </ul>
      <p className="mt-2 text-xs text-tinta-3">Los creditos gratis se renuevan cada dia (Flow dice la hora en el menu de la cuenta).</p>
      {error && <p className="mt-2 text-xs text-error">{error}</p>}
    </div>
  );
}
