"use client";

import "@xyflow/react/dist/style.css";
import {
  Background,
  Controls,
  ReactFlow,
  useNodes,
  useReactFlow,
  useViewportStore,
  type NodeTypes,
} from "@xyflow/react";
import { useEffect, useMemo, useRef, type RefObject } from "react";
import type { RunView } from "@/lib/derive";
import { isStep, type StepId } from "@/lib/events";
import { buildEdges, buildNodes } from "@/lib/graph";
import { AgentNode } from "./nodes/AgentNode";
import { GateNode } from "./nodes/GateNode";
import { PillNode } from "./nodes/PillNode";
import { ToolNode } from "./nodes/ToolNode";

const nodeTypes: NodeTypes = { tool: ToolNode, agent: AgentNode, gate: GateNode, pill: PillNode } as NodeTypes;

/** Mesmo enquadramento na carga e no botão de ajuste. Número puro seria lido como px. */
const FIT_VIEW = { padding: "10%" } as const;

/**
 * O `fitView` inicial roda uma vez, antes do layout assentar (painel restaurado do
 * localStorage, nós crescendo durante a execução). Reenquadra a cada mudança de tamanho
 * do canvas ou dos nós, até o usuário mover/zoomar a vista manualmente.
 */
function AutoFit({ enabled }: { enabled: RefObject<boolean> }) {
  const { fitView } = useReactFlow();
  const width = useViewportStore((s) => s.width);
  const height = useViewportStore((s) => s.height);
  const sizes = useNodes()
    .map((n) => `${n.id}:${n.measured?.width ?? 0}x${n.measured?.height ?? 0}`)
    .join("|");

  useEffect(() => {
    if (enabled.current && width > 0 && height > 0) void fitView(FIT_VIEW);
  }, [enabled, fitView, width, height, sizes]);

  return null;
}

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
  const edges = useMemo(() => buildEdges(view, selected), [view, selected]);
  const autoFit = useRef(true);
  const stopAutoFit = () => {
    autoFit.current = false;
  };

  // Teclado: Enter ou Espaço num nó focado (Tab) seleciona o nó para inspeção.
  const onKeyDown = (e: React.KeyboardEvent<HTMLDivElement>) => {
    if (e.key !== "Enter" && e.key !== " ") return;
    const id = (e.target as HTMLElement).closest<HTMLElement>(".react-flow__node")?.dataset.id;
    if (id && isStep(id)) {
      e.preventDefault();
      onSelect(id);
    }
  };

  return (
    <div className="h-full w-full" onKeyDown={onKeyDown}>
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
        fitViewOptions={FIT_VIEW}
        minZoom={0.3}
        onMoveStart={(event) => {
          // Só gestos do usuário trazem evento; movimentos programáticos vêm com null.
          if (event) stopAutoFit();
        }}
      >
        <AutoFit enabled={autoFit} />
        <Background gap={22} size={1.25} color="var(--color-line-strong)" />
        <Controls
          showInteractive={false}
          fitViewOptions={FIT_VIEW}
          onZoomIn={stopAutoFit}
          onZoomOut={stopAutoFit}
          onFitView={() => {
            autoFit.current = true;
          }}
        />
      </ReactFlow>
    </div>
  );
}
