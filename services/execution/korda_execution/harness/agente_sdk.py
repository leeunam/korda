"""Agente sobre o Claude Agent SDK. É o único arquivo que importa o SDK.

Dois modos, o mesmo isolamento:
- `agente_sdk` (CorretorAgente): só correção, chave da Anthropic, fora da demo;
- `claude_cli` (ExecutorClaudeCli e ClienteClaudeCli): construção, correção e
  planejamento pelo login do plano pessoal (`claude /login`), sem chave. O
  custo que o CLI informa é nocional: o limite real é a cota do plano.

O SDK roda o CLI do Claude Code no host (worker), onde estão o repositório e as
respostas esperadas. Por isso: sem ferramentas embutidas (`tools=[]` vira
`--tools ""`), lista explícita de embutidas proibidas, só as seis ferramentas
mcp__korda__* liberadas, modo `dontAsk`, hook que nega o resto, cwd numa pasta
vazia, sem configurações do disco, e a sessão é abortada se o init listar
qualquer ferramenta fora de mcp__korda__*.

O SDK monta o ambiente do CLI como `os.environ` + `options.env`: consegue
sobrescrever variáveis, não remover. No modo `claude_cli`, o `cli_path` aponta
para um lançador gerado por sessão, que troca o ambiente inteiro por uma lista
de permissão (`ambiente_minimo`) antes de executar o `claude` do host. Assim,
`KORDA_LLM_CHAVE` e o resto do `.env` nunca chegam ao CLI. Também liga
`--safe-mode` (sem CLAUDE.md, skills, plugins, hooks nem MCP do usuário),
`--strict-mcp-config` e `--no-session-persistence`. `--bare` não serve: nele o
CLI nunca lê o login OAuth.
"""

from __future__ import annotations

import asyncio
import json
import math
import os
import shutil
import subprocess
import sys
import tempfile
import time
from collections.abc import Callable
from contextlib import aclosing
from dataclasses import dataclass, field
from pathlib import Path

from .cliente_chat import ErroLLM, RespostaChat
from .config import VARIAVEIS_PROIBIDAS_CLI, ConfigHarness, ErroConfiguracao
from .contexto import SISTEMA, montar_prompt
from .executor_chat import TENTATIVA_CONSTRUCAO, ExecutorChat
from .ferramentas_agente import ESPECIFICACOES, despachar
from .politica import FERRAMENTAS, PREFIXO, STEP, HookPreToolUse, hook_pre_tool_use
from .tipos import FerramentasAgente, ResultadoTentativa, SaidaSessao, usd_para_centavos

EMBUTIDAS = (
    "Bash", "BashOutput", "KillShell", "Read", "Write", "Edit", "MultiEdit", "NotebookEdit", "Glob", "Grep",
    "WebFetch", "WebSearch", "Agent", "Task", "TodoWrite", "ListMcpResourcesTool", "ReadMcpResourceTool",
)
FOLGA_ORCAMENTO = 0.9
SERVIDOR = "korda"
# Variáveis que o próprio SDK passa ao CLI e o lançador deixa atravessar (nenhuma é segredo).
VARIAVEIS_DO_SDK = ("CLAUDE_CODE_ENTRYPOINT", "CLAUDE_AGENT_SDK_VERSION", "CLAUDE_CODE_SDK_READS_SESSION_STATE", "PWD")
# Corta o tráfego fora da conversa; não muda a autenticação.
VARIAVEIS_FIXAS = {"DISABLE_AUTOUPDATER": "1", "DISABLE_TELEMETRY": "1", "DISABLE_ERROR_REPORTING": "1",
                   "CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC": "1", "LANG": "C.UTF-8", "LC_ALL": "C.UTF-8"}
ARGS_ASSINATURA = {"safe-mode": None, "no-session-persistence": None}
CODIGO_LANCADOR_RECUSOU = 97


class ErroSegurancaHarness(RuntimeError):
    """A sessão do agente expôs algo fora da política; a tentativa é abortada."""


@dataclass
class ContextoSessao:
    """Tudo de que uma sessão precisa; o SDK só é importado ao abri-la."""
    cfg: ConfigHarness
    ferramentas: FerramentasAgente | None
    hook: HookPreToolUse | None
    max_budget_usd: float
    escritas: list[str] = field(default_factory=list)
    sistema: str = SISTEMA
    max_turns: int | None = None
    verificar_ativa: Callable[[], None] | None = None
    interrupcao: BaseException | None = None  # revogação vista dentro de uma ferramenta; relançada no fim


RodarSessao = Callable[[str, ContextoSessao], SaidaSessao]


# ---------------------------------------------------------------- verificações da sessão

def verificar_ferramentas_sessao(ferramentas: list[str]) -> None:
    estranhas = [n for n in ferramentas if not n.startswith(PREFIXO)]
    if estranhas:
        raise ErroSegurancaHarness("a sessão do agente expôs ferramentas fora do catálogo: " + ", ".join(estranhas))


def nomes_do_usuario(home: Path | None) -> set[str]:
    """Skills, agentes e comandos do ~/.claude do usuário: nenhum deles pode aparecer na sessão."""
    if home is None:
        return set()
    base = Path(home) / ".claude"
    nomes: set[str] = set()
    for pasta in ("skills", "agents", "commands"):
        try:
            nomes.update(p.stem for p in (base / pasta).iterdir())
        except OSError:
            continue
    return nomes


PREFIXO_PLUGIN_EMBUTIDO = "cc-plugin-"
PASTAS_PLUGINS_USUARIO = ("cache", "marketplaces", "synced", "data")


def _plugins_instalados(home: Path | None) -> set[str]:
    try:
        registro = json.loads((Path(home) / ".claude/plugins/installed_plugins.json").read_text(encoding="utf-8"))
    except (OSError, ValueError, TypeError):
        return set()
    plugins = registro.get("plugins", registro) if isinstance(registro, dict) else {}
    return {str(chave).split("@")[0] for chave in plugins} if isinstance(plugins, dict) else set()


def plugin_embutido(plugin, home: Path | None, cwd: str | None = None) -> bool:
    """Plugin que vem dentro do binário do Claude Code (`cc-plugin-*`; o --safe-mode os mantém ligados).

    Qualquer outro, ou um com o mesmo nome de um plugin instalado pelo usuário, ou carregado de uma pasta
    de plugins do ~/.claude ou do cwd, não é embutido.
    """
    if not isinstance(plugin, dict):
        return False
    nome, caminho = str(plugin.get("name") or ""), str(plugin.get("path") or "")
    if not nome.startswith(PREFIXO_PLUGIN_EMBUTIDO) or nome in _plugins_instalados(home):
        return False
    proibidas = [Path(cwd)] if cwd else []
    if home is not None:
        proibidas += [Path(home) / ".claude/plugins" / p for p in PASTAS_PLUGINS_USUARIO]
    alvo = Path(caminho)
    return not any(alvo == pasta or pasta in alvo.parents for pasta in proibidas)


def _nomes(itens) -> list[str]:
    return [str(i.get("name")) if isinstance(i, dict) else str(i) for i in (itens or [])]


def verificar_init(dados: dict, *, ferramentas_esperadas: set[str], home: Path | None) -> None:
    """Confere o init do modo assinatura antes do primeiro turno do modelo (abortar aqui não gasta cota)."""
    ferramentas = list(dados.get("tools") or [])
    verificar_ferramentas_sessao(ferramentas)
    faltam = sorted(ferramentas_esperadas - set(ferramentas))
    if faltam:
        raise ErroSegurancaHarness("o init não listou as ferramentas korda (o --safe-mode pode ter desligado o MCP "
                                   "em processo): " + ", ".join(faltam))
    servidores = [n for n in _nomes(dados.get("mcp_servers")) if n != SERVIDOR]
    if servidores:
        raise ErroSegurancaHarness("a sessão carregou servidores MCP de fora: " + ", ".join(servidores))
    de_fora = [p for p in dados.get("plugins") or [] if not plugin_embutido(p, home, dados.get("cwd"))]
    if de_fora:
        raise ErroSegurancaHarness("a sessão carregou plugins de fora do CLI: " + ", ".join(
            f"{p.get('name')} ({p.get('path')})" if isinstance(p, dict) else str(p) for p in de_fora))
    fonte = dados.get("apiKeySource")
    if fonte not in (None, "none"):
        raise ErroSegurancaHarness(f"a sessão não usou o login do plano (apiKeySource={fonte!r})")
    do_usuario = nomes_do_usuario(home)
    vazados = sorted({n.split(":")[-1].lstrip("/") for c in ("skills", "agents", "slash_commands")
                      for n in _nomes(dados.get(c))} & do_usuario)
    if vazados:
        raise ErroSegurancaHarness("a sessão carregou itens do ~/.claude do usuário: " + ", ".join(vazados))


# ---------------------------------------------------------------- CLI pelo login, com ambiente mínimo

def localizar_claude() -> str:
    caminho = shutil.which("claude")
    if not caminho:
        raise ErroConfiguracao("o CLI `claude` não está no PATH: instale o Claude Code e faça `claude /login`")
    return str(Path(caminho).resolve())


def ambiente_minimo(claude_real: str, origem: dict | None = None, home: str | None = None) -> dict:
    """O único ambiente que o CLI recebe: HOME (para achar o login), PATH fixo e as variáveis do SDK.

    Nada de KORDA_*, do .env, de ANTHROPIC_* nem de credenciais de nuvem.
    """
    origem = os.environ if origem is None else origem
    home = home or os.path.expanduser("~")
    caminhos = [str(Path(claude_real).parent), "/usr/local/bin", "/usr/bin", "/bin"]
    ambiente = {"HOME": home, "PATH": os.pathsep.join(caminhos), "USER": origem.get("USER") or Path(home).name,
                **VARIAVEIS_FIXAS}
    ambiente.update({k: origem[k] for k in VARIAVEIS_DO_SDK if k in origem})
    return ambiente


LANCADOR = '''#!{python} -I
# Gerado pelo harness da Korda para uma sessão; apagado ao fim. Troca o ambiente
# herdado do SDK pela lista de permissão e executa o claude do host.
import os, sys
PROIBIDAS = {proibidas!r}
presentes = [n for n in PROIBIDAS if n in os.environ]
if presentes:
    sys.stderr.write("korda: credencial de API no ambiente do CLI: " + ", ".join(presentes) + "\\n")
    sys.exit({codigo})
fixo = {fixo!r}
for k in {do_sdk!r}:
    if k in os.environ:
        fixo[k] = os.environ[k]
os.execve({claude!r}, [{claude!r}] + sys.argv[1:], fixo)
'''


def escrever_lancador(pasta: Path, claude_real: str, home: str | None = None) -> Path:
    fixo = ambiente_minimo(claude_real, {}, home)
    caminho = Path(pasta) / "claude-korda"
    caminho.write_text(LANCADOR.format(python=sys.executable, proibidas=VARIAVEIS_PROIBIDAS_CLI,
                                       codigo=CODIGO_LANCADOR_RECUSOU, fixo=fixo, do_sdk=VARIAVEIS_DO_SDK,
                                       claude=claude_real), encoding="utf-8")
    caminho.chmod(0o700)
    return caminho


def verificar_login(rodar=subprocess.run, claude_real: str | None = None) -> dict:
    """`claude auth status --json` (não gasta cota). Exige o login do plano, sem chave nem nuvem.

    Devolve só o método e o tipo do plano; e-mail e organização não saem daqui.
    """
    claude_real = claude_real or localizar_claude()
    orientacao = "faça `claude /login` com a conta do plano (ver services/execution/README.md)"
    try:
        r = rodar([claude_real, "auth", "status", "--json"], env=ambiente_minimo(claude_real), capture_output=True,
                  text=True, timeout=30, cwd=tempfile.gettempdir())
    except (OSError, subprocess.SubprocessError):
        raise ErroConfiguracao(f"não consegui conferir o login do CLI; {orientacao}") from None
    try:
        status = json.loads(r.stdout or "")
    except ValueError:
        status = None
    if r.returncode != 0 or not isinstance(status, dict):
        raise ErroConfiguracao(f"`claude auth status` falhou ou não existe nesta versão do CLI; {orientacao}")
    if status.get("loggedIn") is not True:
        raise ErroConfiguracao(f"o CLI não está logado; {orientacao}")
    if status.get("apiProvider") not in (None, "firstParty") or status.get("authMethod") != "claude.ai":
        raise ErroConfiguracao("o CLI está autenticado por outra via que não o login do plano "
                               f"(authMethod={status.get('authMethod')!r}); {orientacao}")
    return {"authMethod": status.get("authMethod"), "subscriptionType": status.get("subscriptionType")}


# ---------------------------------------------------------------- opções e coleta

def construir_opcoes(cfg: ConfigHarness, servidor_mcp, hook: HookPreToolUse | None, cwd_vazio: Path,
                     max_budget_usd: float, *, sistema: str = SISTEMA, max_turns: int | None = None,
                     cli_path: str | Path | None = None):
    from claude_agent_sdk import ClaudeAgentOptions, HookMatcher

    opcoes = dict(
        tools=[],
        disallowed_tools=list(EMBUTIDAS),
        allowed_tools=[PREFIXO + n for n in FERRAMENTAS] if servidor_mcp is not None else [],
        permission_mode="dontAsk",
        max_turns=max_turns or cfg.max_turnos_tentativa,
        max_budget_usd=max_budget_usd,
        model=cfg.modelo,
        setting_sources=[],
        cwd=str(cwd_vazio),
        system_prompt=sistema,
        mcp_servers={SERVIDOR: servidor_mcp} if servidor_mcp is not None else {},
        hooks={"PreToolUse": [HookMatcher(matcher=None, hooks=[hook])]} if hook is not None else {},
    )
    if cfg.cobranca == "assinatura":
        if cli_path is None:
            raise ValueError("o modo assinatura exige o lançador com ambiente mínimo")
        opcoes.update(cli_path=str(cli_path), strict_mcp_config=True, extra_args=dict(ARGS_ASSINATURA))
    else:
        opcoes["env"] = {"ANTHROPIC_API_KEY": cfg.chave_api or ""}
    return ClaudeAgentOptions(**opcoes)


def ferramentas_sdk(ctx: ContextoSessao) -> list:
    """As seis ferramentas como SdkMcpTool, todas pelo mesmo `despachar` do falso."""
    from claude_agent_sdk import tool

    def fabricar(nome: str):
        async def executar(args: dict) -> dict:
            if ctx.interrupcao is None and ctx.verificar_ativa is not None:
                try:
                    ctx.verificar_ativa()
                except Exception as exc:  # revogada: nada mais roda; a exceção volta ao worker no fim
                    ctx.interrupcao = exc
            if ctx.interrupcao is not None:
                return {"content": [{"type": "text", "text": '{"ok": false, "erro": "execução revogada"}'}],
                        "is_error": True}
            return await despachar(nome, args, ctx.ferramentas, ctx.escritas)
        return executar

    return [tool(nome, descricao, schema)(fabricar(nome)) for nome, (descricao, schema) in ESPECIFICACOES.items()]


def _servidor(ctx: ContextoSessao):
    from claude_agent_sdk import create_sdk_mcp_server

    return create_sdk_mcp_server(name=SERVIDOR, version="0.1.0", tools=ferramentas_sdk(ctx))


def _tokens_entrada(uso: dict) -> int:
    """Entrada total: tokens novos + criação e leitura de cache (o CLI informa os três separados)."""
    return sum(int(uso.get(c) or 0) for c in ("input_tokens", "cache_creation_input_tokens", "cache_read_input_tokens"))


async def _coletar(prompt: str, opcoes, verificar_init_fn: Callable[[dict], None] | None = None) -> SaidaSessao:
    from claude_agent_sdk import AssistantMessage, RateLimitEvent, ResultMessage, SystemMessage, query

    ferramentas_sessao: list[str] = []
    resultado = None
    modelo = None
    por_turno: dict[str, list[int]] = {}
    limite = None
    async with aclosing(query(prompt=prompt, options=opcoes)) as mensagens:
        async for msg in mensagens:
            if isinstance(msg, SystemMessage) and msg.subtype == "init":
                ferramentas_sessao = list(msg.data.get("tools") or [])
                modelo = msg.data.get("model")
                verificar_ferramentas_sessao(ferramentas_sessao)
                if verificar_init_fn is not None:
                    verificar_init_fn(msg.data)
            elif isinstance(msg, AssistantMessage):
                # Um turno pode vir em várias mensagens com o mesmo id e o mesmo uso.
                if msg.usage:
                    por_turno[msg.message_id or str(len(por_turno))] = [_tokens_entrada(msg.usage),
                                                                         int(msg.usage.get("output_tokens") or 0)]
                if msg.error == "rate_limit":
                    limite = limite or "rate_limit"
            elif isinstance(msg, RateLimitEvent):
                info = msg.rate_limit_info
                if info.status == "rejected":
                    limite = f"{info.rate_limit_type or 'cota'}, reinicia em {info.resets_at}"
            elif isinstance(msg, ResultMessage):
                resultado = msg
    if resultado is None:
        return SaidaSessao("sem_resultado", 0, None, {}, ferramentas_sessao, modelo=modelo,
                           tokens_por_turno=list(por_turno.values()), limite_uso=bool(limite),
                           erro=f"limite de uso do plano: {limite}" if limite else None)
    if resultado.is_error and resultado.api_error_status == 429:
        limite = limite or "HTTP 429"
    erro = None
    if limite:
        erro = f"limite de uso do plano: {limite}"
    elif resultado.is_error:
        detalhe = "; ".join(resultado.errors or []) or (resultado.result or "")
        status = f"HTTP {resultado.api_error_status}: " if resultado.api_error_status else ""
        erro = (status + detalhe)[:300] or resultado.subtype
    return SaidaSessao(resultado.subtype, resultado.num_turns, resultado.total_cost_usd, resultado.usage or {},
                       ferramentas_sessao, erro=erro, tokens_por_turno=list(por_turno.values()),
                       limite_uso=bool(limite), texto=resultado.result or "", modelo=modelo,
                       stop_reason=resultado.stop_reason)


def rodar_sessao_sdk(prompt: str, ctx: ContextoSessao) -> SaidaSessao:
    """Abre uma sessão real do Agent SDK com chave. Gasta créditos: só com o portão da config liberado."""
    servidor = _servidor(ctx)
    with tempfile.TemporaryDirectory(prefix="korda-agente-") as vazio:
        opcoes = construir_opcoes(ctx.cfg, servidor, ctx.hook, Path(vazio), ctx.max_budget_usd)
        return asyncio.run(_coletar(prompt, opcoes))


def rodar_sessao_cli(prompt: str, ctx: ContextoSessao) -> SaidaSessao:
    """Abre uma sessão real pelo login do plano. Gasta cota: só com o portão da config liberado.

    Sem `ctx.ferramentas` (planejamento), a sessão não tem servidor MCP nem ferramenta alguma.
    """
    claude_real = localizar_claude()
    home = os.path.expanduser("~")
    servidor = _servidor(ctx) if ctx.ferramentas is not None else None
    esperadas = {PREFIXO + n for n in FERRAMENTAS} if servidor is not None else set()
    with tempfile.TemporaryDirectory(prefix="korda-agente-") as vazio, \
            tempfile.TemporaryDirectory(prefix="korda-lancador-") as pasta_lancador:
        lancador = escrever_lancador(Path(pasta_lancador), claude_real, home)
        opcoes = construir_opcoes(ctx.cfg, servidor, ctx.hook, Path(vazio), ctx.max_budget_usd, sistema=ctx.sistema,
                                  max_turns=ctx.max_turns, cli_path=lancador)
        saida = asyncio.run(_coletar(prompt, opcoes, lambda d: verificar_init(
            d, ferramentas_esperadas=esperadas, home=Path(home))))
    if ctx.interrupcao is not None:
        raise ctx.interrupcao
    return saida


def _custo_valido(custo) -> float | None:
    if type(custo) not in (float, int) or not math.isfinite(custo) or custo < 0:
        return None
    return float(custo)


# ---------------------------------------------------------------- modo API (chave): só correção

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
        custo = _custo_valido(saida.total_cost_usd)
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


# ---------------------------------------------------------------- modo assinatura (claude_cli)

class ExecutorClaudeCli(ExecutorChat):
    """Construção e correção pelo CLI do Claude Code, com o login do plano. Mesma interface do ExecutorChat.

    Herda os tetos (60% na construção, o restante dividido pelas correções, folga de 10%) e os prompts.
    O `total_cost_usd` do CLI é nocional (cota do plano), mas segue como freio: `max_budget_usd`.
    Limite de uso do plano: registra `erro_api`, devolve falha e não abre outra sessão nesta execução.
    """
    nome = "claude_cli"

    def __init__(self, cfg: ConfigHarness, ferramentas: FerramentasAgente, plano_publico: dict, perfis: dict,
                 limite: int, emissor, medidor, *, rodar_sessao: RodarSessao | None = None, **extra):
        if cfg.executor != "claude_cli" or not cfg.permitir_llm_real:
            raise ValueError("ExecutorClaudeCli exige KORDA_EXECUTOR=claude_cli e KORDA_PERMITIR_LLM_REAL=1")
        super().__init__(cfg, None, ferramentas, plano_publico, perfis, limite, emissor, medidor, **extra)
        self.rodar_sessao = rodar_sessao or rodar_sessao_cli
        self.limite_uso: str | None = None

    def _sessao(self, sistema: str, prompt: str, tentativa: int, teto: float, max_turnos: int,
                modelos_obrigatorios: list[str] | None = None) -> dict:
        if self.limite_uso:
            return {"ok": False, "codigo": "limite_uso", "erro": self.limite_uso, "custo_centavos": 0}
        if self.restante_usd <= 0 or teto <= 0:
            return {"ok": False, "erro": "orçamento de LLM esgotado", "custo_centavos": 0}
        hook = hook_pre_tool_use(self.plano_publico["editable_models"], self.emissor,
                                 obter_tentativa=lambda: max(1, tentativa))
        ctx = ContextoSessao(self.cfg, self.ferramentas, hook, teto, sistema=sistema, max_turns=max_turnos,
                             verificar_ativa=self.verificar_ativa)
        inicio = time.monotonic()
        saida = self.rodar_sessao(prompt, ctx)
        self.ultima_saida = saida
        duracao = round(time.monotonic() - inicio, 3)
        escritas = list(ctx.escritas)
        # Custo desconhecido consome o teto inteiro, por precaução.
        custo = _custo_valido(saida.total_cost_usd)
        self.gasto_usd += custo if custo is not None else teto
        custo_centavos = usd_para_centavos(custo, self.cfg.taxa_usd_brl)
        self.custo_total_centavos += custo_centavos or 0
        # O CLI só confere o teto depois do turno; até a fatia sem a folga, é o freio funcionando.
        excedeu = custo is not None and custo > teto / FOLGA_ORCAMENTO
        if saida.limite_uso:
            self.limite_uso = (f"{saida.erro or 'limite de uso do plano'}; a sessão parou e uma pessoa decide "
                               "quando retomar (sem nova tentativa automática)")
        ok = (bool(escritas) and not excedeu and custo is not None and not saida.limite_uso
              and saida.subtype not in ("error_during_execution", "sem_resultado"))
        uso = saida.usage or {}
        tokens_entrada, tokens_saida = _tokens_entrada(uso), int(uso.get("output_tokens") or 0)
        if self.medidor is not None:
            self.medidor.registrar(ResultadoTentativa(
                tentativa=tentativa, corretor=self.nome, ok=ok, motivo_parada=saida.subtype, turnos=saida.num_turns,
                tokens_entrada=tokens_entrada, tokens_saida=tokens_saida,
                tokens_cache_leitura=int(uso.get("cache_read_input_tokens") or 0), custo_usd=custo,
                custo_centavos=custo_centavos, duracao_s=duracao, arquivos_escritos=escritas))
        if self.emissor is not None:
            construcao = tentativa == TENTATIVA_CONSTRUCAO
            fase = "construção" if construcao else f"correção {tentativa}"
            self.emissor.emit_event(
                STEP, "agent_finished", f"Agente terminou a {fase} ({saida.subtype})", max(1, tentativa),
                fase="construcao" if construcao else "correcao", subtype=saida.subtype,
                turnos=saida.num_turns, arquivos=escritas, custo_usd=custo, custo_centavos=custo_centavos,
                custo_total_centavos=self.custo_total_centavos,
                orcamento_centavos=usd_para_centavos(self.orcamento_total_usd, self.cfg.taxa_usd_brl),
                custo_estimado=True, cobranca="assinatura", modelo=saida.modelo or self.cfg.modelo,
                tokens_entrada=tokens_entrada, tokens_saida=tokens_saida, ferramentas=list(saida.ferramentas_sessao),
                tokens_por_turno=saida.tokens_por_turno, limite_uso=saida.limite_uso,
                **({"erro_api": saida.erro} if saida.erro else {}))
        if ok:
            return {"ok": True, "custo_centavos": custo_centavos}
        if saida.limite_uso:
            return {"ok": False, "codigo": "limite_uso", "erro": self.limite_uso, "custo_centavos": custo_centavos}
        if excedeu:
            return {"ok": False, "erro": "a sessão excedeu o orçamento autorizado", "custo_centavos": custo_centavos}
        motivo = "terminou com erro" if escritas else "terminou sem alteração"
        detalhe = f": {saida.erro}" if saida.erro else ""
        return {"ok": False, "erro": f"agente {motivo} ({saida.subtype}){detalhe}", "custo_centavos": custo_centavos}


class ClienteClaudeCli:
    """`completar` sem ferramentas sobre uma sessão de um turno do CLI, para o planejamento.

    Mantém a interface do ClienteChat: `gerar_documento_base`, o ClienteComOrcamento e o bloco de
    decisão não mudam. `custos_nocionais_usd` guarda o total_cost_usd do CLI de cada chamada.
    """

    def __init__(self, cfg: ConfigHarness, rodar_sessao: RodarSessao | None = None):
        if cfg.executor != "claude_cli" or not cfg.permitir_llm_real:
            raise ValueError("ClienteClaudeCli exige KORDA_EXECUTOR=claude_cli e KORDA_PERMITIR_LLM_REAL=1")
        self.cfg = cfg
        self.rodar_sessao = rodar_sessao or rodar_sessao_cli
        self.custos_nocionais_usd: list[float | None] = []
        self.ultima_saida: SaidaSessao | None = None

    def completar(self, mensagens: list[dict], ferramentas: list[dict], *, max_tokens: int | None = None) -> RespostaChat:
        if ferramentas:
            raise ValueError("ClienteClaudeCli não oferece ferramentas: é só para o planejamento")
        sistema = "\n\n".join(m["content"] for m in mensagens if m.get("role") == "system")
        prompt = "\n\n".join(m["content"] for m in mensagens if m.get("role") == "user")
        ctx = ContextoSessao(self.cfg, None, None, self.cfg.orcamento_execucao_usd * FOLGA_ORCAMENTO,
                             sistema=sistema, max_turns=1)
        saida = self.rodar_sessao(prompt, ctx)
        self.ultima_saida = saida
        self.custos_nocionais_usd.append(_custo_valido(saida.total_cost_usd))
        if saida.limite_uso or saida.subtype != "success" or saida.erro:
            raise ErroLLM(f"sessão do CLI terminou com {saida.subtype}: {saida.erro or 'sem detalhe'}"[:300])
        uso = saida.usage or {}
        return RespostaChat(conteudo=saida.texto, tool_calls=[], tokens_entrada=_tokens_entrada(uso),
                            tokens_saida=int(uso.get("output_tokens") or 0),
                            finish_reason="length" if saida.stop_reason == "max_tokens" else "stop",
                            uso_informado="output_tokens" in uso,
                            mensagem_assistente={"role": "assistant", "content": saida.texto})
