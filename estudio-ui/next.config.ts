import type { NextConfig } from "next";

// Backend FastAPI (el mismo motor de MoneyPrinterTurbo). En Docker se pasa como
// build-arg: las rewrites se serializan EN EL BUILD.
const API_URL = process.env.MPT_API_URL || "http://localhost:8080";

const nextConfig: NextConfig = {
  output: "standalone",
  experimental: {
    // Las subidas (clips de Flow, ZIPs de la extension) pasan por las rewrites y
    // Next corta el cuerpo a 10 MB por defecto. La web sube por tandas de <=200 MB.
    proxyClientMaxBodySize: "1gb",
  },
  async rewrites() {
    return [
      { source: "/api/estudio/:path*", destination: `${API_URL}/api/v1/estudio/:path*` },
      { source: "/api/motor/:path*", destination: `${API_URL}/api/v1/:path*` },
    ];
  },
};

export default nextConfig;
