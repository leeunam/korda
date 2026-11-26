import { Position, type NodeProps } from "@xyflow/react";
import { NodeCard, NodeHandle, NodeFooter, NodeHead } from "./StateBadge";
import type { ToolNodeType } from "./types";

const HUE = "var(--color-kind-tool)";

/** Resumo da ferramenta. Comando e permissões ficam no painel de inspeção. */
export function ToolNode({ data, selected }: NodeProps<ToolNodeType>) {
  return (
    <NodeCard state={data.state} selected={!!selected} kind="Tool" width={260}>
      <NodeHead icon={data.icon} hue={HUE} title={data.title} subtitle={data.description} mono />
      <NodeFooter>
        {data.footer}
        <NodeHandle lit={!!selected} type="source" position={Position.Right} />
      </NodeFooter>
    </NodeCard>
  );
}
