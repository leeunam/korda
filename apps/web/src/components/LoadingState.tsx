"use client";

import { useEffect, useState } from "react";

/*
 * Loading State (beautifului.dev): grade de pixels para trabalho longo, com rótulo
 * cintilante e cronômetro em algarismos tabulares. Com movimento reduzido a grade fica
 * no estado apagado; o cronômetro continua.
 *   Drive: células quadradas, frente em chevron para a direita (2 frentes em voo)
 *   Dots:  mesma frente, células redondas
 *   Orbit: um cometa contornando a grade
 */

const chevron = Array.from({ length: 9 }, (_, i) => {
  const r = Math.floor(i / 3),
    c = i % 3;
  return (c + Math.abs(r - 1)) * 90;
});

const ORBIT_ORDER = [0, 1, 2, 5, 8, 7, 6, 3];
const orbit = Array.from({ length: 9 }, (_, i) => {
  const k = ORBIT_ORDER.indexOf(i);
  return k === -1 ? null : k * 110;
});

export type LoaderVariant = "Drive" | "Dots" | "Orbit";

const PATTERNS: Record<LoaderVariant, { delays: (number | null)[]; dur: number; round: boolean }> = {
  Drive: { delays: chevron, dur: 650, round: false },
  Dots: { delays: chevron, dur: 650, round: true },
  Orbit: { delays: orbit, dur: 950, round: false },
};

function LoaderGrid({ delays, dur, round }: { delays: (number | null)[]; dur: number; round: boolean }) {
  return (
    <span aria-hidden className="grid shrink-0 grid-cols-[repeat(3,4px)] gap-[1.5px]">
      {delays.map((delay, index) => (
        <span
          key={index}
          className={`pixel-cell size-[4px] bg-ink ${round ? "rounded-full" : "rounded-[1px]"}`}
          style={{
            opacity: delay === null ? 0.07 : 0.15,
            animation: delay === null ? "none" : `pixel-on ${dur}ms ease-in-out ${delay}ms infinite`,
          }}
        />
      ))}
    </span>
  );
}

function useElapsed() {
  const [ds, setDs] = useState(0);
  useEffect(() => {
    const t = setInterval(() => setDs((d) => d + 1), 100);
    return () => clearInterval(t);
  }, []);
  const total = ds / 10;
  if (total < 60) return `${total.toFixed(1)}s`;
  return `${Math.floor(total / 60)}m ${(total % 60).toFixed(1)}s`;
}

export function LoadingState({ label = "Running", variant = "Drive" }: { label?: string; variant?: LoaderVariant }) {
  const elapsed = useElapsed();
  return (
    <span className="flex w-fit items-center gap-2">
      <LoaderGrid {...PATTERNS[variant]} />
      <span
        className="shimmer-text bg-clip-text text-transparent"
        style={{
          backgroundImage:
            "linear-gradient(90deg, var(--color-faint) 35%, var(--color-ink) 50%, var(--color-faint) 65%)",
          backgroundSize: "200% 100%",
        }}
      >
        {label}
      </span>
      <span aria-hidden className="font-mono text-[0.92em] font-normal text-faint tabular-nums">
        {elapsed}
      </span>
    </span>
  );
}
