"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import seed from "@/data/seed-run.json";
import { deriveState } from "@/lib/derive";
import type { RunEvent, StepId } from "@/lib/events";
import { createPlayer, type Mode, type Player, type PlayerStatus, type Speed } from "@/lib/player";
import { createMemoryStore, useRunEvents } from "@/lib/store";
import { InspectPanel } from "./InspectPanel";
import { RunGraph } from "./RunGraph";
import { RunHeader } from "./RunHeader";

const source = seed.events as RunEvent[];

export function RunApp() {
  const [store] = useState(createMemoryStore);
  const [mode, setMode] = useState<Mode>("simulation");
  const [speed, setSpeed] = useState<Speed>(1);
  const playerRef = useRef<Player | null>(null);
  const speedRef = useRef<Speed>(1);
  const [status, setStatus] = useState<PlayerStatus>("idle");
  const [selected, setSelected] = useState<StepId | null>(null);

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
    <div className="flex h-dvh flex-col">
      <RunHeader
        runId={seed.run_id}
        client={seed.client}
        mode={mode}
        onMode={setMode}
        status={status}
        speed={speed}
        onSpeed={changeSpeed}
        onPlay={() => playerRef.current?.play()}
        onPause={() => playerRef.current?.pause()}
        onRestart={() => playerRef.current?.restart()}
      />
      <div className="flex min-h-0 flex-1 flex-col md:flex-row">
        <main className="min-h-0 flex-1" aria-label="Grafo da execução">
          <RunGraph view={view} selected={selected} onSelect={setSelected} />
        </main>
        <aside
          aria-label="Inspeção"
          className="max-h-[45vh] shrink-0 overflow-y-auto border-t border-ink-100 md:max-h-none md:w-[380px] md:border-l md:border-t-0"
        >
          <InspectPanel
            view={view}
            events={events}
            selected={selected}
            mode={mode}
            onGrant={(step) => playerRef.current?.grantApproval(step)}
            onClose={() => setSelected(null)}
          />
        </aside>
      </div>
    </div>
  );
}
