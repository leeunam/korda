import { ArrowPathIcon, PauseIcon, PlayIcon } from "@heroicons/react/24/outline";
import type { Mode, PlayerStatus, Speed } from "@/lib/player";

const STATUS_TEXT: Record<PlayerStatus, string> = {
  idle: "parado",
  playing: "reproduzindo",
  paused: "pausado",
  waiting_human: "aguardando aprovação humana",
  finished: "fim da execução",
};

export const MODE_LABEL: Record<Mode, string> = {
  simulation: "SIMULAÇÃO · dados sintéticos",
  replay: "REPLAY · gravado",
};

const btn =
  "inline-flex h-8 items-center justify-center rounded-[6px] border border-ink-900 px-2 text-[12px] font-semibold text-ink-900 hover:bg-ink-100 focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-ink-900 disabled:border-ink-100 disabled:text-ink-500 disabled:hover:bg-transparent";

export function RunHeader(props: {
  runId: string;
  client: string;
  mode: Mode;
  onMode: (m: Mode) => void;
  status: PlayerStatus;
  speed: Speed;
  onSpeed: (s: Speed) => void;
  onPlay: () => void;
  onPause: () => void;
  onRestart: () => void;
}) {
  const { mode, status, speed } = props;
  const playing = status === "playing";
  return (
    <header className="flex flex-wrap items-center gap-x-6 gap-y-3 border-b border-ink-100 px-4 py-3">
      <div className="flex min-w-0 items-center gap-3">
        {/* eslint-disable-next-line @next/next/no-img-element */}
        <img src="/korda-wordmark-black.svg" alt="Korda" className="h-6 w-auto" />
        <div className="min-w-0 leading-tight">
          <p className="truncate font-mono text-[12px] text-ink-900">{props.runId}</p>
          <p className="truncate text-[12px] text-ink-500">{props.client}</p>
        </div>
      </div>

      <p
        className="rounded-[4px] border-2 border-ink-900 px-2 py-1 text-[11px] font-bold uppercase tracking-[0.08em]"
        role="status"
      >
        {MODE_LABEL[mode]}
      </p>

      <div className="ml-auto flex flex-wrap items-center gap-2">
        <div role="radiogroup" aria-label="Modo" className="flex rounded-[6px] border border-ink-900 p-0.5">
          {(["simulation", "replay"] as const).map((m) => (
            <button
              key={m}
              role="radio"
              aria-checked={mode === m}
              onClick={() => props.onMode(m)}
              className={`h-7 rounded-[4px] px-2 text-[12px] font-semibold focus-visible:outline-2 focus-visible:outline-ink-900 ${
                mode === m ? "bg-ink-900 text-paper" : "text-ink-900 hover:bg-ink-100"
              }`}
            >
              {m === "simulation" ? "Simulação" : "Replay"}
            </button>
          ))}
        </div>

        <button
          className={`${btn} w-8`}
          onClick={playing ? props.onPause : props.onPlay}
          disabled={status === "finished" || status === "waiting_human"}
          aria-label={playing ? "Pausar" : "Reproduzir"}
          title={playing ? "Pausar" : "Reproduzir"}
        >
          {playing ? <PauseIcon className="h-4 w-4" strokeWidth={1.5} /> : <PlayIcon className="h-4 w-4" strokeWidth={1.5} />}
        </button>
        <button className={`${btn} w-8`} onClick={props.onRestart} aria-label="Reiniciar" title="Reiniciar">
          <ArrowPathIcon className="h-4 w-4" strokeWidth={1.5} />
        </button>

        <div role="radiogroup" aria-label="Velocidade" className="flex gap-1">
          {([1, 2, 4] as const).map((s) => (
            <button
              key={s}
              role="radio"
              aria-checked={speed === s}
              onClick={() => props.onSpeed(s)}
              className={`${btn} w-9 ${speed === s ? "!bg-ink-900 !text-paper" : ""}`}
            >
              {s}×
            </button>
          ))}
        </div>

        <p className="w-full text-right text-[12px] text-ink-500 sm:w-auto" aria-live="polite">
          {STATUS_TEXT[status]}
        </p>
      </div>
    </header>
  );
}
