import { Handle, Position, type NodeProps } from "@xyflow/react";
import { RunningCursor, StateBadge, frameClass, titleClass } from "./StateBadge";
import type { ToolNodeType } from "./types";

export function ToolNode({ data, selected }: NodeProps<ToolNodeType>) {
  const { state, icon: Icon } = data;
  return (
    <div className={`w-[248px] overflow-hidden rounded-[8px] bg-paper ${frameClass(state, !!selected)}`}>
      <div className="flex items-center gap-2 px-3 pt-3">
        <Icon className="h-5 w-5 shrink-0 text-ink-900" strokeWidth={1.5} aria-hidden />
        <h3 className={`font-mono text-[14px] font-semibold ${titleClass(state)}`}>
          {data.title}
          <RunningCursor state={state} />
        </h3>
      </div>
      <div className="px-3 pt-1.5">
        <StateBadge state={state} />
      </div>
      <p className="px-3 pt-2 text-[12px] leading-snug text-ink-500">{data.description}</p>
      <dl className="space-y-1.5 px-3 py-3">
        {data.fields.map((f) => (
          <div key={f.label}>
            <dt className="text-[10px] font-semibold uppercase tracking-[0.06em] text-ink-500">{f.label}</dt>
            <dd className="mt-0.5 rounded-[4px] border border-ink-100 px-2 py-1 font-mono text-[11px] text-ink-900">
              {f.value}
            </dd>
          </div>
        ))}
      </dl>
      <div className="relative flex items-center justify-between bg-ink-900 px-3 py-2 text-[12px] text-paper">
        <span>{data.footer}</span>
        <span className="text-ink-100">saída</span>
        <Handle type="source" position={Position.Right} className="!h-3 !w-3 !border-2 !border-paper !bg-ink-900" />
      </div>
    </div>
  );
}
