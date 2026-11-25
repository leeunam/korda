import { Position, type NodeProps } from "@xyflow/react";
import { NodeCard, NodeHandle, NodeHead } from "./StateBadge";
import type { PillNodeType } from "./types";

export function PillNode({ data, selected }: NodeProps<PillNodeType>) {
  const input = data.side === "input";
  const hue = input ? "var(--color-kind-input)" : "var(--color-kind-output)";
  return (
    <NodeCard state={data.state} selected={!!selected} kind={input ? "Input" : "Output"} width={260}>
      {input ? null : <NodeHandle lit={!!selected} type="target" position={Position.Top} />}
      <NodeHead icon={data.icon} hue={hue} title={data.label} subtitle={data.caption} />
      {input ? <NodeHandle lit={!!selected} type="source" position={Position.Bottom} /> : null}
    </NodeCard>
  );
}
