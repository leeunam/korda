import { CpuChipIcon } from "@heroicons/react/24/outline";
import { Position, type NodeProps } from "@xyflow/react";
import { NodeCard, NodeHandle, NodeFooter, NodeHead } from "./StateBadge";
import type { AgentNodeType } from "./types";

const HUE = "var(--color-kind-agent)";

/** Resumo do agente. Modelo e instruções ficam no painel de inspeção. */
export function AgentNode({ data, selected }: NodeProps<AgentNodeType>) {
  return (
    <NodeCard state={data.state} selected={!!selected} kind="Agent" width={280}>
      <NodeHandle lit={!!selected} id="plan" type="target" position={Position.Top} />
      <NodeHandle lit={!!selected} id="tools" type="target" position={Position.Left} />
      <NodeHead icon={CpuChipIcon} hue={HUE} title={data.title} subtitle={data.subtitle} />
      <NodeFooter>
        {data.output}
        <NodeHandle lit={!!selected} id="models" type="source" position={Position.Bottom} />
      </NodeFooter>
    </NodeCard>
  );
}
