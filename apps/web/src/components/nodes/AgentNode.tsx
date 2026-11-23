import { CpuChipIcon } from "@heroicons/react/24/outline";
import { Handle, Position, type NodeProps } from "@xyflow/react";
import { RunningCursor, StateBadge, frameClass, titleClass } from "./StateBadge";
import type { AgentNodeType } from "./types";

const handleCls = "!h-3 !w-3 !border-2 !border-paper !bg-ink-900";

function InputRow({ id, label }: { id: string; label: string }) {
  return (
    <div className="relative flex items-center px-3 py-1.5 text-[12px] font-semibold text-ink-900">
      <Handle id={id} type="target" position={Position.Left} className={handleCls} />
      {label}
    </div>
  );
}

export function AgentNode({ data, selected }: NodeProps<AgentNodeType>) {
  const { state } = data;
  return (
    <div className={`w-[300px] overflow-hidden rounded-[8px] bg-paper ${frameClass(state, !!selected)}`}>
      <div className="flex items-center gap-2 px-3 pt-3">
        <CpuChipIcon className="h-5 w-5 shrink-0 text-ink-900" strokeWidth={1.5} aria-hidden />
        <div>
          <h3 className={`text-[15px] font-bold tracking-[-0.02em] ${titleClass(state)}`}>
            {data.title}
            <RunningCursor state={state} />
          </h3>
          <p className="text-[11px] text-ink-500">{data.subtitle}</p>
        </div>
      </div>
      <div className="px-3 pt-1.5">
        <StateBadge state={state} />
      </div>
      <dl className="space-y-1.5 px-3 pt-3">
        <div>
          <dt className="text-[10px] font-semibold uppercase tracking-[0.06em] text-ink-500">Modelo</dt>
          <dd className="mt-0.5 rounded-[4px] border border-ink-100 px-2 py-1 font-mono text-[11px]">{data.model}</dd>
        </div>
        <div>
          <dt className="text-[10px] font-semibold uppercase tracking-[0.06em] text-ink-500">Instruções</dt>
          <dd className="mt-0.5 rounded-[4px] border border-ink-100 px-2 py-1.5 text-[11px] leading-snug">
            {data.instructions}
          </dd>
        </div>
      </dl>
      <div className="mt-2 border-t border-ink-100 py-1">
        <InputRow id="plan" label="Plano" />
        <InputRow id="tools" label="Ferramentas" />
      </div>
      <div className="relative flex items-center justify-between bg-ink-900 px-3 py-2 text-[12px] text-paper">
        <span>{data.output}</span>
        <span className="text-ink-100">saída</span>
        <Handle id="models" type="source" position={Position.Right} className={handleCls} />
      </div>
    </div>
  );
}
