/**
 * Fundo de vidro do cabeçalho, compartilhado pela barra (componente de servidor) e pelo painel do menu (cliente).
 * Fica fora de MobileMenu.tsx: exportado de um módulo "use client", chegaria ao servidor como referência, não como texto.
 */
export const HEADER_GLASS =
  "rounded-2xl border border-white/9 bg-black/55 shadow-[0_8px_32px_rgb(0_0_0/0.45)] backdrop-blur-xl";
