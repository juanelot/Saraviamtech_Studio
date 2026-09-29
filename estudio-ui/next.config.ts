import type { NextConfig } from "next";

// Backend FastAPI (el mismo motor de MoneyPrinterTurbo). En Docker se pasa como
// build-arg: las rewrites se serializan EN EL BUILD.
const API_URL = process.env.MPT_API_URL || "http://localhost:8080";

const nextConfig: NextConfig = {
  output: "standalone",
  async rewrites() {
    return [
      { source: "/api/estudio/:path*", destination: `${API_URL}/api/v1/estudio/:path*` },
      { source: "/api/motor/:path*", destination: `${API_URL}/api/v1/:path*` },
    ];
  },
};

export default nextConfig;
