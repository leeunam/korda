import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  // Gera .next/standalone (server.js + dependências rastreadas) para a imagem Docker. O Vercel ignora.
  output: "standalone",
  // Só em `next dev`: deixa abrir o servidor pelo IP da rede local (ex.: testar no celular). Sem isto o Next
  // bloqueia os recursos de dev, a página não hidrata e nada interativo funciona (ex.: o menu do cabeçalho).
  allowedDevOrigins: ["10.*.*.*", "192.168.*.*", "*.local"],
  cacheComponents: true,
  partialPrefetching: true,
  turbopack: {
    rules: {
      "*.css": {
        loaders: ["@tailwindcss/turbopack"],
        as: "*.css",
      },
    },
  },
};

export default nextConfig;
