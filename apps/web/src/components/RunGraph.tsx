"use client";

import "@xyflow/react/dist/style.css";
import { Background, Controls, ReactFlow, type NodeTypes } from "@xyflow/react";
import { useMemo } from "react";
import type { RunView } from "@/lib/derive";
import { isStep, type StepId } from "@/lib/events";
import { buildEdges, buildNodes } from "@/lib/graph";
import { AgentNode } from "./nodes/AgentNode";
import { GateNode } from "./nodes/GateNode";
import { PillNode } from "./nodes/PillNode";
import { ToolNode } from "./nodes/ToolNode";

const nodeTypes: NodeTypes = { tool: ToolNode, agent: AgentNode, gate: GateNode, pill: PillNode } as NodeTypes;

export function RunGraph({
  view,
  selected,
  onSelect,
}: {
  view: RunView;
  selected: StepId | null;
  onSelect: (step: StepId | null) => void;
}) {
  const nodes = useMemo(() => buildNodes(view, selected), [view, selected]);
  const edges = useMemo(() => buildEdges(view), [view]);

  return (
    <ReactFlow
      nodes={nodes}
      edges={edges}
      nodeTypes={nodeTypes}
      nodesDraggable={false}
      nodesConnectable={false}
      edgesFocusable={false}
      onNodeClick={(_, node) => onSelect(isStep(node.id) ? node.id : null)}
      onPaneClick={() => onSelect(null)}
      fitView
      fitViewOptions={{ padding: 0.15 }}
      minZoom={0.3}
    >
      <Background gap={24} size={1} color="#E5E5E5" />
      <Controls showInteractive={false} />
    </ReactFlow>
  );
}
