// Lo UNICO que obliga a leer texto de Flow: el aviso de cuota / limite de uso.
// El idioma de la web sigue al de la cuenta de Google. Si un idioma no esta aqui no se
// rompe nada: el aviso se trata como un fallo normal (4 intentos), solo no pausa a tiempo.
// Para ampliar: anadir frases en minusculas (sin tildes: se comparan sin ellas).
export const FRASES_LIMITE = [
  // es
  'alcanzado el limite', 'limite de uso', 'limite diario', 'cuota', 'has alcanzado', 'demasiadas solicitudes', 'intentalo mas tarde', 'vuelve a intentarlo mas tarde',
  // en
  'quota', 'rate limit', 'limit reached', 'reached your', 'too many requests', 'try again later', 'daily limit', 'usage limit',
  // pt
  'sua cota', 'atingiu o limite', 'tente novamente mais tarde', 'muitas solicitacoes',
  // fr
  'quota atteint', 'limite atteinte', 'trop de requetes', 'reessayez plus tard',
  // it
  'limite raggiunto', 'troppe richieste', 'riprova piu tardi',
  // de
  'kontingent', 'limit erreicht', 'zu viele anfragen', 'spater erneut',
];

const sinTildes = (s) => s.toLowerCase().normalize('NFD').replace(/[̀-ͯ]/g, '');

export function esLimite(texto) {
  if (!texto) return false;
  const t = sinTildes(texto);
  return FRASES_LIMITE.some((f) => t.includes(f));
}
