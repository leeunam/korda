"use client";

// Provisório (passo 5 do plano): ?n=<k> mostra o estado após os k primeiros eventos do seed.
import { useSearchParams } from "next/navigation";
import { useState } from "react";
import seed from "@/data/seed-run.json";
import { deriveState } from "@/lib/derive";
import type { RunEvent, StepId } from "@/lib/events";
import { RunGraph } from "./RunGraph";

const events = seed.events as RunEvent[];

export function GraphPreview() {
  const params = useSearchParams();
  const n = Math.max(0, Math.min(events.length, Number(params.get("n") ?? events.length) || 0));
  const [selected, setSelected] = useState<StepId | null>(null);
  const view = deriveState(events.slice(0, n));
  return (
    <div className="flex h-dvh flex-col">
      <p className="border-b border-ink-100 px-4 py-2 text-[12px] text-ink-500">
        Prévia · {n} de {events.length} eventos · dados sintéticos
        {n > 0 ? ` · último: ${events[n - 1].type} (${events[n - 1].step})` : ""}
      </p>
      <div className="flex-1">
        <RunGraph view={view} selected={selected} onSelect={setSelected} />
      </div>
    </div>
  );
}
