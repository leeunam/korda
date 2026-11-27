export type Lacuna = {
  id?: string; question?: string; pergunta?: string; motivo?: string; mensagem?: string; detail?: string;
  key?: string; topic?: string; rule_key?: string; campo?: string; state?: string; blocking?: boolean;
};
export type Fonte = {
  revision: number; context_id: string; sha256: string; estado: string;
  pendencias?: Lacuna[]; lacunas?: Lacuna[]; regras?: Record<string, Regra>;
};
export type Regra = { value?: unknown; status?: string; state?: string; evidence_ids?: string[]; confirmed_by?: { role: string } | null };
export type Plano = {
  plan_version: string; state: string; context_id: string; context_revision: number; context_sha256: string;
  destination: string; cost_estimate_brl_cents: number | null; ingestion_level: string;
  metrics: Record<string, { unit?: string; formula?: string; state?: string }>;
  rules: Record<string, Regra>; gaps: Lacuna[];
};
export type Execucao = {
  run_id: string; state: string; plan_version: string; destination: string;
  kpis: Record<string, number | null> | null;
  avaliacao: { aprovado: boolean; classe: string; divergencias: number; comparados?: Record<string, number> } | null;
  arquivos: string[];
};
export type Projeto = { project_id: string; source: Fonte | null; plan: Plano | null; run: Execucao | null };

export const nomeMetrica: Record<string, string> = {
  custo_frete_por_entrega: "Custo de frete por entrega", otif_pct: "OTIF", ocupacao_pct: "Ocupação dos veículos",
};
const estados: Record<string, string> = {
  pronto: "Pronta para planejamento", pendente: "Aguardando informações", rascunho: "Rascunho",
  aguardando_aprovacao: "Aguardando aprovação do plano", plano_aprovado: "Plano aprovado",
  plano_rejeitado: "Plano rejeitado", enfileirada: "Aguardando o worker", executando: "Em execução", falhou: "Execução interrompida",
  aguardando_aprovacao_entrega: "Aguardando aprovação da entrega", entrega_autorizada: "Entrega autorizada",
  entrega_rejeitada: "Entrega rejeitada", promovida: "Entrega promovida", invalidada: "Versão substituída",
};

export function legivel(valor: string) {
  return (estados[valor] || nomeMetrica[valor] || valor.replaceAll("_", " "));
}

export function caminhoProjeto(id: string) {
  return "/api/operador/projetos/" + encodeURIComponent(id);
}

export async function consultar<T>(url: string, comando?: Record<string, unknown>, sinal?: AbortSignal): Promise<T> {
  const resposta = await fetch(url, {
    method: comando ? "POST" : "GET", cache: "no-store", signal: sinal,
    ...(comando ? { headers: { "Content-Type": "application/json" }, body: JSON.stringify(comando) } : {}),
  });
  const corpo = await resposta.json().catch(() => null);
  if (!resposta.ok || !corpo) throw new Error(typeof corpo?.error === "string" ? corpo.error :
    "O painel não conseguiu consultar o serviço local. Atualize o projeto para conferir o estado.");
  return corpo as T;
}
