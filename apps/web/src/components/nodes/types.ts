import type { ComponentType, SVGProps } from "react";
import type { Node } from "@xyflow/react";
import type { GateState, NodeState } from "@/lib/derive";

export type Icon = ComponentType<SVGProps<SVGSVGElement>>;
export type Field = { label: string; value: string };

export type ToolData = {
  state: NodeState;
  icon: Icon;
  title: string;
  description: string;
  footer: string;
};
export type AgentData = {
  state: NodeState;
  title: string;
  subtitle: string;
  output: string;
};
export type GateData = { state: NodeState; gate: GateState; title: string; subtitle: string };
export type PillData = { state: NodeState; icon: Icon; label: string; caption?: string; side: "input" | "output" };

export type ToolNodeType = Node<ToolData, "tool">;
export type AgentNodeType = Node<AgentData, "agent">;
export type GateNodeType = Node<GateData, "gate">;
export type PillNodeType = Node<PillData, "pill">;
export type KordaNode = ToolNodeType | AgentNodeType | GateNodeType | PillNodeType;
