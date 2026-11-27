"""Pacote de entrega (K13): a infra que o harness construiu, as decisões e a página de revisão.

`empacotar` monta `revisao/<run>/entrega/` só a partir do que a execução já produziu e do
plano aprovado no registro. Nada aqui chama LLM, lê `evaluation/golden/` ou inventa números:
cada valor exibido vem de um arquivo do pacote, e o pacote lista o hash de todos eles.

Os bytes de `resultados/` e `infra/` são conferidos contra o manifesto da aprovação 2 depois
de copiados. `decisoes.md`, `execucao.md` e `index.html` são derivados de forma determinística
(mesmas entradas, mesmos bytes).
"""

from __future__ import annotations

import csv
import json
import re
import shutil
import uuid
from datetime import datetime
from decimal import ROUND_HALF_EVEN, Decimal, InvalidOperation
from pathlib import Path

from . import artefatos
from .sandbox import RAIZ_REPO

PROJETO = RAIZ_REPO / "services/execution/pipeline/projeto"
# O que estava montado só leitura na sandbox e é preciso para reexecutar o projeto.
ARQUIVOS_PROJETO = ("dbt_project.yml", "profiles.yml", "ingerir.py", "exportar.py", "exportar_prata.py")
PASTAS_PROJETO = ("definicoes", "tests", "macros")
ESTADOS_EMPACOTAVEIS = {"aguardando_aprovacao_entrega", "entrega_autorizada", "entrega_rejeitada"}
LIMITE_CSV = 32 * 1024**2

# Pacote de domínio (logística): onde cada regra do plano vive no pipeline e qual teste dbt a
# protege. O plano não guarda esse vínculo; esta tabela é editorial e versionada aqui. O trecho
# de SQL é localizado por palavra-chave no modelo que o agente escreveu, então pode não ser
# encontrado (a página avisa). Regra sem teste dbt é garantida só pelo avaliador independente.
REGRAS_DOMINIO = {
    "deduplicar_cte": {"titulo": "Deduplicar CT-e pela chave", "modelo": "prata_ctes",
                       "palavras": ("row_number", "copia"),
                       "testes": ("chave_fiscal_unica", "documentos_conflitantes")},
    "excluir_cancelados": {"titulo": "Excluir CT-e cancelado", "modelo": "prata_ctes",
                           "palavras": ("110111", "'135'"), "testes": ()},
    "rateio_cte": {"titulo": "Ratear o frete do CT-e entre os pedidos", "modelo": "prata_rateios",
                   "palavras": ("peso_decimos_kg", "resto"), "testes": ("conservacao",)},
    "sem_data_realizada": {"titulo": "Entrega sem data realizada", "modelo": "ouro_por_pedido",
                           "palavras": ("data_realizada <=",), "testes": ()},
    "ocupacao_unidade": {"titulo": "Unidade da ocupação", "modelo": "ouro_por_viagem",
                         "palavras": ("capacidade_kg", "'kg'"), "testes": ()},
    "prazo_conta_sabado": {"titulo": "Prazo conta sábado", "modelo": "ouro_por_pedido",
                           "palavras": ("data_prevista",), "testes": ()},
    "excluir_tipos_viagem": {"titulo": "Tipos de viagem excluídos", "modelo": "ouro_por_pedido",
                             "palavras": ("tipo_viagem",), "testes": ("integridade_fontes",)},
    "no_prazo": {"titulo": "Entrega no prazo", "modelo": "ouro_por_pedido",
                 "palavras": ("as no_prazo",), "testes": ()},
    "completo": {"titulo": "Entrega completa", "modelo": "ouro_por_pedido",
                 "palavras": ("as completo",), "testes": ()},
}
METRICAS = {
    "custo_frete_por_entrega": {"titulo": "Custo de frete por entrega", "formato": "brl"},
    "otif_pct": {"titulo": "OTIF (no prazo e completo)", "formato": "pct"},
    "ocupacao_pct": {"titulo": "Ocupação da frota", "formato": "pct"},
}
ROTULOS_EVENTO = {
    "run_started": ("Execução iniciada", "info"),
    "source_profiled": ("Perfil da fonte", "info"),
    "file_written": ("Modelo escrito", "info"),
    "tool_refused": ("Recusado pela política", "recusa"),
    "build_started": ("Construção iniciada", "info"),
    "agent_finished": ("Agente terminou", "info"),
    "dbt_failed": ("dbt build falhou", "falha"),
    "dbt_passed": ("dbt build passou", "ok"),
    "test_failed": ("Testes falharam", "falha"),
    "test_passed": ("Testes passaram", "ok"),
    "fix_started": ("Correção iniciada", "info"),
    "fix_applied": ("Correção aplicada", "info"),
    "intervention_requested": ("Pediu intervenção humana", "falha"),
    "docs_generated": ("Documentação dbt gerada", "ok"),
    "docs_failed": ("Documentação dbt falhou", "falha"),
    "evaluation_finished": ("Avaliador independente", "ok"),
    "run_failed": ("Execução falhou", "falha"),
    "package_built": ("Pacote de entrega montado", "ok"),
    "package_failed": ("Pacote de entrega não gerado", "falha"),
}


# ---------------------------------------------------------------- leitura


def _json(caminho: Path):
    """Insumo opcional: ausente ou ilegível vira None e a seção mostra 'indisponível'."""
    try:
        return json.loads(caminho.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def _csv(caminho: Path) -> list[dict]:
    if caminho.stat().st_size > LIMITE_CSV:
        raise ValueError(f"{caminho.name} acima do limite")
    with caminho.open(encoding="utf-8", newline="") as fp:
        return list(csv.DictReader(fp))


def _eventos(caminho: Path) -> list[dict]:
    try:
        linhas = caminho.read_text(encoding="utf-8").splitlines()
    except OSError:
        return []
    eventos = []
    for linha in linhas:
        try:
            evento = json.loads(linha)
        except ValueError:
            continue
        if isinstance(evento, dict) and isinstance(evento.get("type"), str):
            eventos.append(evento)
    return eventos


def _modelos(infra: Path) -> dict[str, str]:
    pasta = infra / "models"
    if not pasta.is_dir():
        return {}
    return {str(p.relative_to(infra)): p.read_text(encoding="utf-8", errors="replace")
            for p in sorted(pasta.rglob("*.sql")) if p.is_file() and not p.is_symlink()}


def _instante(ts):
    try:
        return datetime.fromisoformat(ts)
    except (TypeError, ValueError):
        return None


# ---------------------------------------------------------------- números


def _dec(texto) -> Decimal:
    try:
        valor = Decimal(str(texto).strip() or "0")
    except InvalidOperation:
        raise ValueError(f"número inválido: {texto!r}") from None
    if not valor.is_finite():
        raise ValueError(f"número inválido: {texto!r}")
    return valor


def _refazer(chave, kpi, pedidos, viagens):
    """Refaz o KPI a partir de dados/*.csv, com o mesmo arredondamento (meio-par, 4 casas)."""
    try:
        if chave == "custo_frete_por_entrega":
            elegiveis = [p for p in pedidos if p["elegivel_custo"] == "1"]
            numerador = sum((_dec(p["custo_frete_rateado"]) for p in elegiveis), Decimal(0))
            denominador = len(elegiveis)
            fator, fonte = Decimal(1), "dados/por_pedido.csv"
            texto = ("soma de custo_frete_rateado dos pedidos com elegivel_custo = 1",
                     "pedidos com elegivel_custo = 1")
            numerador_txt = str(numerador.quantize(Decimal("0.01")))
        elif chave == "otif_pct":
            numerador = sum((_dec(p["otif"]) for p in pedidos), Decimal(0))
            denominador = sum(int(_dec(p["elegivel_otif"])) for p in pedidos)
            fator, fonte = Decimal(100), "dados/por_pedido.csv"
            texto = ("pedidos com otif = 1 (no prazo e completo)", "pedidos com elegivel_otif = 1")
            numerador_txt = str(int(numerador))
        elif chave == "ocupacao_pct":
            numerador = sum((_dec(v["carga"]) for v in viagens), Decimal(0))
            denominador = sum(_dec(v["capacidade"]) for v in viagens)
            fator, fonte = Decimal(100), "dados/por_viagem.csv"
            texto = ("soma da carga (kg) de todas as viagens", "soma da capacidade (kg) dos veículos")
            numerador_txt = str(numerador.normalize() if numerador == numerador.to_integral() else numerador)
        else:
            return None
        if not denominador:
            return None
        valor = (numerador * fator / Decimal(denominador)).quantize(Decimal("0.0001"), ROUND_HALF_EVEN)
        confere = kpi is not None and valor == _dec(kpi).quantize(Decimal("0.0001"), ROUND_HALF_EVEN)
        denominador_txt = int(denominador) if denominador == int(denominador) else str(denominador)
        return {"numerador": numerador_txt, "denominador": denominador_txt, "multiplicador": int(fator),
                "valor": str(valor), "confere": confere, "fonte": fonte,
                "numerador_descricao": texto[0], "denominador_descricao": texto[1]}
    except (KeyError, ValueError):
        return None


# ---------------------------------------------------------------- vínculos


def _trecho(modelos: dict[str, str], dominio: dict | None) -> dict | None:
    """Linhas do modelo capturado que casam as palavras-chave da regra, com uma de contexto."""
    if not dominio or not modelos:
        return None
    preferido = [c for c in modelos if Path(c).stem == dominio["modelo"]]
    for caminho in preferido + [c for c in modelos if c not in preferido]:
        linhas = modelos[caminho].splitlines()
        achadas = [i for i, linha in enumerate(linhas)
                   if any(p.lower() in linha.lower() for p in dominio["palavras"])]
        if achadas:
            visiveis = sorted({j for i in achadas for j in (i - 1, i, i + 1) if 0 <= j < len(linhas)})[:16]
            return {"arquivo": caminho, "localizado": True, "destaque": [i + 1 for i in achadas],
                    "linhas": [[j + 1, linhas[j]] for j in visiveis]}
    if preferido:
        linhas = modelos[preferido[0]].splitlines()
        return {"arquivo": preferido[0], "localizado": False, "destaque": [],
                "linhas": [[j + 1, linhas[j]] for j in range(min(12, len(linhas)))]}
    return None


def _testes(manifest, run_results) -> dict[str, dict]:
    """Testes do projeto pelo manifest do dbt (ou pelos arquivos, se ele faltar), com o status do build."""
    status = {}
    for r in (run_results or {}).get("results", []) if isinstance(run_results, dict) else []:
        if isinstance(r, dict) and isinstance(r.get("unique_id"), str):
            status[r["unique_id"]] = str(r.get("status", ""))
    testes = {}
    nos = (manifest or {}).get("nodes", {}) if isinstance(manifest, dict) else {}
    for uid, no in sorted(nos.items()):
        if isinstance(no, dict) and no.get("resource_type") == "test":
            sql = str(no.get("raw_code", ""))
            testes[str(no.get("name"))] = {"id": uid, "arquivo": str(no.get("original_file_path", "")), "sql": sql,
                                          "descricao": _descricao(sql), "status": status.get(uid)}
    if not testes:
        for arquivo in sorted((PROJETO / "tests").glob("*.sql")):
            sql = arquivo.read_text(encoding="utf-8")
            testes[arquivo.stem] = {"id": None, "arquivo": f"tests/{arquivo.name}", "sql": sql,
                                    "descricao": _descricao(sql), "status": None}
    return testes


def _descricao(sql: str) -> str:
    primeira = sql.lstrip().splitlines()[0] if sql.strip() else ""
    return primeira[2:].strip() if primeira.startswith("--") else ""


def _linhagem(manifest, catalog) -> dict | None:
    if not isinstance(manifest, dict):
        return None
    colunas = {}
    if isinstance(catalog, dict):
        for grupo in ("nodes", "sources"):
            for uid, no in (catalog.get(grupo) or {}).items():
                cols = (no or {}).get("columns") or {}
                colunas[uid] = [[str(c.get("name", n)), str(c.get("type", ""))]
                                for n, c in sorted(cols.items(), key=lambda x: (x[1] or {}).get("index", 0))]
    nos, arestas = {}, []
    todos = {**(manifest.get("sources") or {}), **(manifest.get("nodes") or {})}
    for uid, no in todos.items():
        if not isinstance(no, dict) or no.get("resource_type") not in ("model", "source", "test"):
            continue
        tipo = no["resource_type"]
        nos[uid] = {"id": uid, "nome": str(no.get("name", uid)), "tipo": tipo,
                    "arquivo": str(no.get("original_file_path", "")) if tipo != "source" else "",
                    "sql": str(no.get("raw_code", "")) if tipo == "model" else "",
                    "colunas": colunas.get(uid)}
        for origem in (no.get("depends_on") or {}).get("nodes", []):
            arestas.append([str(origem), uid])
    arestas = [a for a in arestas if a[0] in nos and a[1] in nos]
    return {"nos": nos, "arestas": arestas, "tem_catalogo": isinstance(catalog, dict)}


def _pedidos_e_ctes(pedidos: list[dict]):
    compactos, ctes = [], {}
    for p in pedidos:
        try:
            linhagem = json.loads(p.get("linhagem_cte") or "[]")
        except ValueError:
            linhagem = []
        fontes = []
        for item in linhagem if isinstance(linhagem, list) else []:
            if not isinstance(item, dict):
                continue
            chave = str(item.get("chave_cte", ""))
            fontes.append({"chave_cte": chave, "parcela_centavos": item.get("parcela_centavos")})
            cte = ctes.setdefault(chave, {"chave_cte": chave, "arquivo": str(item.get("arquivo", "")),
                                          "sha256": str(item.get("sha256", "")),
                                          "frete_centavos": item.get("frete_centavos"), "pedidos": []})
            cte["pedidos"].append({"pedido_id": p.get("pedido_id"), "peso_decimos_kg": p.get("peso_decimos_kg"),
                                   "parcela_centavos": item.get("parcela_centavos")})
        compactos.append({k: p.get(k, "") for k in (
            "pedido_id", "viagem_id", "tipo_viagem", "elegivel_custo", "custo_frete_rateado", "data_prevista",
            "data_realizada", "no_prazo", "completo", "otif", "qt_itens", "qt_entregue", "peso_decimos_kg",
            "arquivo_pedido", "linha_pedido", "arquivo_entrega", "linha_entrega", "chave_nfe")}
            | {"ctes": fontes})
    return compactos, ctes


def _exemplos(pedidos: list[dict], ctes: dict) -> list[dict]:
    """Pedidos reais que mostram cada caso; nenhum é inventado."""
    casos = (
        ("CT-e dividido entre pedidos (rateio por peso)",
         lambda p: any(len(ctes.get(c["chave_cte"], {}).get("pedidos", [])) > 1 for c in p["ctes"])),
        ("Sem CT-e válido (fora do custo)", lambda p: p["elegivel_custo"] == "0"),
        ("No prazo, mas incompleto (falha no OTIF)", lambda p: p["no_prazo"] == "1" and p["completo"] == "0"),
        ("Sem data realizada (conta como falha)", lambda p: not p["data_realizada"]),
        ("Atrasado", lambda p: p["no_prazo"] == "0" and bool(p["data_realizada"])),
    )
    exemplos = []
    for rotulo, criterio in casos:
        achado = next((p for p in pedidos if criterio(p)), None)
        if achado:
            exemplos.append({"rotulo": rotulo, "pedido_id": achado["pedido_id"]})
    return exemplos


def _linha_do_tempo(eventos: list[dict]) -> dict:
    inicio = _instante(eventos[0].get("ts")) if eventos else None
    fim = _instante(eventos[-1].get("ts")) if eventos else None
    itens, perfis = [], []
    for e in eventos:
        dados = e.get("dados") if isinstance(e.get("dados"), dict) else {}
        if e["type"] == "source_profiled":
            perfis.append(str(dados.get("fonte") or e.get("message", "")))
            continue
        rotulo, classe = ROTULOS_EVENTO.get(e["type"], (e["type"], "info"))
        detalhe = str(e.get("message", ""))
        if dados.get("caminho") and dados["caminho"] not in detalhe:
            detalhe = f"{detalhe} ({dados['caminho']})"
        if e["type"] == "tool_refused" and dados.get("origem"):
            detalhe = f"{detalhe} [barrado por: {dados['origem']}]"
        quando = _instante(e.get("ts"))
        itens.append({"t": _relativo(inicio, quando), "tipo": e["type"], "rotulo": rotulo, "classe": classe,
                      "detalhe": detalhe[:400], "tentativa": e.get("attempt"), "etapa": str(e.get("step", ""))})
    duracao = (fim - inicio).total_seconds() if inicio and fim else None
    return {"itens": itens, "perfis": perfis, "duracao_s": duracao,
            "recusas": sum(1 for e in eventos if e["type"] == "tool_refused"),
            "falhas": sum(1 for e in eventos if e["type"] in ("dbt_failed", "test_failed")),
            "correcoes": sum(1 for e in eventos if e["type"] == "fix_applied"),
            "escritas": sum(1 for e in eventos if e["type"] == "file_written")}


def _relativo(inicio, quando):
    if not inicio or not quando:
        return ""
    s = int((quando - inicio).total_seconds())
    return f"+{s // 60:02d}:{s % 60:02d}"


def duracao_texto(segundos) -> str:
    if segundos is None:
        return "indisponível"
    s = int(round(segundos))
    return f"{s // 60} min {s % 60} s" if s >= 60 else f"{s} s"


def moeda(valor, simbolo="R$") -> str:
    if valor is None:
        return "indisponível"
    texto = f"{Decimal(str(valor)).quantize(Decimal('0.01'), ROUND_HALF_EVEN):,.2f}"
    return f"{simbolo} " + texto.replace(",", "_").replace(".", ",").replace("_", ".")


# ---------------------------------------------------------------- dossiê


def montar_dossie(plano: dict, revisao: Path, run_id: str | None = None) -> dict:
    """Junta plano, resultados, laudo, eventos e infra num só dicionário, que é a fonte da página."""
    revisao = Path(revisao)
    kpis = (_json(revisao / "resultados/kpis.json") or {}).get("kpis") or {}
    pedidos = _csv(revisao / "resultados/por_pedido.csv")
    viagens = _csv(revisao / "resultados/por_viagem.csv")
    laudo = _json(revisao / "avaliacao.json")
    manifest = _json(revisao / "infra/target/manifest.json")
    catalog = _json(revisao / "infra/target/catalog.json")
    run_results = _json(revisao / "infra/target/run_results.json")
    medicao = _json(revisao / "medicao.json")
    eventos = _eventos(revisao / "eventos.jsonl")
    modelos = _modelos(revisao / "infra")
    testes = _testes(manifest, run_results)
    evidencias = {e["id"]: e for e in plano.get("evidence", [])}

    regras = []
    for chave, regra in plano["rules"].items():
        dominio = REGRAS_DOMINIO.get(chave)
        nomes_testes = list(dominio["testes"]) if dominio else []
        regras.append({
            "chave": chave, "titulo": dominio["titulo"] if dominio else chave, "valor": regra.get("value"),
            "status": regra.get("status"), "papel": (regra.get("confirmed_by") or {}).get("role"),
            "mapeada": dominio is not None,
            "evidencias": [{k: evidencias[i].get(k) for k in ("id", "source_id", "locator", "excerpt")}
                           for i in regra.get("evidence_ids", []) if i in evidencias],
            "metricas": [m for m, d in plano["metrics"].items() if chave in d.get("rule_keys", [])],
            "trecho": _trecho(modelos, dominio),
            "testes": [{"nome": n, **testes[n]} for n in nomes_testes if n in testes],
        })

    selo = _selo(laudo)
    metricas = []
    for chave, definicao in plano["metrics"].items():
        meta = METRICAS.get(chave, {"titulo": chave, "formato": "num"})
        metricas.append({
            "chave": chave, "titulo": meta["titulo"], "formato": meta["formato"], "valor": kpis.get(chave),
            "unidade": definicao.get("unit"), "formula": definicao.get("formula"),
            "denominador": definicao.get("denominator"), "grao": definicao.get("grain"),
            "aceite": definicao.get("acceptance", []), "regras": definicao.get("rule_keys", []),
            "refeito": _refazer(chave, kpis.get(chave), pedidos, viagens), "selo": selo,
        })

    compactos, ctes = _pedidos_e_ctes(pedidos)
    medicao = medicao if isinstance(medicao, dict) else {}
    return {
        "run_id": run_id or revisao.name, "project_id": plano.get("project_id"),
        "plan_version": plano.get("plan_version"), "dataset": plano.get("dataset"),
        "sintetico": bool(plano.get("synthetic", True)),
        "executor": medicao.get("executor"), "medicao": medicao,
        "kpis": metricas, "regras": regras, "testes": testes, "laudo": selo,
        "linhagem": _linhagem(manifest, catalog), "modelos": modelos,
        "pedidos": compactos, "ctes": ctes, "exemplos": _exemplos(compactos, ctes),
        "n_viagens": len(viagens), "tempo": _linha_do_tempo(eventos),
    }


def _selo(laudo) -> dict:
    """Só os campos de resumo do laudo; os `exemplos` de divergência não entram no pacote."""
    if not isinstance(laudo, dict):
        return {"estado": "nao_avaliado", "texto": "não avaliado"}
    comparados = laudo.get("comparados") if isinstance(laudo.get("comparados"), dict) else {}
    n_ped, n_via = comparados.get("por_pedido.csv"), comparados.get("por_viagem.csv")
    if laudo.get("aprovado") is True:
        texto = (f"conferido pelo avaliador independente: {laudo.get('divergencias', 0)} divergências em "
                 f"{n_ped} pedidos e {n_via} viagens")
        return {"estado": "aprovado", "texto": texto, "pedidos": n_ped, "viagens": n_via}
    return {"estado": "reprovado", "texto": f"recusado pelo avaliador independente ({laudo.get('classe')}, "
                                            f"{laudo.get('divergencias')} divergências)"}


# ---------------------------------------------------------------- documentos


def _valor_md(valor) -> str:
    return "`" + json.dumps(valor, ensure_ascii=False) + "`"


def decisoes_md(dossie: dict) -> str:
    partes = [
        "# Registro de decisões\n",
        f"Gerado do plano aprovado `{dossie['plan_version']}` (projeto `{dossie['project_id']}`, "
        f"lote `{dossie['dataset']}`). **Dados sintéticos.** Cada regra mostra o trecho da entrevista que a "
        "confirmou, as métricas que ela afeta e o que a garante.\n",
        "O vínculo regra → modelo → teste vem de uma tabela de domínio da Korda (`REGRAS_DOMINIO` em "
        "`entrega.py`), não do plano. Regra sem teste dbt é garantida pelo avaliador independente, que "
        "refaz o cálculo sem usar o pipeline.\n",
    ]
    for r in dossie["regras"]:
        partes.append(f"\n## {r['titulo']} (`{r['chave']}`)\n")
        partes.append(f"- **Valor:** {_valor_md(r['valor'])} ({r['status']}"
                      + (f", confirmada por: {r['papel']}" if r["papel"] else "") + ")")
        partes.append("- **Métricas afetadas:** " + (", ".join(f"`{m}`" for m in r["metricas"]) or "nenhuma"))
        if r["trecho"]:
            aviso = "" if r["trecho"]["localizado"] else " (trecho não localizado por palavra-chave)"
            partes.append(f"- **Onde está no pipeline:** `projeto_dbt/{r['trecho']['arquivo']}`{aviso}")
        if r["testes"]:
            partes.append("- **Teste que garante:** " + ", ".join(
                f"`projeto_dbt/{t['arquivo']}`" + (f" ({t['descricao']})" if t["descricao"] else "")
                for t in r["testes"]))
        else:
            partes.append("- **Teste que garante:** sem teste dbt; conferida pelo avaliador independente.")
        partes.append("- **Por quê (evidência):**")
        for ev in r["evidencias"]:
            trecho = " ".join(str(ev["excerpt"]).split())
            partes.append(f"  - `{ev['source_id']}`, {ev['locator']}:\n\n    > {trecho}\n")
        if not r["evidencias"]:
            partes.append("  - sem evidência registrada no plano.")
    return "\n".join(partes) + "\n"


def execucao_md(dossie: dict) -> str:
    t, m = dossie["tempo"], dossie["medicao"]
    sintetico = "sim" if m.get("synthetic", True) else "não"
    linhas = [
        "# Como o agente construiu\n",
        "Registro de uma execução passada, não ao vivo. Gerado de `eventos.jsonl` e `medicao.json`.\n",
        f"- **Execução:** `{dossie['run_id']}` (executor `{m.get('executor', 'indisponível')}`; "
        f"execução sintética, sem LLM real: {sintetico})",
        f"- **Tempo (primeiro ao último evento):** {duracao_texto(t['duracao_s'])}",
        f"- **Custo estimado:** {moeda(m.get('custo_usd'), 'US$')} "
        f"(≈ {moeda((m.get('custo_centavos') or 0) / 100 if m else None)}); "
        f"tokens: {m.get('tokens_entrada', 0)} de entrada, {m.get('tokens_saida', 0)} de saída",
        f"- **Modelos escritos:** {t['escritas']} · **falhas de build/teste:** {t['falhas']} · "
        f"**correções:** {t['correcoes']} · **recusas pela política (hook/ferramentas):** {t['recusas']}",
    ]
    if t["perfis"]:
        linhas.append(f"- **Fontes perfiladas antes de construir:** {', '.join(t['perfis'])}")
    linhas.append("\n## Linha do tempo\n")
    linhas.append("| Quando | Etapa | O que aconteceu | Detalhe |\n| --- | --- | --- | --- |")
    for item in t["itens"]:
        detalhe = item["detalhe"].replace("|", "\\|").replace("\n", " ")
        linhas.append(f"| {item['t']} | {item['etapa']} | {item['rotulo']} | {detalhe} |")
    if not t["itens"]:
        linhas.append("| | | eventos indisponíveis | |")
    return "\n".join(linhas) + "\n"


def readme_projeto(dossie: dict) -> str:
    return f"""# Projeto dbt entregue (execução `{dossie['run_id']}`)

**Dados sintéticos.** Modelos em `models/` foram escritos pelo executor `{dossie['executor']}` dentro da
sandbox; `tests/`, `definicoes/`, `macros/`, `ingerir.py` e `exportar.py` são os arquivos protegidos que
estavam montados somente leitura. `regras.json` traz os valores das regras do plano aprovado.

## Rodar de novo

O projeto usa os caminhos da sandbox (`/work/...`), então roda na mesma imagem (`docker build -t
korda-sandbox:dev infra/sandbox` no repositório Korda). `FONTES` é uma pasta com `erp/`, `tms/` e `cte/`
(o lote sintético: `python3 -m data.synthetic.generator.generate --empresa 01_demo`).

```bash
mkdir -p saida
docker run --rm -i --network none \\
  --mount type=bind,src="$PWD",dst=/work/projeto,readonly \\
  --mount type=bind,src="$FONTES",dst=/work/fontes,readonly \\
  --mount type=bind,src="$PWD/saida",dst=/work/saida \\
  --user "$(id -u):$(id -g)" \\
  korda-sandbox:dev sh -c 'python /work/projeto/ingerir.py < /work/projeto/regras.json \\
    && dbt build && python /work/projeto/exportar.py'
```

`dbt build` roda os modelos e os testes de `tests/`. Os resultados saem em `saida/resultados/` e podem ser
comparados com `../dados/`. O que cada teste garante está em `../decisoes.md`.
"""


# ---------------------------------------------------------------- pacote


def _copiar_projeto(destino: Path, revisao: Path, regras: dict) -> None:
    destino.mkdir()
    for nome in ARQUIVOS_PROJETO:
        shutil.copyfile(PROJETO / nome, destino / nome)
    for pasta in PASTAS_PROJETO:
        if (PROJETO / pasta).is_dir():
            shutil.copytree(PROJETO / pasta, destino / pasta, ignore=shutil.ignore_patterns("__pycache__"))
    shutil.copytree(revisao / "infra/models", destino / "models")
    (destino / "regras.json").write_text(json.dumps(regras, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def empacotar(registro, raiz: Path, run_id: str) -> Path:
    """Monta (ou remonta) `revisao/<run>/entrega/` para uma execução aprovada pelo avaliador."""
    from .pagina_entrega import renderizar

    if not isinstance(run_id, str) or not re.fullmatch(r"[a-z0-9][a-z0-9_-]{0,63}", run_id):
        raise ValueError("identificador de execução inválido")
    estado = registro.consultar(run_id)
    if estado["state"] not in ESTADOS_EMPACOTAVEIS:
        raise ValueError(f"execução em estado {estado['state']}: só se empacota execução aprovada pelo "
                         "avaliador e ainda não promovida")
    aprovado = estado["manifesto"]
    artefatos._validar(aprovado)
    if "infra" not in aprovado:
        raise ValueError("execução anterior à captura da infra: reexecute para gerar o pacote")
    plano = registro.plano_da_execucao(run_id)
    revisao = Path(raiz).resolve() / "revisao" / run_id
    staging = revisao / f".entrega-{uuid.uuid4().hex}"
    staging.mkdir(mode=0o700)
    try:
        # Copia e confere as cópias: o que entra no pacote é exatamente o que foi aprovado.
        shutil.copytree(revisao / "resultados", staging / "dados")
        _copiar_projeto(staging / "projeto_dbt", revisao, {k: r["value"] for k, r in plano["rules"].items()})
        (staging / "docs_dbt").mkdir()
        for caminho in aprovado["infra"]:
            if caminho.startswith("target/"):
                shutil.copyfile(revisao / "infra" / caminho, staging / "docs_dbt" / caminho.removeprefix("target/"))
        if (revisao / "infra/prata").is_dir():
            shutil.copytree(revisao / "infra/prata", staging / "dados/prata")
        _conferir_copias(staging, aprovado)

        dossie = montar_dossie(plano, revisao, run_id)
        (staging / "decisoes.md").write_text(decisoes_md(dossie), encoding="utf-8")
        (staging / "execucao.md").write_text(execucao_md(dossie), encoding="utf-8")
        (staging / "projeto_dbt/README.md").write_text(readme_projeto(dossie), encoding="utf-8")
        (staging / "index.html").write_text(renderizar(dossie), encoding="utf-8")
        manifesto = {"run_id": run_id, "plan_version": plano["plan_version"], "sintetico": True,
                     "arquivos": artefatos.inventario(staging), "aprovado": aprovado}
        (staging / "manifesto.json").write_text(json.dumps(manifesto, ensure_ascii=False, indent=2, sort_keys=True)
                                                + "\n", encoding="utf-8")
        destino = revisao / "entrega"
        antigo = None
        if destino.exists():
            antigo = revisao / f".entrega-antiga-{uuid.uuid4().hex}"
            destino.rename(antigo)
        staging.rename(destino)
        if antigo is not None:
            shutil.rmtree(antigo)
        return destino
    finally:
        if staging.exists():
            shutil.rmtree(staging)


def _conferir_copias(pacote: Path, aprovado: dict) -> None:
    dados = {c: m for c, m in artefatos.inventario(pacote / "dados").items() if not c.startswith("prata/")}
    if dados != aprovado["arquivos"]:
        raise ValueError("resultados da revisão diferem do manifesto aprovado")
    infra = {f"models/{c}": m for c, m in artefatos.inventario(pacote / "projeto_dbt/models").items()}
    infra |= {f"target/{c}": m for c, m in artefatos.inventario(pacote / "docs_dbt").items()}
    if (pacote / "dados/prata").is_dir():
        infra |= {f"prata/{c}": m for c, m in artefatos.inventario(pacote / "dados/prata").items()}
    if infra != aprovado["infra"]:
        raise ValueError("modelos ou target do dbt diferem do manifesto aprovado")
