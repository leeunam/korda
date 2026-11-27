"""ExecutorChat: o agente que constrói o pipeline a partir do plano e corrige falhas.

`construir(documento_base)` escreve os modelos bronze/prata/ouro a partir do
plano aprovado. Chamado como `executor(falha, tentativa)`, é o Corretor do
ciclo de até 3 correções do worker. As duas fases dividem o orçamento da
execução: a construção usa até 60%; cada correção, o restante dividido pelas
tentativas que faltam. Sempre com 10% de folga, porque o custo é estimado.
"""

from __future__ import annotations

import time

from .cliente_chat import ClienteChat, ClienteComOrcamento
from .config import ConfigHarness
from .contexto import SISTEMA, SISTEMA_CONSTRUCAO, montar_prompt, montar_prompt_construcao
from .politica import STEP
from .sessao_chat import executar_sessao
from .tipos import FerramentasAgente, ResultadoTentativa, SaidaSessao, usd_para_centavos

FOLGA = 0.9
FRACAO_CONSTRUCAO = 0.6
TENTATIVA_CONSTRUCAO = 0


class ExecutorChat:
    nome = "chat"

    def __init__(self, cfg: ConfigHarness, cliente: ClienteChat, ferramentas: FerramentasAgente, plano_publico: dict,
                 perfis: dict, limite: int, emissor, medidor, *, custo_anterior_centavos: int = 0,
                 orcamento_total_usd: float | None = None, verificar_ativa=None, esquema_bronze: str | None = None):
        self.cfg = cfg
        self.cliente = cliente
        self.ferramentas = ferramentas
        self.plano_publico = plano_publico
        self.perfis = perfis
        self.limite = limite
        self.emissor = emissor
        self.medidor = medidor
        self.verificar_ativa = verificar_ativa
        self.esquema_bronze = esquema_bronze
        self.documento_base = None
        self.gasto_usd = 0.0
        self.custo_total_centavos = custo_anterior_centavos
        self.orcamento_total_usd = cfg.orcamento_execucao_usd if orcamento_total_usd is None else orcamento_total_usd
        self.ultima_saida: SaidaSessao | None = None

    @property
    def restante_usd(self) -> float:
        return self.cfg.orcamento_execucao_usd - self.gasto_usd

    def descontar_documento_base(self, custo_usd: float | None) -> None:
        """O documento-base (chamada do worker) sai do mesmo orçamento da execução."""
        if custo_usd:
            self.gasto_usd += custo_usd
            self.custo_total_centavos += usd_para_centavos(custo_usd, self.cfg.taxa_usd_brl) or 0

    def teto_construcao(self) -> float:
        return min(self.restante_usd, self.cfg.orcamento_execucao_usd * FRACAO_CONSTRUCAO) * FOLGA

    def teto_correcao(self, tentativa: int) -> float:
        faltam = max(1, self.limite - tentativa + 1)
        return self.restante_usd / faltam * FOLGA

    def construir(self, documento_base: str | None) -> dict:
        if self.emissor is not None:
            self.emissor.emit_event(STEP, "build_started", "Agente iniciou a construção do pipeline a partir do plano",
                                    1, plan_version=self.plano_publico.get("plan_version"))
        self.documento_base = documento_base
        prompt = montar_prompt_construcao(self.plano_publico, self.perfis, documento_base, self.esquema_bronze)
        return self._sessao(SISTEMA_CONSTRUCAO, prompt, TENTATIVA_CONSTRUCAO, self.teto_construcao(),
                            self.cfg.max_turnos_construcao)

    def __call__(self, falha: dict, tentativa: int) -> dict:
        prompt = montar_prompt(falha, tentativa, self.limite, self.plano_publico, self.perfis, self.documento_base,
                               self.esquema_bronze)
        return self._sessao(SISTEMA, prompt, tentativa, self.teto_correcao(tentativa), self.cfg.max_turnos_tentativa)

    def _sessao(self, sistema: str, prompt: str, tentativa: int, teto: float, max_turnos: int) -> dict:
        if self.restante_usd <= 0 or teto <= 0:
            return {"ok": False, "erro": "orçamento de LLM esgotado", "custo_centavos": 0}
        if isinstance(self.cliente, ClienteComOrcamento):
            self.cliente.limitar_sessao(teto)
        inicio = time.monotonic()
        saida, escritas = executar_sessao(
            self.cliente, sistema, prompt, self.ferramentas, self.plano_publico["editable_models"],
            emissor=self.emissor, tentativa=max(1, tentativa), max_turnos=max_turnos, teto_usd=teto,
            precos=(self.cfg.preco_entrada_usd_mtok, self.cfg.preco_saida_usd_mtok), verificar_ativa=self.verificar_ativa)
        self.ultima_saida = saida
        duracao = round(time.monotonic() - inicio, 3)
        # Custo desconhecido consome o teto inteiro, por precaução.
        self.gasto_usd += saida.total_cost_usd if saida.total_cost_usd is not None else teto
        custo_centavos = usd_para_centavos(saida.total_cost_usd, self.cfg.taxa_usd_brl)
        self.custo_total_centavos += custo_centavos or 0
        excedeu = saida.total_cost_usd is not None and saida.total_cost_usd > teto
        ok = bool(escritas) and not excedeu and saida.total_cost_usd is not None and saida.subtype != "error_during_execution"
        if self.medidor is not None:
            self.medidor.registrar(ResultadoTentativa(
                tentativa=tentativa, corretor=self.nome, ok=ok, motivo_parada=saida.subtype, turnos=saida.num_turns,
                tokens_entrada=saida.usage.get("input_tokens", 0), tokens_saida=saida.usage.get("output_tokens", 0),
                tokens_cache_leitura=0, custo_usd=saida.total_cost_usd, custo_centavos=custo_centavos,
                duracao_s=duracao, arquivos_escritos=list(escritas)))
        if self.emissor is not None:
            fase = "construção" if tentativa == TENTATIVA_CONSTRUCAO else f"correção {tentativa}"
            self.emissor.emit_event(
                STEP, "agent_finished", f"Agente terminou a {fase} ({saida.subtype})", max(1, tentativa),
                fase="construcao" if tentativa == TENTATIVA_CONSTRUCAO else "correcao", subtype=saida.subtype,
                turnos=saida.num_turns, arquivos=list(escritas), custo_usd=saida.total_cost_usd,
                custo_centavos=custo_centavos, custo_total_centavos=self.custo_total_centavos,
                orcamento_centavos=usd_para_centavos(self.orcamento_total_usd, self.cfg.taxa_usd_brl),
                custo_estimado=True, tokens_entrada=saida.usage.get("input_tokens", 0),
                tokens_saida=saida.usage.get("output_tokens", 0), ferramentas=list(saida.ferramentas_sessao),
                tokens_por_turno=saida.tokens_por_turno, **({"erro_api": saida.erro} if saida.erro else {}))
        if ok:
            return {"ok": True, "custo_centavos": custo_centavos}
        if excedeu:
            return {"ok": False, "erro": "a sessão excedeu o orçamento autorizado", "custo_centavos": custo_centavos}
        motivo = "terminou com erro" if escritas else "terminou sem alteração"
        detalhe = f": {saida.erro}" if saida.erro else ""
        return {"ok": False, "erro": f"agente {motivo} ({saida.subtype}){detalhe}", "custo_centavos": custo_centavos}
