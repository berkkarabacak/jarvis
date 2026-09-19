import type { NextConfig } from "next"

const exportUi = process.env.JARVIS_DESKTOP_EXPORT === "1"
const apiOrigin = process.env.JARVIS_API_ORIGIN || "http://127.0.0.1:8787"

const nextConfig: NextConfig = {
  output: exportUi ? "export" : undefined,
  basePath: exportUi ? "/desktop-ui" : "",
  trailingSlash: exportUi,
  images: { unoptimized: true },
}

if (!exportUi) {
  nextConfig.rewrites = async () => [
    { source: "/api/:path*", destination: `${apiOrigin}/api/:path*` },
    { source: "/ceo", destination: `${apiOrigin}/ceo` },
    { source: "/ceo/:path*", destination: `${apiOrigin}/ceo/:path*` },
  ]
}

export default nextConfig
