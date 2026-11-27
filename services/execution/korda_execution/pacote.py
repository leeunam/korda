"""Pacote local de reprodução da execução v0.2, preparado após o aceite técnico."""

import fcntl
import hashlib
import json
import math
import os
import re
import stat
import uuid
import zipfile
from contextlib import contextmanager
from datetime import datetime
from html import escape
from pathlib import Path

from .artefatos import LIMITES, LIMITE_PACOTE, PACOTE, _diretorio


REPO = Path(__file__).resolve().parents[3]
MODELOS = ("prata_ctes", "prata_rateios", "ouro_por_pedido", "ouro_por_viagem", "ouro_kpis")
TESTES = ("chave_fiscal_unica", "conservacao", "contrato_exportacao", "documentos_conflitantes",
          "integridade_fontes", "rastreabilidade_cte")
CONFIG = ("dbt_project.yml", "profiles.yml", "definicoes/fontes.yml", "macros/meio_par.sql",
          "ingerir.py", "exportar.py")
AMBIENTE = ("Dockerfile", "requirements.txt", "consulta.py", "perfil.py",
            *("korda_ingestao/" + n + ".py" for n in ("__init__", "__main__", "csv_bruto", "cte", "landing", "parquet")))
# O SQL gerado também é um artefato público da demo. Rejeite credenciais com
# formato reconhecível sem registrar o texto suspeito em logs ou mensagens.
CREDENCIAL_SQL = re.compile(
    r"-----BEGIN [A-Z ]*PRIVATE KEY-----|\b(?:sk-(?:proj-|ant-)?|gh[pousr]_)[\w-]{20,}"
    r"|\bBearer\s+[A-Za-z0-9._~+/-]{16,}"
    r"|\b(?:api[_-]?key|access[_-]?token|password|senha)\s*[:=]\s*['\"][^'\"\s]{4,}['\"]",
    re.IGNORECASE,
)
REPRODUZIR = """# Reproduzir os indicadores

Extraia este ZIP em um diretório novo. A pasta `projeto/` contém o SQL que o dbt executou e os testes protegidos. `resultados/` contém os indicadores e sua linhagem por pedido e viagem. `execucao.json` identifica a revisão do plano, a janela, o destino autorizado pelo plano e o laudo técnico. A autorização humana para entrega é registrada pelo serviço que promove a pasta.

Abra `docs/index.html` no navegador, inclusive offline, para consultar colunas, tipos físicos, fontes e dependências dos modelos. O worker gera o catálogo com `dbt docs generate` na sandbox e combina as relações descritas no manifesto do build. Em `decisoes.json`, as referências `/evidence/N` apontam à posição da evidência no plano local da versão identificada. O hash do documento de construção permite conferir o texto aprovado sem distribuí-lo.

Os dados da transportadora são sintéticos. `medicao.json` identifica se a construção usou um executor simulado. A lista `por_tentativa` registra o resultado de cada sessão, os turnos, tokens, duração e custos conhecidos. Nela, a tentativa zero corresponde à construção inicial. O total em centavos de real só aparece quando a medição está completa. Custos de planejamento anterior e de infraestrutura ficam fora dessa medição. `eventos.jsonl` lista as etapas da execução até a avaliação técnica. Mensagens de conversa, erros detalhados, consultas e credenciais ficam fora desse extrato. A promoção ocorre depois da aprovação humana do pacote.

Use Docker em Linux e a mesma landing autorizada da execução, com manifesto e tabelas Parquet. Em N0 ela vem dos arquivos exportados. Em N1 ela corresponde à janela do ERP, TMS e CT-e simulados. O operador fornece essa pasta em separado. Confira `sha256sum "$LANDING/manifesto.json"` com `landing_manifest_sha256` de `execucao.json` para identificar o manifesto original.

Para regenerar as entradas sintéticas, use o gerador `data/synthetic/generator/generate.py --empresa 01_demo` do repositório Korda. Aplique ao lote o nível e a janela registrados em `execucao.json`, usando a ingestão N0 ou o replay dos sistemas simulados N1 na versão do projeto da execução. O diretório `ambiente/korda_ingestao/` traz o leitor N0; nas entregas N1, `referencia/ingestao_n1/` traz também o leitor do simulador. Uma nova carga pode registrar outro horário e produzir um hash físico de manifesto diferente. Use os hashes dos três resultados para conferir o replay da mesma janela.

Na raiz extraída, defina `LANDING` como o caminho absoluto da landing. Comece com um diretório `saida` novo. O primeiro comando prepara o ambiente com as versões da demo. O segundo executa o tratamento dos dados sem rede.

```sh
docker build -t korda-repro:local ambiente
mkdir -m 700 saida
docker run --rm -i --network none --read-only --cap-drop ALL \\
  --security-opt no-new-privileges --user "$(id -u):$(id -g)" --tmpfs /tmp:rw,nosuid,size=256m \\
  --memory 2g --cpus 1 --pids-limit 256 \\
  -v "$PWD/projeto:/work/projeto:ro" -v "$LANDING:/work/fontes:ro" \\
  -v "$PWD/saida:/work/saida" korda-repro:local sh -ec \\
  'python /work/projeto/ingerir.py && dbt --no-use-colors build && python /work/projeto/exportar.py && DBT_TARGET_PATH=/work/saida/docs dbt --no-use-colors docs generate' < regras.json
(cd saida && sha256sum -c ../resultados.sha256)
```

Para auditar o frete, localize o pedido em `resultados/por_pedido.csv` e consulte `linhagem_cte`, com a chave do documento, hash do XML e centavos rateados. O mesmo CSV identifica o pedido e a entrega que sustentam o OTIF. `por_viagem.csv` identifica a viagem e o veículo usados para ocupação. Em N1, use também a carga da landing para localizar o registro da janela avaliada.
"""


@contextmanager
def _arquivo(pasta, nome, limite):
    relativo = Path(nome)
    if relativo.is_absolute() or ".." in relativo.parts:
        raise ValueError("caminho de arquivo inválido")
    with _diretorio(pasta / relativo.parent) as pai:
        fd = os.open(relativo.name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=pai)
        try:
            st = os.fstat(fd)
            if not stat.S_ISREG(st.st_mode) or st.st_nlink != 1 or not 0 < st.st_size <= limite:
                raise ValueError(f"arquivo de pacote irregular ou excede limite: {nome}")
            with os.fdopen(fd, "rb", closefd=False) as entrada:
                yield entrada
            final = os.fstat(fd)
            if (st.st_size, st.st_mtime_ns) != (final.st_size, final.st_mtime_ns):
                raise ValueError(f"arquivo de pacote mudou durante a captura: {nome}")
        finally:
            os.close(fd)


def _ler(pasta, nome, limite):
    with _arquivo(pasta, nome, limite) as f:
        dados = f.read(limite + 1)
        if len(dados) > limite:
            raise ValueError(f"arquivo excede limite de leitura: {nome}")
        return dados


def _json(valor):
    return (json.dumps(valor, ensure_ascii=False, allow_nan=False, sort_keys=True, indent=2) + "\n").encode()


def _entrada_zip(nome):
    info = zipfile.ZipInfo(nome)  # Horário fixo, independente do momento de empacotar.
    info.compress_type = zipfile.ZIP_DEFLATED
    info.external_attr = 0o100644 << 16
    return info


def _dbt(projeto, modelos):
    target = projeto.parent / "saida/target"
    relatorio = json.loads(_ler(target, "run_results.json", 8 * 1024**2))
    manifest = json.loads(_ler(target, "manifest.json", 16 * 1024**2))
    if not relatorio["metadata"].get("invocation_id") or (
        relatorio["metadata"]["invocation_id"] != manifest["metadata"].get("invocation_id")
    ):
        raise ValueError("relatório e manifesto dbt pertencem a builds diferentes")
    esperados = {f"model.korda_logistica.{m}": "success" for m in MODELOS}
    esperados.update({f"test.korda_logistica.{t}": "pass" for t in TESTES})
    nos = {r["unique_id"]: r["status"] for r in relatorio["results"]}
    if nos != esperados or len(nos) != len(relatorio["results"]):
        raise ValueError("o dbt não confirmou todos os modelos e testes protegidos")
    for nome, dados in modelos.items():
        node = manifest["nodes"]["model.korda_logistica." + Path(nome).stem]
        codigo = dados.decode("utf-8").replace("\r\n", "\n").strip()
        if not codigo or node["original_file_path"] != nome or node["raw_code"].strip() != codigo:
            raise ValueError(f"o SQL capturado diverge do modelo testado: {nome}")
        if CREDENCIAL_SQL.search(codigo):
            raise ValueError(f"credencial identificada no SQL; revise o modelo antes da entrega: {nome}")
    return {"versao": relatorio["metadata"]["dbt_version"], "nos": nos}, manifest


def _docs(projeto, manifest):
    """Publica nomes e tipos físicos e as arestas do manifesto. Textos livres ficam na sandbox."""
    catalogo = json.loads(_ler(projeto.parent / "saida/docs", "catalog.json", 8 * 1024**2))
    fontes = {"source.korda_logistica.sinteticas.bronze_" + n for n in
              ("pedidos", "entregas", "viagens", "veiculos", "documentos")}
    ids = fontes | {"model.korda_logistica." + n for n in MODELOS}
    partes = ['<!doctype html><html lang="pt-BR"><meta charset="utf-8">',
              '<meta http-equiv="Content-Security-Policy" content="default-src \'none\'">',
              '<title>Dicionário e linhagem da execução</title><h1>Dicionário e linhagem da execução</h1>',
              '<p>Fontes bronze e modelos testados da transportadora sintética. '
              'Os tipos de coluna foram consultados no catálogo do DuckDB pelo dbt.</p>']
    for id_ in sorted(ids, key=lambda item: (item not in fontes, item)):
        colecao = "sources" if id_ in fontes else "nodes"
        nome = id_.split(".")[-1]
        partes.append(f'<section id="{nome}"><h2>{nome}</h2>')
        if id_ not in fontes:
            pais = manifest["nodes"][id_]["depends_on"]["nodes"]
            if any(p not in ids for p in pais):
                raise ValueError("dependência fora das fontes ou modelos da demonstração")
            referencias = [p.split(".")[-1] for p in sorted(set(pais))]
            links = [f'<a href="#{pai}">{pai}</a>' for pai in referencias]
            partes.append("<p>Dependências no manifesto dbt: " + (", ".join(links) or "nenhuma") + ".</p>")
        colunas = catalogo[colecao][id_]["columns"]
        if not 1 <= len(colunas) <= 128:
            raise ValueError("número de colunas fora do limite no catálogo dbt")
        partes.append("<table><thead><tr><th>Coluna</th><th>Tipo físico</th></tr></thead><tbody>")
        for col in sorted(colunas.values(), key=lambda c: c["index"]):
            coluna, tipo = col["name"], col["type"]
            if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]{0,63}", coluna) or not re.fullmatch(r"[A-Za-z0-9_ (),\[\]]{1,64}", tipo):
                raise ValueError("nome ou tipo de coluna fora do formato da demonstração")
            partes.append(f"<tr><td>{escape(coluna)}</td><td>{escape(tipo)}</td></tr>")
        partes.append("</tbody></table></section>")
    return ("\n".join(partes) + "\n</html>\n").encode()


def _decisoes(plano):
    indices = {e["id"]: f"/evidence/{i}" for i, e in enumerate(plano["evidence"])}
    decisoes = {}
    for nome, regra in plano["rules"].items():
        papel = (regra.get("confirmed_by") or {}).get("role")
        if regra["status"] not in {"confirmada", "a_confirmar", "em_conflito"}:
            raise ValueError("estado de regra desconhecido no plano")
        decisoes[nome] = {"valor": regra["value"], "estado": regra["status"],
                          "papel_confirmador": papel if papel in {"financeiro", "operacao"} else None,
                          "evidencias": [indices[i] for i in regra["evidence_ids"]]}
    construcao = plano.get("construction")
    return {
        "plan_version": plano["plan_version"], "context_revision": plano["context_revision"],
        "construction_sha256": hashlib.sha256(construcao["document"].encode()).hexdigest() if construcao else None,
        "regras": decisoes,
    }


ETAPAS = {"plano", "ingestao", "construcao", "modelos", "avaliacao", "execucao"}
TIPOS_EVENTO = {
    "run_started", "plan_read", "source_profiled", "build_started", "file_written", "dbt_passed", "dbt_failed",
    "test_passed", "test_failed", "fix_started", "fix_applied", "fix_failed", "agent_finished", "tool_refused",
    "query_finished", "query_failed", "intervention_requested", "measurement_saved", "document_ready",
    "evaluation_finished", "run_failed",
}


def _eventos(revisao):
    linhas = []
    with _arquivo(revisao, "eventos.jsonl", 16 * 1024**2) as f:
        for linha in f:
            ev = json.loads(linha)
            if ev["run_id"] != revisao.name:
                raise ValueError("evento pertence a outra execução")
            if ev["step"] not in ETAPAS or ev["type"] not in TIPOS_EVENTO:
                continue
            ts = datetime.fromisoformat(ev["ts"])
            if ts.utcoffset() is None or type(ev["attempt"]) is not int or ev["attempt"] < 0:
                raise ValueError("evento sem instante ou tentativa válida")
            # As mensagens e `dados` podem conter conteúdo do cliente ou do fornecedor.
            publicavel = {"step": ev["step"], "type": ev["type"], "attempt": ev["attempt"], "ts": ts.isoformat()}
            linhas.append(json.dumps(publicavel, sort_keys=True).encode() + b"\n")
    return b"".join(linhas)


def _metricas(registro, campos, *, total_incompleto=False):
    valores = {}
    for k in campos:
        if k not in registro:
            continue
        n = registro[k]
        if k in {"custo_usd", "custo_centavos"} and (total_incompleto or n is None):
            valores[k] = None
        elif (type(n) is int or (type(n) is float and math.isfinite(n))) and n >= 0:
            valores[k] = n
        else:
            raise ValueError(f"valor inválido na medição: {k}")
    return valores


def _medicao(revisao, plano):
    medicao = json.loads(_ler(revisao, "medicao.json", 4 * 1024**2))
    if medicao.get("run_id") != revisao.name or medicao.get("plan_version", plano["plan_version"]) != plano["plan_version"]:
        raise ValueError("medição não corresponde à execução e versão revisadas")
    if medicao["executor"] not in {"roteirizado", "falso", "chat", "agente_sdk"}:
        raise ValueError("executor desconhecido na medição")
    if type(medicao["synthetic"]) is not bool or type(medicao["custo_completo"]) is not bool:
        raise ValueError("marcadores de medição inválidos")
    resultado = {k: medicao[k] for k in ("executor", "synthetic", "custo_completo")}
    consumo = ("turnos", "tokens_entrada", "tokens_saida", "tokens_cache_leitura", "duracao_s", "custo_usd", "custo_centavos")
    resultado.update(_metricas(medicao, ("tentativas", "builds", "correcoes", "duracao_etapa_s", *consumo),
                               total_incompleto=not medicao["custo_completo"]))
    tentativas = []
    for sessao in medicao["por_tentativa"]:
        if type(sessao["tentativa"]) is not int or sessao["tentativa"] < 0 or type(sessao["ok"]) is not bool:
            raise ValueError("tentativa inválida na medição")
        tentativas.append({"tentativa": sessao["tentativa"], "ok": sessao["ok"], **_metricas(sessao, consumo)})
    if len(tentativas) != medicao["tentativas"]:
        raise ValueError("contagem de tentativas inconsistente na medição")
    resultado["por_tentativa"] = tentativas
    return resultado


def _resumo(revisao, plano, dbt):
    laudo = json.loads(_ler(revisao, "avaliacao.json", 512 * 1024))
    controles = ("fontes_conferidas", "regras_conferidas", "landing_conferida", "linhagem_conferida")
    if (laudo.get("aprovado") is not True or laudo.get("classe") != "ok" or laudo.get("divergencias") != 0
            or any(laudo.get(c) is not True for c in controles) or laudo.get("empresa") != plano["dataset"]
            or laudo.get("nivel") != {"n0": 0, "n1": 1}[plano["ingestion"]["level"]]):
        raise ValueError("o pacote requer laudo aprovado para o cenário da execução")
    comparados = laudo["comparados"]
    if (set(comparados) != {"kpis", "por_pedido.csv", "por_viagem.csv"} or comparados["kpis"] != 3
            or any(type(n) is not int or n < 1 for n in comparados.values())):
        raise ValueError("laudo sem confronto de indicadores, pedidos e viagens")
    ingestao = json.loads(_ler(revisao, "ingestao.json", 8 * 1024**2))
    digest = ingestao["landing_manifest_sha256"]
    if not isinstance(digest, str) or not re.fullmatch(r"[a-f0-9]{64}", digest):
        raise ValueError("hash do manifesto da landing inválido")
    return {
        "run_id": revisao.name,
        **{k: plano[k] for k in ("schema_version", "plan_version", "project_id", "context_revision", "dataset", "destination")},
        "ingestion": {k: plano["ingestion"][k] for k in ("level", "window", "proposal_sha256")},
        "landing_manifest_sha256": digest,
        "dbt": dbt,
        "avaliacao": {k: laudo[k] for k in ("aprovado", "classe", "divergencias", "comparados", *controles)},
    }


def _preencher(arquivo, projeto, resultados, revisao, plano):
    modelos = {f"models/{nome}.sql": _ler(projeto, f"models/{nome}.sql", 256 * 1024) for nome in MODELOS}
    if set(plano["editable_models"]) != set(modelos):
        raise ValueError("modelos aprovados divergem dos modelos do pacote")
    validacao, manifest = _dbt(projeto, modelos)
    resumo = _resumo(revisao, plano, validacao)
    regras = {k: v["value"] for k, v in plano["rules"].items()}
    arquivo.writestr(_entrada_zip("README.md"), REPRODUZIR.encode())
    arquivo.writestr(_entrada_zip("regras.json"), _json(regras))
    arquivo.writestr(_entrada_zip("execucao.json"), _json(resumo))
    arquivo.writestr(_entrada_zip("decisoes.json"), _json(_decisoes(plano)))
    arquivo.writestr(_entrada_zip("medicao.json"), _json(_medicao(revisao, plano)))
    arquivo.writestr(_entrada_zip("eventos.jsonl"), _eventos(revisao))
    arquivo.writestr(_entrada_zip("docs/index.html"), _docs(projeto, manifest))
    for nome, dados in sorted(modelos.items()):
        arquivo.writestr(_entrada_zip("projeto/" + nome), dados)
    for nome in (*CONFIG, *(f"tests/{t}.sql" for t in TESTES)):
        arquivo.writestr(_entrada_zip("projeto/" + nome), _ler(projeto, nome, 256 * 1024))
    for nome in AMBIENTE:
        arquivo.writestr(_entrada_zip("ambiente/" + nome), _ler(REPO / "infra/sandbox", nome, 256 * 1024))
    if plano["ingestion"]["level"] == "n1":
        for nome in ("__init__.py", "__main__.py", "fontes.py"):
            caminho = "ingestao_n1/" + nome
            arquivo.writestr(_entrada_zip("referencia/" + caminho),
                             _ler(REPO / "services/execution/referencia", caminho, 256 * 1024))
    hashes = []
    for nome, limite in LIMITES.items():
        caminho = "resultados/" + nome
        digest = hashlib.sha256()
        lidos = 0
        with _arquivo(resultados, nome, limite) as src, arquivo.open(_entrada_zip(caminho), "w") as dst:
            while bloco := src.read(128 * 1024):
                lidos += len(bloco)
                if lidos > limite:
                    raise ValueError(f"resultado excede limite: {nome}")
                dst.write(bloco)
                digest.update(bloco)
        hashes.append(f"{digest.hexdigest()}  {caminho}\n")
    arquivo.writestr(_entrada_zip("resultados.sha256"), "".join(hashes).encode())


def montar_pacote(projeto: Path, resultados: Path, revisao: Path, plano: dict) -> Path:
    """Publica o ZIP na área privada de revisão. O registro decide a promoção ao destino."""
    projeto, resultados, revisao = Path(projeto), Path(resultados), Path(revisao)
    if resultados != revisao / "resultados" or plano["schema_version"] != "0.2.0":
        raise ValueError("o pacote exige os resultados da revisão v0.2 da execução")
    temporario = ".pacote-" + uuid.uuid4().hex
    with _diretorio(resultados) as pai:
        # Leitores do manifesto e outros produtores veem apenas o inventário definitivo.
        fcntl.flock(pai, fcntl.LOCK_EX)
        fd = os.open(temporario, os.O_CREAT | os.O_EXCL | os.O_RDWR, 0o600, dir_fd=pai)
        try:
            with os.fdopen(fd, "w+b") as lote:
                with zipfile.ZipFile(lote, "w", allowZip64=False) as arquivo:
                    _preencher(arquivo, projeto, resultados, revisao, plano)
                lote.flush()
                os.fsync(lote.fileno())
                if lote.tell() > LIMITE_PACOTE:
                    raise ValueError("o pacote ultrapassa o limite de promoção")
                # Publicação sem sobrescrever um pacote existente em uma revisão congelada.
                try:
                    os.link(temporario, PACOTE, src_dir_fd=pai, dst_dir_fd=pai, follow_symlinks=False)
                except FileExistsError:
                    lote.seek(0)
                    with _arquivo(resultados, PACOTE, LIMITE_PACOTE) as existente:
                        if hashlib.file_digest(lote, "sha256").digest() != hashlib.file_digest(existente, "sha256").digest():
                            raise ValueError("esta revisão já possui pacote com bytes diferentes")
        finally:
            os.unlink(temporario, dir_fd=pai)
            os.fsync(pai)
    return resultados / PACOTE
