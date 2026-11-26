"use client";

import { useRef, type KeyboardEvent, type PointerEvent } from "react";

type Props = {
  /** "x": arrasta na horizontal (altera largura); "y": na vertical (altera altura). */
  axis: "x" | "y";
  value: number;
  min: number;
  max: number;
  onChange: (value: number) => void;
  onReset: () => void;
  controls: string;
  label: string;
};

const STEP = 16;
const BIG_STEP = 64;

/**
 * Divisor entre o grafo e o painel lateral. O painel fica à direita (x) ou
 * embaixo (y), então arrastar para a esquerda/cima aumenta o painel.
 */
export function ResizeHandle({ axis, value, min, max, onChange, onReset, controls, label }: Props) {
  const drag = useRef<{ start: number; value: number } | null>(null);
  const clamp = (v: number) => Math.round(Math.min(max, Math.max(min, v)));
  const coord = (e: PointerEvent) => (axis === "x" ? e.clientX : e.clientY);

  const onPointerDown = (e: PointerEvent<HTMLDivElement>) => {
    if (e.button !== 0) return;
    e.preventDefault();
    e.currentTarget.setPointerCapture(e.pointerId);
    drag.current = { start: coord(e), value };
    document.body.dataset.resizing = axis;
  };

  const onPointerMove = (e: PointerEvent<HTMLDivElement>) => {
    const d = drag.current;
    if (!d) return;
    onChange(clamp(d.value + (d.start - coord(e))));
  };

  const end = (e: PointerEvent<HTMLDivElement>) => {
    if (!drag.current) return;
    drag.current = null;
    if (e.currentTarget.hasPointerCapture(e.pointerId)) e.currentTarget.releasePointerCapture(e.pointerId);
    delete document.body.dataset.resizing;
  };

  const onKeyDown = (e: KeyboardEvent<HTMLDivElement>) => {
    const step = e.shiftKey ? BIG_STEP : STEP;
    const grow = axis === "x" ? "ArrowLeft" : "ArrowUp";
    const shrink = axis === "x" ? "ArrowRight" : "ArrowDown";
    let next: number | null = null;
    if (e.key === grow) next = value + step;
    else if (e.key === shrink) next = value - step;
    else if (e.key === "Home") next = min;
    else if (e.key === "End") next = max;
    else if (e.key === "Enter") {
      e.preventDefault();
      onReset();
      return;
    }
    if (next === null) return;
    e.preventDefault();
    onChange(clamp(next));
  };

  return (
    <div
      role="separator"
      tabIndex={0}
      aria-label={label}
      aria-controls={controls}
      aria-orientation={axis === "x" ? "vertical" : "horizontal"}
      aria-valuenow={value}
      aria-valuemin={min}
      aria-valuemax={max}
      onPointerDown={onPointerDown}
      onPointerMove={onPointerMove}
      onPointerUp={end}
      onPointerCancel={end}
      onDoubleClick={onReset}
      onKeyDown={onKeyDown}
      className={`group relative flex shrink-0 touch-none items-center justify-center outline-none select-none ${
        axis === "x" ? "w-3 cursor-col-resize self-stretch" : "h-2 cursor-row-resize"
      }`}
    >
      <span
        aria-hidden
        className={`rounded-full bg-line-strong opacity-0 transition-opacity group-hover:opacity-100 group-focus-visible:bg-accent group-focus-visible:opacity-100 group-active:opacity-100 ${
          axis === "x" ? "h-10 w-1" : "h-1 w-10"
        }`}
      />
    </div>
  );
}
