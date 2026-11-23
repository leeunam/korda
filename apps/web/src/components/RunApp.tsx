"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import seed from "@/data/seed-run.json";
import { deriveState } from "@/lib/derive";
import type { RunEvent, StepId } from "@/lib/events";
import { createPlayer, type Mode, type Player, type PlayerStatus, type Speed } from "@/lib/player";
import { createMemoryStore, useRunEvents } from "@/lib/store";
import { InspectPanel } from "./InspectPanel";
import { RunGraph } from "./RunGraph";
import { RunControls } from "./RunControls";
import { ResizeHandle } from "./ResizeHandle";
import { usePanelSize } from "@/lib/usePanelSize";

const source = seed.events as RunEvent[];

export function RunApp() {
  const [store] = useState(createMemoryStore);
  const [mode, setMode] = useState<Mode>("simulation");
  const [speed, setSpeed] = useState<Speed>(1);
  const playerRef = useRef<Player | null>(null);
  const speedRef = useRef<Speed>(1);
  const [status, setStatus] = useState<PlayerStatus>("idle");
  const [selected, setSelected] = useState<StepId | null>(null);

  const panel = usePanelSize();
  const events = useRunEvents(store);
  const view = useMemo(() => deriveState(events), [events]);

  // Um player por modo. Trocar de modo descarta o anterior (timers e eventos).
  useEffect(() => {
    const p = createPlayer({ mode, source, store });
    const off = p.onStatus(setStatus);
    playerRef.current = p;
    p.setSpeed(speedRef.current);
    p.play();
    return () => {
      off();
      p.dispose();
      playerRef.current = null;
    };
  }, [mode, store]);

  const changeSpeed = (s: Speed) => {
    speedRef.current = s;
    setSpeed(s);
    playerRef.current?.setSpeed(s);
  };

  return (
    <div className="flex h-dvh flex-col bg-page p-2 md:flex-row md:p-3">
      <main
        className="logo-fade relative min-h-0 flex-1 overflow-hidden rounded-[16px] bg-page shadow-card"
        aria-label="Run graph"
      >
        {/* eslint-disable-next-line @next/next/no-img-element */}
        <img
          src="/korda-wordmark-white.svg"
          alt="Korda"
          className="pointer-events-none absolute top-6 left-6 z-10 h-5 w-auto select-none"
        />
        <RunGraph view={view} selected={selected} onSelect={setSelected} />
      </main>
      {panel ? (
        <ResizeHandle
          axis={panel.axis}
          value={panel.value}
          min={panel.min}
          max={panel.max}
          onChange={panel.set}
          onReset={panel.reset}
          controls="run-sidebar"
          label="Resize sidebar"
        />
      ) : (
        <div aria-hidden className="h-2 shrink-0 md:w-3" />
      )}
      {/* Coluna lateral: controles e inspetor são cartões separados com a mesma largura. */}
      <div
        id="run-sidebar"
        style={panel?.axis === "x" ? { width: panel.value } : undefined}
        className={`flex min-h-0 shrink-0 flex-col gap-2 md:gap-3 ${panel ? "" : "md:w-[340px]"}`}
      >
        <section aria-label="Run controls" className="shrink-0 rounded-[16px] bg-canvas shadow-card">
          <RunControls
            mode={mode}
            onMode={setMode}
            status={status}
            speed={speed}
            onSpeed={changeSpeed}
            onPlay={() => playerRef.current?.play()}
            onPause={() => playerRef.current?.pause()}
            onRestart={() => playerRef.current?.restart()}
          />
        </section>
        <aside
          aria-label="Inspector"
          style={panel?.axis === "y" ? { height: panel.value } : undefined}
          className={`flex min-h-0 flex-col overflow-hidden rounded-[16px] bg-canvas shadow-card md:flex-1 ${
            panel ? "" : "max-h-[50vh] md:max-h-none"
          }`}
        >
          <div className="min-h-0 flex-1 overflow-y-auto">
            <InspectPanel
              view={view}
              events={events}
              selected={selected}
              mode={mode}
              onGrant={(step) => playerRef.current?.grantApproval(step)}
              onClose={() => setSelected(null)}
            />
          </div>
        </aside>
      </div>
    </div>
  );
}
