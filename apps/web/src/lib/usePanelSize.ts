"use client";

import { useCallback, useMemo, useState, useSyncExternalStore } from "react";
import { maxX, SIDEBAR_DEFAULT_X, SIDEBAR_MIN_X, storageKey, type Axis } from "./panelBounds";

export type { Axis };

/** Mesmo breakpoint do `md:` do Tailwind: acima dele o painel fica ao lado do grafo. */
const DESKTOP = "(min-width: 768px)";

const DEFAULTS: Record<Axis, (vw: number, vh: number) => number> = {
  x: () => SIDEBAR_DEFAULT_X,
  y: (_, vh) => Math.round(vh * 0.5),
};

const MIN: Record<Axis, number> = { x: SIDEBAR_MIN_X, y: 160 };

const maxFor = (axis: Axis, vw: number, vh: number) =>
  axis === "x" ? maxX(vw) : Math.max(MIN.y, Math.round(vh * 0.8));

function readStored(axis: Axis): number | null {
  try {
    const raw = window.localStorage.getItem(storageKey(axis));
    const n = raw === null ? NaN : Number(raw);
    return Number.isFinite(n) ? n : null;
  } catch {
    return null;
  }
}

function writeStored(axis: Axis, value: number | null) {
  try {
    if (value === null) window.localStorage.removeItem(storageKey(axis));
    else window.localStorage.setItem(storageKey(axis), String(value));
  } catch {
    // Armazenamento indisponível: o tamanho vale só para esta sessão.
  }
}

// Snapshot como string para ser estável entre leituras (useSyncExternalStore compara por ===).
function subscribe(onChange: () => void) {
  const mq = window.matchMedia(DESKTOP);
  mq.addEventListener("change", onChange);
  window.addEventListener("resize", onChange);
  return () => {
    mq.removeEventListener("change", onChange);
    window.removeEventListener("resize", onChange);
  };
}
const getSnapshot = () =>
  `${window.matchMedia(DESKTOP).matches ? "x" : "y"}|${window.innerWidth}|${window.innerHeight}`;
const getServerSnapshot = () => null;

function initialSizes(): Partial<Record<Axis, number>> {
  if (typeof window === "undefined") return {};
  return { x: readStored("x") ?? undefined, y: readStored("y") ?? undefined };
}

/**
 * Tamanho do painel lateral: largura no desktop, altura no celular.
 * Retorna `null` no SSR e na hidratação, para usar o tamanho padrão do CSS.
 */
export function usePanelSize() {
  const snap = useSyncExternalStore(subscribe, getSnapshot, getServerSnapshot);
  const [sizes, setSizes] = useState(initialSizes);

  const viewport = useMemo(() => {
    if (!snap) return null;
    const [a, w, h] = snap.split("|");
    return { axis: a as Axis, vw: Number(w), vh: Number(h) };
  }, [snap]);

  const axis = viewport?.axis ?? null;

  const set = useCallback(
    (value: number) => {
      if (!axis) return;
      setSizes((s) => ({ ...s, [axis]: value }));
      writeStored(axis, value);
    },
    [axis],
  );

  const reset = useCallback(() => {
    if (!axis) return;
    setSizes((s) => ({ ...s, [axis]: undefined }));
    writeStored(axis, null);
  }, [axis]);

  if (!viewport) return null;

  const { vw, vh } = viewport;
  const min = MIN[viewport.axis];
  const max = maxFor(viewport.axis, vw, vh);
  const raw = sizes[viewport.axis] ?? DEFAULTS[viewport.axis](vw, vh);
  const value = Math.min(max, Math.max(min, raw));

  return { axis: viewport.axis, value, min, max, set, reset };
}
