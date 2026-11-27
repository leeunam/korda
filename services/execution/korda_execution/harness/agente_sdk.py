"""Corretor agente sobre o Claude Agent SDK. É o único arquivo que importa o SDK.

Trocar de harness (Messages API, Devin, OpenHands) significa escrever outro
corretor com a mesma assinatura; o resto do harness não muda.

O SDK roda o CLI do Claude Code no host (worker), onde estão o repositório e as
respostas esperadas. Por isso: sem ferramentas embutidas (`tools=[]` vira
`--tools ""`), lista explícita de embutidas proibidas, só as seis ferramentas
mcp__korda__* liberadas, modo `dontAsk`, hook que nega o resto, cwd numa pasta
vazia, sem configurações do disco, e a sessão é abortada se o init listar
qualquer ferramenta fora de mcp__korda__*. O SDK herda o ambiente do processo:
rode o worker com o ambiente mínimo.
"""

from __future__ import annotations

import asyncio
import math
import tempfile
import time
from collections.abc import Callable
from contextlib import aclosing
from dataclasses import dataclass, field
from pathlib import Path

from .config import ConfigHarness
from .contexto import SISTEMA, montar_prompt
from .ferramentas_agente import ESPECIFICACOES, despachar
from .politica import FERRAMENTAS, PREFIXO, STEP, HookPreToolUse, hook_pre_tool_use
from .tipos import FerramentasAgente, ResultadoTentativa, SaidaSessao, usd_para_centavos

EMBUTIDAS = (
    "Bash", "BashOutput", "KillShell", "Read", "Write", "Edit", "MultiEdit", "NotebookEdit", "Glob", "Grep",
    "WebFetch", "WebSearch", "Agent", "Task", "TodoWrite", "ListMcpResourcesTool", "ReadMcpResourceTool",
)
FOLGA_ORCAMENTO = 0.9


class ErroSegurancaHarness(RuntimeError):
    """A sessão do agente expôs algo fora da política; a tentativa é abortada."""


@dataclass
class ContextoSessao:
    """Tudo de que uma sessão precisa; o SDK só é importado ao abri-la."""
    cfg: ConfigHarness
    ferramentas: FerramentasAgente
    hook: HookPreToolUse
    max_budget_usd: float
    escritas: list[str] = field(default_factory=list)


RodarSessao = Callable[[str, ContextoSessao], SaidaSessao]


def verificar_ferramentas_sessao(ferramentas: list[str]) -> None:
    estranhas = [n for n in ferramentas if not n.startswith(PREFIXO)]
    if estranhas:
        raise ErroSegurancaHarness("a sessão do agente expôs ferramentas fora do catálogo: " + ", ".join(estranhas))


def construir_opcoes(cfg: ConfigHarness, servidor_mcp, hook: HookPreToolUse, cwd_vazio: Path, max_budget_usd: float):
    from claude_agent_sdk import ClaudeAgentOptions, HookMatcher

    return ClaudeAgentOptions(
        tools=[],
        disallowed_tools=list(EMBUTIDAS),
        allowed_tools=[PREFIXO + n for n in FERRAMENTAS],
        permission_mode="dontAsk",
        max_turns=cfg.max_turnos_tentativa,
        max_budget_usd=max_budget_usd,
        model=cfg.modelo,
        setting_sources=[],
        cwd=str(cwd_vazio),
        system_prompt=SISTEMA,
        mcp_servers={"korda": servidor_mcp},
        hooks={"PreToolUse": [HookMatcher(matcher=None, hooks=[hook])]},
        env={"ANTHROPIC_API_KEY": cfg.chave_api or ""},
    )


def ferramentas_sdk(ctx: ContextoSessao) -> list:
    """As seis ferramentas como SdkMcpTool, todas pelo mesmo `despachar` do falso."""
    from claude_agent_sdk import tool

    def fabricar(nome: str):
        async def executar(args: dict) -> dict:
            return await despachar(nome, args, ctx.ferramentas, ctx.escritas)
        return executar

    return [tool(nome, descricao, schema)(fabricar(nome)) for nome, (descricao, schema) in ESPECIFICACOES.items()]


def _servidor(ctx: ContextoSessao):
    from claude_agent_sdk import create_sdk_mcp_server

    return create_sdk_mcp_server(name="korda", version="0.1.0", tools=ferramentas_sdk(ctx))


async def _coletar(prompt: str, opcoes) -> SaidaSessao:
    from claude_agent_sdk import ResultMessage, SystemMessage, query

    ferramentas_sessao: list[str] = []
    resultado = None
    async with aclosing(query(prompt=prompt, options=opcoes)) as mensagens:
        async for msg in mensagens:
            if isinstance(msg, SystemMessage) and msg.subtype == "init":
                ferramentas_sessao = list(msg.data.get("tools") or [])
                verificar_ferramentas_sessao(ferramentas_sessao)
            elif isinstance(msg, ResultMessage):
                resultado = msg
    if resultado is None:
        return SaidaSessao("sem_resultado", 0, None, {}, ferramentas_sessao)
    return SaidaSessao(resultado.subtype, resultado.num_turns, resultado.total_cost_usd, resultado.usage or {},
                       ferramentas_sessao)


def rodar_sessao_sdk(prompt: str, ctx: ContextoSessao) -> SaidaSessao:
    """Abre uma sessão real do Agent SDK. Gasta créditos: só com o portão da config liberado."""
    servidor = _servidor(ctx)
    with tempfile.TemporaryDirectory(prefix="korda-agente-") as vazio:
        opcoes = construir_opcoes(ctx.cfg, servidor, ctx.hook, Path(vazio), ctx.max_budget_usd)
        return asyncio.run(_coletar(prompt, opcoes))


class CorretorAgente:
    nome = "agente_sdk"

    def __init__(self, cfg: ConfigHarness, ferramentas: FerramentasAgente, plano_publico: dict, perfis: dict,
                 limite: int, emissor, medidor, rodar_sessao: RodarSessao | None = None):
        if cfg.executor != "agente_sdk" or not cfg.permitir_llm_real or not cfg.chave_api:
            raise ValueError("CorretorAgente exige a configuração do agente liberada (ver ConfigHarness)")
        self.cfg = cfg
        self.ferramentas = ferramentas
        self.plano_publico = plano_publico
        self.perfis = perfis
        self.limite = limite
        self.emissor = emissor
        self.medidor = medidor
        self.rodar_sessao = rodar_sessao or rodar_sessao_sdk
        self.gasto_usd = 0.0

    def __call__(self, falha: dict, tentativa: int) -> dict:
        total = self.cfg.orcamento_execucao_usd
        restante = total - self.gasto_usd
        if restante <= 0:
            return {"ok": False, "erro": "orçamento de LLM esgotado", "custo_centavos": 0}
        teto = min(restante, total / 3) * FOLGA_ORCAMENTO
        hook = hook_pre_tool_use(self.plano_publico["editable_models"], self.emissor,
                                 obter_tentativa=lambda: tentativa)
        ctx = ContextoSessao(self.cfg, self.ferramentas, hook, teto)
        prompt = montar_prompt(falha, tentativa, self.limite, self.plano_publico, self.perfis)
        inicio = time.monotonic()
        saida = self.rodar_sessao(prompt, ctx)
        duracao = round(time.monotonic() - inicio, 3)

        # Custo desconhecido consome o teto inteiro da tentativa, por precaução.
        custo = saida.total_cost_usd
        if type(custo) not in (float, int) or not math.isfinite(custo) or custo < 0:
            custo = None
        self.gasto_usd += custo if custo is not None else teto
        custo_centavos = usd_para_centavos(custo, self.cfg.taxa_usd_brl)
        excedeu = saida.subtype == "error_max_budget_usd" or (custo is not None and custo > teto)
        ok = bool(ctx.escritas) and custo is not None and not excedeu and saida.subtype == "success"
        uso = saida.usage or {}
        if self.medidor is not None:
            self.medidor.registrar(ResultadoTentativa(
                tentativa=tentativa, corretor=self.nome, ok=ok, motivo_parada=saida.subtype, turnos=saida.num_turns,
                tokens_entrada=int(uso.get("input_tokens") or 0), tokens_saida=int(uso.get("output_tokens") or 0),
                tokens_cache_leitura=int(uso.get("cache_read_input_tokens") or 0), custo_usd=custo,
                custo_centavos=custo_centavos, duracao_s=duracao, arquivos_escritos=list(ctx.escritas)))
        if self.emissor is not None:
            self.emissor.emit_event(STEP, "agent_finished", f"agente terminou ({saida.subtype})", tentativa,
                                    subtype=saida.subtype, turnos=saida.num_turns, custo_usd=custo,
                                    custo_centavos=custo_centavos, arquivos=list(ctx.escritas),
                                    ferramentas_sessao=saida.ferramentas_sessao)
        if ok:
            return {"ok": True, "custo_centavos": custo_centavos}
        if excedeu:
            erro = "o SDK encerrou ou excedeu o orçamento autorizado da tentativa"
        elif ctx.escritas:
            erro = f"sessão do agente terminou com erro ({saida.subtype})"
        else:
            erro = f"agente terminou sem alteração ({saida.subtype})"
        return {"ok": False, "erro": erro, "custo_centavos": custo_centavos}
