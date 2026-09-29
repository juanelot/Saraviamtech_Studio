import Link from "next/link";
import { MARCA } from "@/lib/marca";

export default function Barra() {
  return (
    <header className="sticky top-0 z-30 border-b border-linea bg-papel/85 backdrop-blur">
      <div className="mx-auto flex h-14 max-w-6xl items-center gap-3 px-4">
        <Link href="/" className="flex items-center gap-2.5">
          <span className="grid h-8 w-8 place-items-center rounded-lg bg-tinta font-display text-sm font-bold text-papel">
            {MARCA.corto}
          </span>
          <span className="font-display text-lg font-semibold tracking-tight">{MARCA.nombre}</span>
        </Link>
        <nav className="ml-auto flex items-center gap-1 text-sm">
          <Link href="/" className="boton boton-fantasma">Mis videos</Link>
        </nav>
      </div>
    </header>
  );
}
