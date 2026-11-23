import { ShieldCheckIcon } from "@heroicons/react/24/outline";
import { Handle, Position, type NodeProps } from "@xyflow/react";
import { StateBadge, frameClass, titleClass } from "./StateBadge";
import type { GateNodeType } from "./types";

const handleCls = "!h-3 !w-3 !border-2 !border-paper !bg-ink-900";

export function GateNode({ data, selected }: NodeProps<GateNodeType>) {
  return (
    <div className={`w-[176px] rounded-[8px] bg-paper px-3 py-3 ${frameClass(data.state, !!selected)}`}>
      <Handle type="target" position={Position.Left} className={handleCls} />
      <div className="flex items-center gap-2">
        <ShieldCheckIcon className="h-5 w-5 shrink-0 text-ink-900" strokeWidth={1.5} aria-hidden />
        <h3 className={`text-[14px] font-bold tracking-[-0.02em] ${titleClass(data.state)}`}>{data.title}</h3>
      </div>
      <p className="mt-1 text-[11px] text-ink-500">{data.subtitle}</p>
      <div className="mt-2">
        <StateBadge state={data.state} gate={data.gate} />
      </div>
      <Handle type="source" position={Position.Right} className={handleCls} />
    </div>
  );
}
