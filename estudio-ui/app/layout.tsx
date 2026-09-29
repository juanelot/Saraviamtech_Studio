import type { Metadata } from "next";
import { Fraunces, Inter } from "next/font/google";
import "./globals.css";
import { MARCA } from "@/lib/marca";
import Barra from "@/components/Barra";

const display = Fraunces({ subsets: ["latin"], variable: "--fuente-display", weight: ["500", "600", "700"] });
const texto = Inter({ subsets: ["latin"], variable: "--fuente-texto" });

export const metadata: Metadata = {
  title: MARCA.nombre,
  description: MARCA.eslogan,
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="es" className={`${display.variable} ${texto.variable}`}>
      <body className="min-h-screen">
        <Barra />
        {children}
      </body>
    </html>
  );
}
