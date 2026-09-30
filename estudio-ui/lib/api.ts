// Cliente del backend del Estudio (/api/v1/estudio via rewrite /api/estudio).

export type EtapaId = "guion" | "voz" | "escenas" | "recursos" | "asignacion" | "render";
export type EstadoEtapa = "ok" | "obsoleta" | "pendiente" | "error" | "ejecutando";

export interface Plano {
  i: number;
  inicio: number;
  fin: number;
  texto: string;
  recurso?: string;
  nombre?: string;
  tipo?: "imagen" | "video";
  offset?: number;
  motivo?: string;
  fijado?: boolean;
  escena?: number;
}

export interface Escena {
  scene_number: number;
  inicio: number;
  fin: number;
  duracion: number;
  planos: number[];
  narration: string;
  image_prompt: string;
  video_prompt: string;
  image_prompt_editado?: boolean;
  video_prompt_editado?: boolean;
}

export interface Recurso {
  id: string;
  nombre: string;
  origen: "subido" | "carpeta";
  tipo: "imagen" | "video";
  ancho: number;
  alto: number;
  duracion: number;
  descripcion: string;
  descripcion_manual: boolean;
  miniatura?: string;
  carpeta?: "images" | "videos" | "";
  escena?: number | null;
}

export const mini = (r: { id: string; miniatura?: string }) => r.miniatura || r.id.split("-")[0];

export interface SalidaGuion { texto: string; origen: string; palabras: number; duracion_estimada_s: number }
export interface SalidaVoz { audio: string; srt: string; duracion: number; planos: Plano[] }
export interface SalidaRecursos { recursos: Recurso[]; total: number; imagenes: number; videos: number; sin_descripcion: number }
export interface SalidaEscenas { escenas: Escena[]; total: number; con_prompt: number; generar: string; script: string }
export interface SalidaAsignacion { planos: Plano[]; recursos_usados: number; faltan?: number[] }
export interface SalidaRender {
  mp4: string; duracion: number; ancho: number; alto: number;
  clips_nuevos: number; clips_reutilizados: number; tam_mb: number; edicion?: string | null;
}

export type Params = Record<string, unknown>;

export interface VistaEtapa<S = unknown> {
  estado: EstadoEtapa;
  salida: S | null;
  error: string | null;
  duracion_s: number | null;
  terminado: number | null;
  params: Params;
}

export interface Trabajo {
  hasta: EtapaId;
  etapa: EtapaId | null;
  progreso: number;
  mensaje: string;
  inicio: number;
}

export interface Vista {
  proyecto: { id: string; titulo: string; creado: number; actualizado: number; params: Record<string, Params> };
  etapas: {
    guion: VistaEtapa<SalidaGuion>;
    voz: VistaEtapa<SalidaVoz>;
    escenas: VistaEtapa<SalidaEscenas>;
    recursos: VistaEtapa<SalidaRecursos>;
    asignacion: VistaEtapa<SalidaAsignacion>;
    render: VistaEtapa<SalidaRender>;
  };
  orden: EtapaId[];
  deps: Record<EtapaId, EtapaId[]>;
  trabajo: Trabajo | null;
  log: string[];
}

export interface Subido {
  nombre: string; tipo: "imagen" | "video"; tam: number;
  carpeta: "images" | "videos" | ""; escena: number | null;
}

export interface ResumenProyecto {
  id: string; titulo: string; creado: number; actualizado: number;
  mp4: string | null; portada: string | null; duracion: number | null; trabajando: boolean;
}

const BASE = "/api/estudio";

async function pedir<T>(ruta: string, init?: RequestInit): Promise<T> {
  const r = await fetch(BASE + ruta, { cache: "no-store", ...init });
  if (!r.ok) {
    let msg = `${r.status}`;
    try {
      const j = await r.json();
      msg = j.detail || j.message || msg;
    } catch {}
    throw new Error(msg);
  }
  return r.json();
}

const json = (body: unknown): RequestInit => ({
  headers: { "Content-Type": "application/json" },
  body: JSON.stringify(body),
});

export const api = {
  listar: () => pedir<{ proyectos: ResumenProyecto[] }>("/proyectos"),
  crear: (titulo: string) => pedir<Vista>("/proyectos", { method: "POST", ...json({ titulo }) }),
  ver: (id: string) => pedir<Vista>(`/proyectos/${id}`),
  editar: (id: string, cambios: { titulo?: string; params?: Record<string, Params> }) =>
    pedir<Vista>(`/proyectos/${id}`, { method: "PATCH", ...json(cambios) }),
  borrar: (id: string) => pedir<{ ok: boolean }>(`/proyectos/${id}`, { method: "DELETE" }),
  duplicar: (id: string, titulo?: string) =>
    pedir<Vista>(`/proyectos/${id}/duplicar`, { method: "POST", ...json({ titulo }) }),
  ejecutar: (id: string, hasta: EtapaId, forzar: EtapaId[] = []) =>
    pedir<Vista>(`/proyectos/${id}/ejecutar`, { method: "POST", ...json({ hasta, forzar }) }),
  cancelar: (id: string) => pedir<{ cancelado: boolean }>(`/proyectos/${id}/cancelar`, { method: "POST" }),
  subidos: (id: string) => pedir<{ archivos: Subido[] }>(`/proyectos/${id}/recursos`),
  subir: (id: string, archivos: File[], sub: "" | "images" | "videos" = "") => {
    const fd = new FormData();
    archivos.forEach((a) => fd.append("archivos", a));
    return pedir<{ guardados: string[]; rechazados: string[] }>(`/proyectos/${id}/recursos?sub=${sub}`, { method: "POST", body: fd });
  },
  quitar: (id: string, nombre: string) =>
    pedir<{ ok: boolean }>(`/proyectos/${id}/recursos/${nombre.split("/").map(encodeURIComponent).join("/")}`, { method: "DELETE" }),
};

export interface ConceptoMiniatura {
  nombre: string; idea: string; texto: string; prompt: string; prompt_sin_texto: string;
  referencia_escena: number | null;
}
export interface EstadoMiniatura {
  params: { indicaciones: string; texto_en_imagen: boolean; cantidad: number; modelo: string; esfuerzo: string };
  conceptos: ConceptoMiniatura[]; analisis_referencia: string; error: string | null;
  generado: number | null; generando: boolean; referencia: string | null; final: string | null; version: number | null;
}

export const miniatura = {
  ver: (id: string) => pedir<EstadoMiniatura>(`/proyectos/${id}/miniatura`),
  generar: (id: string, params: Partial<EstadoMiniatura["params"]>) =>
    pedir<EstadoMiniatura>(`/proyectos/${id}/miniatura/generar`, { method: "POST", ...json(params) }),
  subir: (id: string, tipo: "referencia" | "final", archivo: File) => {
    const fd = new FormData();
    fd.append("archivo", archivo);
    return pedir<EstadoMiniatura>(`/proyectos/${id}/miniatura/${tipo}`, { method: "POST", body: fd });
  },
  quitar: (id: string, tipo: "referencia" | "final") =>
    pedir<EstadoMiniatura>(`/proyectos/${id}/miniatura/${tipo}`, { method: "DELETE" }),
};

export interface VozClonada { id: string; nombre: string; duracion: number | null; transcripcion: string }
export interface VocesClonadas { activo: boolean; voces: VozClonada[]; error: string | null }

export const clonadas = {
  listar: () => pedir<VocesClonadas>("/voces-clonadas"),
  crear: (audio: Blob, nombre: string, transcripcion = "", archivo = "voz.wav") => {
    const fd = new FormData();
    fd.append("audio", audio, archivo);
    fd.append("nombre", nombre);
    fd.append("transcripcion", transcripcion);
    return pedir<VozClonada>("/voces-clonadas", { method: "POST", body: fd });
  },
};

export interface Turno { rol: "persona" | "asistente"; texto: string; t: number }
export interface Charla { id: string; turnos: Turno[]; pensando: boolean; error: string | null }

export const asistente = {
  preguntar: (pregunta: string, charla?: string | null, proyecto?: string | null) =>
    pedir<Charla>("/asistente", { method: "POST", ...json({ pregunta, charla, proyecto }) }),
  ver: (charla: string) => pedir<Charla>(`/asistente/${charla}`),
};

export const url = {
  archivo: (id: string, ruta: string, v?: number | null) =>
    `${BASE}/proyectos/${id}/archivo/${ruta}${v ? `?v=${Math.round(v)}` : ""}`,
  miniatura: (h: string) => `${BASE}/miniatura/${h}`,
  original: (id: string, h: string) => `${BASE}/proyectos/${id}/original/${h}`,
  descargar: (id: string) => `${BASE}/proyectos/${id}/descargar`,
  scriptJson: (id: string) => `${BASE}/proyectos/${id}/script.json`,
  promptsTxt: (id: string) => `${BASE}/proyectos/${id}/prompts.txt`,
  muestraClonada: (vid: string) => `${BASE}/voces-clonadas/${vid}/audio`,
  descargarMiniatura: (id: string) => `${BASE}/proyectos/${id}/miniatura-descargar`,
};

export async function listarMusica(): Promise<string[]> {
  try {
    const r = await fetch("/api/motor/musics", { cache: "no-store" });
    const j = await r.json();
    return (j?.data?.files || []).map((f: { file: string }) => f.file).sort();
  } catch {
    return [];
  }
}

export function mmss(s: number | null | undefined) {
  if (s == null || isNaN(s)) return "–";
  const m = Math.floor(s / 60);
  const r = Math.round(s % 60);
  return `${m}:${String(r).padStart(2, "0")}`;
}
