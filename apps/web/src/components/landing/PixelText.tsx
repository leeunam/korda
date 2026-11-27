"use client";

import { useEffect, useRef } from "react";

/**
 * Texto em serifa "pixelado": desenhado num canvas de baixa resolução, com o alfa
 * binarizado, e ampliado com `image-rendering: pixelated`. Um <span> invisível com a
 * fonte real reserva o espaço do layout; leitores de tela leem o título completo no <h1>.
 */
export function PixelText({ text, fontFamily, weight = 400 }: { text: string; fontFamily: string; weight?: number }) {
  const sizerRef = useRef<HTMLSpanElement>(null);
  const canvasRef = useRef<HTMLCanvasElement>(null);

  useEffect(() => {
    const sizer = sizerRef.current;
    const canvas = canvasRef.current;
    if (!sizer || !canvas) return;

    const draw = () => {
      const rect = canvas.getBoundingClientRect();
      const fontSize = parseFloat(getComputedStyle(sizer).fontSize);
      if (!rect.width || !fontSize) return;

      // Um "pixel" a cada ~1/30 do corpo da fonte: serrilhado visível, mas legível.
      const px = Math.max(2, fontSize / 30);
      const w = Math.ceil(rect.width / px);
      const h = Math.ceil(rect.height / px);
      canvas.width = w;
      canvas.height = h;

      // Desenha no tamanho real (mesmas métricas e tamanho óptico do texto em CSS) e só
      // então reduz para a grade de pixels; desenhar direto em corpo pequeno muda a largura.
      const style = getComputedStyle(sizer);
      const full = document.createElement("canvas");
      full.width = Math.ceil(rect.width);
      full.height = Math.ceil(rect.height);
      const fctx = full.getContext("2d");
      const ctx = canvas.getContext("2d", { willReadFrequently: true });
      if (!fctx || !ctx) return;
      fctx.font = `${weight} ${fontSize}px ${fontFamily}`;
      if ("letterSpacing" in fctx) fctx.letterSpacing = style.letterSpacing === "normal" ? "0px" : style.letterSpacing;
      fctx.fillStyle = style.color;
      fctx.textAlign = "center";
      const m = fctx.measureText(text);
      const asc = m.fontBoundingBoxAscent ?? m.actualBoundingBoxAscent;
      const desc = m.fontBoundingBoxDescent ?? m.actualBoundingBoxDescent;
      fctx.fillText(text, full.width / 2, (full.height - (asc + desc)) / 2 + asc);

      ctx.clearRect(0, 0, w, h);
      ctx.imageSmoothingQuality = "high";
      ctx.drawImage(full, 0, 0, w, h);

      // Bordas duras: sem anti-aliasing, cada pixel é aceso ou apagado.
      const img = ctx.getImageData(0, 0, w, h);
      const d = img.data;
      for (let i = 3; i < d.length; i += 4) d[i] = d[i] > 100 ? 255 : 0;
      ctx.putImageData(img, 0, 0);
    };

    let cancelled = false;
    document.fonts.ready.then(() => !cancelled && draw());
    const ro = new ResizeObserver(draw);
    ro.observe(sizer);
    return () => {
      cancelled = true;
      ro.disconnect();
    };
  }, [text, fontFamily, weight]);

  return (
    <span className="relative inline-block" aria-hidden>
      <span ref={sizerRef} className="invisible">
        {text}
      </span>
      <canvas
        ref={canvasRef}
        className="pointer-events-none absolute -top-[20%] -left-[4%] h-[140%] w-[108%]"
        style={{ imageRendering: "pixelated" }}
      />
    </span>
  );
}
