"""Simulador de custo da construção pelo ExecutorChat (sem LLM).

Roda `executar_sessao` com um cliente roteirizado que imita uma construção e
mede o que seria enviado à API em cada turno. Tokens são **estimados** por
caracteres ÷ 4 sobre o JSON de `mensagens` + catálogo de ferramentas (sem
tokenizer). Os tamanhos de saída das ferramentas imitam o projeto protegido
real (arquivos lidos do disco) e um dbt build de 5 modelos e 6 testes. Nada
de `pipeline/projeto/models/*.sql` é lido: os SQL "escritos" são texto de
enchimento com o tamanho típico.

Uso: `cd services/execution && python3 -m tests.harness.simulador_custo`.
"""

from __future__ import annotations

import json
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path

from korda_execution.eventos import EmissorEventos
from korda_execution.harness.cliente_chat import RespostaChat
from korda_execution.harness.contexto import SISTEMA_CONSTRUCAO, montar_prompt_construcao, projetar_plano
from korda_execution.harness.sessao_chat import executar_sessao

RAIZ_EXEC = Path(__file__).resolve().parents[2]
REPO = RAIZ_EXEC.parents[1]
PROJETO = RAIZ_EXEC / "pipeline/projeto"
DOCUMENTO = RAIZ_EXEC / "tests/fixtures/planejamento/02_rateio_confirmado.md"
CONTEXTO = REPO / "packages/contracts/context/v0.1.0/examples/02_rateio_confirmado.json"
PRECOS = (4.0, 20.0)  # padrão de ConfigHarness (USD por milhão de tokens)
CARACTERES_POR_TOKEN = 4
# No ensaio-01 (27/11/2026), um roteiro equivalente estimou 152 mil tokens de entrada; o gateway informou 338 mil.
FATOR_ENSAIO01 = 2.2

MODELOS = {"models/prata_ctes.sql": 2500, "models/prata_rateios.sql": 2000, "models/ouro_por_pedido.sql": 4000,
           "models/ouro_por_viagem.sql": 3000, "models/ouro_kpis.sql": 1500}

PERFIS = {
    "erp_pedidos": {"fonte": "erp_pedidos", "formato": "csv", "colunas": ["cd_ped", "cd_cli", "dt_emis", "dt_prev_ent",
                    "qt_itens", "ps_bruto", "vl_cubag", "vl_merc", "ch_nfe"], "separador": ";",
                    "registros_analisados": 100, "amostra_parcial": True},
    "tms_entregas": {"fonte": "tms_entregas", "formato": "csv", "colunas": ["id_ent", "id_viag", "nr_ped", "seq_parada",
                     "qt_entregue", "dt_baixa", "st_ent"], "separador": ";", "registros_analisados": 100,
                     "amostra_parcial": True},
    "cte": {"fonte": "cte", "formato": "xml", "arquivos_elegiveis": 3494, "arquivos_analisados": 24,
            "amostra_parcial": True, "tipos_na_amostra": {"cteProc": 22, "procEventoCTe": 2}},
}


def _sql_enchimento(caminho: str, tamanho: int) -> str:
    """SQL fictício do tamanho dado (não é o modelo de referência)."""
    linha = "  , coalesce(campo_sintetico, 0) as coluna_sintetica -- enchimento do simulador\n"
    corpo = f"-- {caminho} (simulado)\nselect\n" + linha * (tamanho // len(linha) + 1)
    return corpo[:tamanho]


def saida_dbt(falha: str | None, n_modelos: int = 5, n_testes: int = 6) -> str:
    """Saída típica de `dbt build` (dbt 1.x, sem cor) com cabeçalho, um par START/OK por nó e o resumo."""
    nos = [f"model main.{Path(m).stem}" for m in list(MODELOS)[:n_modelos]] + [f"test teste_{i}" for i in range(n_testes)]
    linhas = ["12:00:00  Running with dbt=1.9.4", "12:00:00  Registered adapter: duckdb=1.9.2",
              f"12:00:01  Found {n_modelos} models, {n_testes} data tests, 5 sources, 512 macros", "",
              "12:00:01  Concurrency: 1 threads (target='sandbox')", ""]
    total = len(nos)
    erros = 0
    for i, no in enumerate(nos, 1):
        linhas.append(f"12:00:0{i % 10}  {i} of {total} START sql table {no} " + "." * 30 + " [RUN]")
        if falha and i == 3:
            linhas.append(f"12:00:0{i % 10}  {i} of {total} ERROR creating sql table {no} " + "." * 20 + " [ERROR in 0.05s]")
            erros += 1
        else:
            linhas.append(f"12:00:0{i % 10}  {i} of {total} OK created sql table {no} " + "." * 24 + " [OK in 0.04s]")
    linhas += ["", "12:00:09  Finished running 5 table models, 6 data tests in 0 hours 0 minutes and 1.20 seconds (1.20s).", ""]
    if falha:
        linhas += ["12:00:09  Completed with 1 error, 0 partial successes, and 0 warnings:", "",
                   "12:00:09    Runtime Error in model ouro_por_pedido (models/ouro_por_pedido.sql)",
                   f"  {falha}", "", "12:00:09    compiled code at target/run/korda_logistica/models/ouro_por_pedido.sql", ""]
    linhas.append(f"12:00:09  Done. PASS={total - erros} WARN=0 ERROR={erros} SKIP=0 NO-OP=0 TOTAL={total}")
    return "\n".join(linhas)


ERRO_BINDER = ("Binder Error: Referenced column \"peso_kg\" not found in FROM clause!\n  Candidate bindings: "
               "\"peso_decimos_kg\", \"pedido_id\", \"qt_itens\", \"chave_nfe\", \"data_prevista\"\n"
               "  LINE 14:     sum(p.peso_kg) over (partition by r.chave_cte) as peso_total\n"
               "                    ^")


class FerramentasSimuladas:
    """Mesmo contrato de FerramentasRestritas, com saídas do tamanho real."""

    def __init__(self, plano_publico: dict, builds: list[str | None]):
        self.plano = plano_publico
        self.builds = list(builds)
        self.escritas: list[str] = []

    def ler_plano(self):
        return {"ok": True, "plano": self.plano}

    def inspecionar_fonte(self, fonte):
        return {"ok": True, "perfil": PERFIS.get(fonte, {"fonte": fonte})}

    def ler_arquivo(self, caminho):
        if caminho.startswith("models/"):
            raise AssertionError("o simulador não lê modelos de referência")
        return {"ok": True, "caminho": caminho, "conteudo": (PROJETO / caminho).read_text(encoding="utf-8")}

    def escrever_modelo(self, caminho, conteudo):
        self.escritas.append(caminho)
        return {"ok": True, "caminho": caminho}

    def rodar_dbt(self, subcomando, selecao=None):
        falha = self.builds.pop(0) if self.builds else None
        n = 1 if selecao else 5
        return {"ok": falha is None, "codigo": 1 if falha else 0, "estourou_tempo": False, "duracao_s": 4.2,
                "stdout": saida_dbt(falha, n_modelos=n, n_testes=0 if selecao else 6), "stderr": ""}

    def consultar_sql(self, sql):
        # ~20 linhas × 8 colunas: uma amostra ou um describe típicos.
        colunas = [f"col_{i}" for i in range(8)]
        return {"ok": True, "colunas": colunas, "linhas": [[f"valor_{l}_{c}" for c in range(8)] for l in range(20)],
                "truncado": False}


class ClienteMedidor:
    """Devolve o roteiro em ordem e estima os tokens de cada pedido pelo tamanho do que seria enviado."""

    def __init__(self, roteiro: list[list[tuple[str, dict]] | None]):
        self.roteiro = list(roteiro)
        self.por_turno: list[dict] = []

    def completar(self, mensagens, ferramentas, *, max_tokens=None):
        enviado = len(json.dumps([mensagens, ferramentas], ensure_ascii=False))
        chamadas = self.roteiro.pop(0) if self.roteiro else None
        if chamadas is None:
            resposta = RespostaChat.texto("Construção concluída.", tokens=(0, 0))
        else:
            resposta = RespostaChat.de_tool_calls(chamadas, tokens=(0, 0))
        gerado = len(json.dumps(resposta.mensagem_assistente, ensure_ascii=False))
        resposta.tokens_entrada = enviado // CARACTERES_POR_TOKEN
        resposta.tokens_saida = gerado // CARACTERES_POR_TOKEN + 40  # + raciocínio curto antes das chamadas
        self.por_turno.append({"entrada": resposta.tokens_entrada, "saida": resposta.tokens_saida})
        return resposta


def _escrever(caminho):
    return ("escrever_modelo", {"caminho": caminho, "conteudo": _sql_enchimento(caminho, MODELOS[caminho])})


def roteiro_tipico(descoberta_no_prompt: bool = False, seletivo: bool = False):
    """Construção típica: ler o plano, inspecionar 3 fontes, ler exportar.py e 2 testes, escrever 5 modelos,
    3 builds e 1 correção. Com `descoberta_no_prompt`, o contrato e o esquema da bronze já vêm no prompt
    e as leituras de dbt_project.yml, fontes.yml e o describe da bronze deixam de ser necessárias (suposição)."""
    build = ("rodar_dbt", {"subcomando": "build"})
    r = [[("ler_plano", {})]]
    if not descoberta_no_prompt:
        r.append([("ler_arquivo", {"caminho": "definicoes/fontes.yml"}), ("ler_arquivo", {"caminho": "dbt_project.yml"})])
    r.append([("ler_arquivo", {"caminho": "exportar.py"})])
    r.append([("ler_arquivo", {"caminho": "tests/conservacao.sql"}), ("ler_arquivo", {"caminho": "tests/chave_fiscal_unica.sql"})])
    r.append([("inspecionar_fonte", {"fonte": f}) for f in PERFIS])
    if not descoberta_no_prompt:
        r.append([("consultar_sql", {"sql": "describe bronze_pedidos"})])
    r.append([("consultar_sql", {"sql": "select * from bronze_documentos limit 20"})])
    r += [[_escrever(m)] for m in MODELOS]
    r.append([("rodar_dbt", {"subcomando": "build", "selecao": "ouro_por_pedido+"})] if seletivo else [build])
    r.append([("consultar_sql", {"sql": "describe bronze_pedidos"})])
    r.append([_escrever("models/ouro_por_pedido.sql")])
    r.append([("rodar_dbt", {"subcomando": "build", "selecao": "ouro_por_pedido+"})] if seletivo else [build])
    r.append([build])
    r.append(None)
    return r, [ERRO_BINDER, None, None]


def roteiro_longo():
    """Construção difícil: lê tudo, 3 correções e mais consultas (~30 turnos)."""
    build = ("rodar_dbt", {"subcomando": "build"})
    r = [[("ler_plano", {})], [("ler_arquivo", {"caminho": "definicoes/fontes.yml"})],
         [("ler_arquivo", {"caminho": "dbt_project.yml"})], [("ler_arquivo", {"caminho": "exportar.py"})],
         [("ler_arquivo", {"caminho": "ingerir.py"})]]
    r += [[("ler_arquivo", {"caminho": f"tests/{t}"})] for t in ("conservacao.sql", "chave_fiscal_unica.sql",
          "documentos_conflitantes.sql", "integridade_fontes.sql", "rastreabilidade_cte.sql", "contrato_exportacao.sql")]
    r.append([("inspecionar_fonte", {"fonte": f}) for f in PERFIS])
    r += [[("consultar_sql", {"sql": f"describe bronze_{t}"})] for t in ("pedidos", "entregas", "documentos")]
    r += [[_escrever(m)] for m in MODELOS]
    for _ in range(3):
        r += [[build], [("consultar_sql", {"sql": "select 1"})], [_escrever("models/ouro_por_pedido.sql")]]
    r += [[build], None]
    return r, [ERRO_BINDER, ERRO_BINDER, ERRO_BINDER, None]


def plano_publico() -> dict:
    sys.path.insert(0, str(REPO))
    from services.planning.korda_planning import gerar_plano

    contexto = json.loads(CONTEXTO.read_text(encoding="utf-8"))
    plano = gerar_plano(contexto, destino="pasta-demo", custo_estimado_centavos=0)
    return projetar_plano(plano)


@dataclass
class Resultado:
    nome: str
    turnos: int
    prompt_inicial: int
    maior_pedido: int
    entrada: int
    saida: int
    subtype: str

    @property
    def usd(self) -> float:
        return (self.entrada * PRECOS[0] + self.saida * PRECOS[1]) / 1_000_000

    @property
    def usd_calibrado(self) -> float:
        return (self.entrada * FATOR_ENSAIO01 * PRECOS[0] + self.saida * PRECOS[1]) / 1_000_000


def simular(nome: str, roteiro_e_builds, *, teto_usd: float = 4.05, max_turnos: int = 40, **sessao) -> Resultado:
    publico = plano_publico()
    roteiro, builds = roteiro_e_builds
    perfis = PERFIS
    prompt = montar_prompt_construcao(publico, perfis, DOCUMENTO.read_text(encoding="utf-8"))
    cliente = ClienteMedidor(roteiro)
    with tempfile.TemporaryDirectory() as tmp:
        emissor = EmissorEventos(Path(tmp) / "eventos.jsonl", "simulador")
        saida, _ = executar_sessao(cliente, SISTEMA_CONSTRUCAO, prompt, FerramentasSimuladas(publico, builds),
                                   publico["editable_models"], emissor=emissor, tentativa=1, max_turnos=max_turnos,
                                   teto_usd=teto_usd, precos=PRECOS, **sessao)
    t = cliente.por_turno
    return Resultado(nome, len(t), t[0]["entrada"], max(x["entrada"] for x in t), sum(x["entrada"] for x in t),
                     sum(x["saida"] for x in t), saida.subtype)


def cenarios() -> list[Resultado]:
    return [simular("típico, sem compactar histórico", roteiro_tipico(), manter_turnos=None),
            simular("típico", roteiro_tipico()),
            simular("típico, descoberta no prompt + builds seletivos", roteiro_tipico(True, True)),
            simular("longo, sem compactar histórico", roteiro_longo(), manter_turnos=None),
            simular("longo (3 correções)", roteiro_longo())]


def tabela(resultados: list[Resultado]) -> str:
    linhas = ["| Cenário | Turnos | Prompt inicial | Maior pedido | Entrada acumulada | Saída | US$ | US$ ×2,2 | Parada |",
              "| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | --- |"]
    def n(valor):
        return f"{valor:,}".replace(",", ".")

    linhas += [f"| {r.nome} | {r.turnos} | {n(r.prompt_inicial)} | {n(r.maior_pedido)} | {n(r.entrada)} | {n(r.saida)} "
               f"| {r.usd:.2f} | {r.usd_calibrado:.2f} | {r.subtype} |" for r in resultados]
    return "\n".join(linhas)


if __name__ == "__main__":
    print("Tokens estimados por caracteres ÷ 4 (sem tokenizer); preços 4/20 US$ por MTok. "
          f"A coluna ×{FATOR_ENSAIO01} aplica à entrada o fator observado no ensaio-01.\n")
    print(tabela(cenarios()))
