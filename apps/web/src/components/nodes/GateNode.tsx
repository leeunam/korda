import { ShieldCheckIcon } from "@heroicons/react/24/outline";
import { Position, type NodeProps } from "@xyflow/react";
import { NodeCard, NodeHandle, NodeHead } from "./StateBadge";
import type { GateNodeType } from "./types";

const HUE = "var(--color-kind-gate)";

export function GateNode({ data, selected }: NodeProps<GateNodeType>) {
  return (
    <NodeCard state={data.state} gate={data.gate} selected={!!selected} kind="Approval" width={260}>
      <NodeHandle lit={!!selected} type="target" position={Position.Top} />
      <NodeHead icon={ShieldCheckIcon} hue={HUE} title={data.title} subtitle={data.subtitle} />
      <NodeHandle lit={!!selected} type="source" position={Position.Bottom} />
    </NodeCard>
  );
}
