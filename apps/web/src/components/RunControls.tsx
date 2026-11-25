import { ArrowPathIcon, PauseIcon, PlayIcon } from "@heroicons/react/24/outline";
import { CheckCircleIcon, HandRaisedIcon } from "@heroicons/react/20/solid";
import type { Mode, PlayerStatus, Speed } from "@/lib/player";
import { LoadingState } from "./LoadingState";

const STATUS_TEXT: Record<PlayerStatus, string> = {
  idle: "Stopped",
  playing: "Running",
  paused: "Paused",
  waiting_human: "Waiting for human approval",
  finished: "Run finished",
};

const STATUS_DOT: Record<PlayerStatus, string> = {
  idle: "border border-faint",
  playing: "", // substituído pelo LoadingState
  paused: "bg-faint",
  waiting_human: "bg-status-waiting",
  finished: "bg-status-done",
};

/** Estados que pedem atenção: caixa tingida com ícone em vez do ponto. */
const STATUS_CALLOUT: Partial<
  Record<PlayerStatus, { Icon: typeof HandRaisedIcon; box: string; icon: string }>
> = {
  waiting_human: { Icon: HandRaisedIcon, box: "bg-status-waiting/12 ring-status-waiting/40", icon: "text-status-waiting" },
  finished: { Icon: CheckCircleIcon, box: "bg-status-done/12 ring-status-done/40", icon: "text-status-done" },
};

/** Botão de ícone dentro de um grupo em `field`. */
const iconBtn =
  "inline-flex size-7 cursor-pointer items-center justify-center rounded-[7px] text-muted transition-colors duration-100 hover:bg-canvas hover:text-ink focus-visible:outline-2 focus-visible:outline-accent disabled:cursor-default disabled:text-faint disabled:hover:bg-transparent";

/** Controle segmentado: trilho em `field`, item ativo em superfície. */
function Segmented<T extends string | number>({
  label,
  value,
  options,
  onChange,
  bare = false,
}: {
  label: string;
  /** Sem trilho próprio, para ficar dentro de outro grupo. */
  bare?: boolean;
  value: T;
  options: { value: T; label: string }[];
  onChange: (v: T) => void;
}) {
  return (
    <div role="radiogroup" aria-label={label} className={bare ? "flex" : "flex rounded-[9px] bg-field p-0.5"}>
      {options.map((o) => {
        const on = o.value === value;
        return (
          <button
            key={String(o.value)}
            role="radio"
            aria-checked={on}
            onClick={() => onChange(o.value)}
            className={`h-7 cursor-pointer rounded-[7px] px-2.5 text-[12.5px] font-medium transition-colors duration-100 focus-visible:outline-2 focus-visible:outline-accent ${
              on ? "bg-canvas text-ink shadow-btn" : "text-muted hover:text-ink"
            }`}
          >
            {o.label}
          </button>
        );
      })}
    </div>
  );
}

/** Controles da execução, em cartão flutuante acima do inspetor: modo, reprodução, velocidade e estado. */
export function RunControls(props: {
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
  const waiting = status === "waiting_human";
  const callout = STATUS_CALLOUT[status];
  return (
    <div className="space-y-2.5 px-4 py-3">
      <div className="flex items-center justify-between gap-2">
        <Segmented
          label="Mode"
          value={mode}
          onChange={props.onMode}
          options={[
            { value: "simulation", label: "Simulation" },
            { value: "replay", label: "Replay" },
          ]}
        />

        <div className="flex items-center gap-0.5 rounded-[9px] bg-field p-0.5" role="group" aria-label="Playback">
          <button
            className={iconBtn}
            onClick={playing ? props.onPause : props.onPlay}
            disabled={status === "finished" || waiting}
            aria-label={playing ? "Pause" : "Play"}
            title={playing ? "Pause" : "Play"}
          >
            {playing ? <PauseIcon className="size-4" strokeWidth={1.8} /> : <PlayIcon className="size-4" strokeWidth={1.8} />}
          </button>
          <button className={iconBtn} onClick={props.onRestart} aria-label="Restart" title="Restart">
            <ArrowPathIcon className="size-4" strokeWidth={1.8} />
          </button>
          <span className="mx-0.5 h-4 w-px bg-line-strong" aria-hidden />
          <Segmented
            label="Speed"
            value={speed}
            onChange={props.onSpeed}
            bare
            options={[1, 4].map((s) => ({ value: s as Speed, label: `${s}×` }))}
          />
        </div>
      </div>

      <p
        role="status"
        aria-live="polite"
        className={
          callout || playing
            ? `flex items-center gap-2 rounded-[9px] px-2.5 py-2 text-[12.5px] font-semibold text-ink ring-1 ring-inset ${playing ? "bg-accent/8 ring-accent/30" : callout?.box}`
            : "flex items-center gap-1.5 text-[12px] text-muted"
        }
      >
        {playing ? (
          <LoadingState label={STATUS_TEXT.playing} variant="Orbit" />
        ) : (
          <>
            {callout ? (
              <callout.Icon className={`size-4 shrink-0 ${callout.icon}`} aria-hidden />
            ) : (
              <span className={`size-1.5 shrink-0 rounded-full ${STATUS_DOT[status]}`} aria-hidden />
            )}
            {STATUS_TEXT[status]}
          </>
        )}
      </p>
    </div>
  );
}
