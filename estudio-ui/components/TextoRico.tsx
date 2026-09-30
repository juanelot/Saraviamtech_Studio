// Markdown suficiente para las respuestas de un prompt maestro: bloques ```,
// tablas |a|b|, titulos #, separadores ---, **negrita** y `codigo`.

function EnLinea({ texto }: { texto: string }) {
  return (
    <>
      {texto.split(/(\*\*[^*]+\*\*|`[^`]+`)/g).map((t, j) =>
        t.startsWith("**") && t.endsWith("**") && t.length > 4 ? <strong key={j}>{t.slice(2, -2)}</strong>
          : t.startsWith("`") && t.endsWith("`") && t.length > 2 ? <code key={j} className="rounded bg-hundido px-1 font-mono text-[0.85em]">{t.slice(1, -1)}</code>
          : t,
      )}
    </>
  );
}

const celdas = (linea: string) => linea.trim().replace(/^\||\|$/g, "").split("|").map((c) => c.trim());
const esSeparador = (linea: string) => /^\s*\|?\s*:?-{2,}:?\s*(\|\s*:?-{2,}:?\s*)*\|?\s*$/.test(linea);

export default function TextoRico({ texto }: { texto: string }) {
  const partes = texto.split(/```[\w-]*\n?/);
  return (
    <div className="space-y-2 leading-relaxed">
      {partes.map((parte, i) =>
        i % 2 === 1 ? (
          <pre key={i} className="overflow-x-auto whitespace-pre-wrap rounded-lg bg-hundido p-3 font-mono text-xs">{parte.trim()}</pre>
        ) : (
          <Bloques key={i} texto={parte} />
        ),
      )}
    </div>
  );
}

function Bloques({ texto }: { texto: string }) {
  const lineas = texto.split("\n");
  const salida: React.ReactNode[] = [];
  let parrafo: string[] = [];
  const cerrar = () => {
    if (parrafo.length) {
      salida.push(<p key={salida.length} className="whitespace-pre-wrap"><EnLinea texto={parrafo.join("\n")} /></p>);
      parrafo = [];
    }
  };
  for (let k = 0; k < lineas.length; k++) {
    const l = lineas[k];
    if (l.trim().startsWith("|") && k + 1 < lineas.length && esSeparador(lineas[k + 1])) {
      cerrar();
      const cabecera = celdas(l);
      const filas: string[][] = [];
      k += 2;
      while (k < lineas.length && lineas[k].trim().startsWith("|")) filas.push(celdas(lineas[k++]));
      k--;
      salida.push(
        <div key={salida.length} className="overflow-x-auto">
          <table className="w-full border-collapse text-[13px]">
            <thead><tr>{cabecera.map((c, j) => <th key={j} className="border-b border-linea px-2 py-1.5 text-left font-semibold">{c}</th>)}</tr></thead>
            <tbody>{filas.map((f, r) => (
              <tr key={r}>{f.map((c, j) => <td key={j} className="border-b border-linea/60 px-2 py-1.5 align-top"><EnLinea texto={c} /></td>)}</tr>
            ))}</tbody>
          </table>
        </div>,
      );
    } else if (/^\s*#{1,4}\s/.test(l)) {
      cerrar();
      salida.push(<p key={salida.length} className="pt-1 font-display font-semibold"><EnLinea texto={l.replace(/^\s*#+\s*/, "")} /></p>);
    } else if (/^\s*(-{3,}|={3,}|\*{3,})\s*$/.test(l)) {
      cerrar();
      salida.push(<hr key={salida.length} className="border-linea" />);
    } else if (!l.trim()) {
      cerrar();
    } else {
      parrafo.push(l);
    }
  }
  cerrar();
  return <>{salida}</>;
}
