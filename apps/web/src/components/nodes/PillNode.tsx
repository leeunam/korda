import { Handle, Position, type NodeProps } from "@xyflow/react";
import { RunningCursor, StateBadge, frameClass, titleClass } from "./StateBadge";
import type { PillNodeType } from "./types";

const handleCls = "!h-3 !w-3 !border-2 !border-paper !bg-ink-900";

export function PillNode({ data, selected }: NodeProps<PillNodeType>) {
  const { state, icon: Icon } = data;
  return (
    <div className={`flex items-center gap-2 rounded-full bg-paper py-2 pl-3 pr-4 ${frameClass(state, !!selected)}`}>
      {data.side === "output" ? <Handle type="target" position={Position.Left} className={handleCls} /> : null}
      <Icon className="h-5 w-5 shrink-0 text-ink-900" strokeWidth={1.5} aria-hidden />
      <div>
        <p className={`text-[14px] font-bold tracking-[-0.02em] ${titleClass(state)}`}>
          {data.label}
          <RunningCursor state={state} />
        </p>
        <StateBadge state={state} />
      </div>
      {data.side === "input" ? <Handle type="source" position={Position.Right} className={handleCls} /> : null}
    </div>
  );
}
