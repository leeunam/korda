"""Página offline da entrega (`index.html`): da conversa ao número.

Um arquivo só, sem rede: CSS e JS embutidos, nenhuma URL externa. Todo texto vindo do plano,
da sandbox ou dos eventos passa por `html.escape`; os dados do drill-down vão num bloco
`application/json` com `<`, `>` e `&` escapados e são inseridos com `textContent`.
"""

from __future__ import annotations

import json
from html import escape

from .entrega import duracao_texto, moeda

LARGURA_NO, ALTURA_NO, PASSO_X, PASSO_Y = 176, 34, 228, 50


def e(valor) -> str:
    return escape("" if valor is None else str(valor), quote=True)


def _numero(valor, formato) -> str:
    if valor is None:
        return "indisponível"
    if formato == "brl":
        return moeda(valor)
    texto = f"{float(valor):,.2f}".replace(",", "_").replace(".", ",").replace("_", ".")
    return f"{texto}%" if formato == "pct" else texto


def _json_seguro(objeto) -> str:
    texto = json.dumps(objeto, ensure_ascii=False, separators=(",", ":"))
    return texto.replace("&", "\\u0026").replace("<", "\\u003c").replace(">", "\\u003e")


def _valor_regra(valor) -> str:
    if valor is True:
        return "sim"
    if valor is False:
        return "não"
    if valor == []:
        return "nenhum"
    return json.dumps(valor, ensure_ascii=False).strip('"')


# ---------------------------------------------------------------- KPIs e cadeia


def _selo_html(selo) -> str:
    classe = {"aprovado": "selo-ok", "reprovado": "selo-falha"}.get(selo["estado"], "selo-neutro")
    marca = {"aprovado": "✓", "reprovado": "✗"}.get(selo["estado"], "–")
    return f'<span class="selo {classe}"><b>{marca}</b> {e(selo["texto"])}</span>'


def _cards_kpi(dossie) -> str:
    cards = []
    for i, k in enumerate(dossie["kpis"]):
        cards.append(f"""
      <button class="kpi" type="button" data-kpi="{e(k['chave'])}" aria-pressed="{'true' if i == 0 else 'false'}">
        <span class="kpi-titulo">{e(k['titulo'])}</span>
        <span class="kpi-valor">{e(_numero(k['valor'], k['formato']))}</span>
        <span class="kpi-unidade">{e(k['unidade'])} · <code>{e(k['chave'])}</code></span>
        {_selo_html(k['selo'])}
        <span class="kpi-dica">ver de onde vem →</span>
      </button>""")
    return "".join(cards)


def _codigo(trecho) -> str:
    if not trecho:
        return '<p class="vazio">Modelo indisponível no pacote.</p>'
    destaque = set(trecho["destaque"])
    linhas, anterior = [], None
    for numero, texto in trecho["linhas"]:
        if anterior is not None and numero != anterior + 1:
            linhas.append('<span class="ln corte">⋯</span>')
        classe = "ln marcada" if numero in destaque else "ln"
        linhas.append(f'<span class="{classe}"><i>{numero}</i>{e(texto) or " "}</span>')
        anterior = numero
    aviso = ("" if trecho["localizado"] else
             '<p class="aviso">Trecho não localizado por palavra-chave: mostrando o início do modelo.</p>')
    return (f'<div class="arquivo">projeto_dbt/{e(trecho["arquivo"])} '
            f'<span class="rotulo-fraco">· trecho localizado por palavra-chave</span></div>'
            f'{aviso}<pre class="sql">{"".join(linhas)}</pre>')


def _garantia(regra, laudo) -> str:
    if regra["testes"]:
        itens = []
        for t in regra["testes"]:
            status = {"pass": ("passou no build", "ok"), "fail": ("falhou", "falha")}.get(
                t["status"] or "", (f"status: {t['status']}" if t["status"] else "status indisponível", "neutro"))
            itens.append(f'<li><code>projeto_dbt/{e(t["arquivo"])}</code> <span class="tag tag-{status[1]}">'
                         f'{e(status[0])}</span>'
                         + (f'<br><span class="rotulo-fraco">{e(t["descricao"])}</span>' if t["descricao"] else "")
                         + "</li>")
        return "<ul class='testes'>" + "".join(itens) + "</ul>"
    if laudo["estado"] == "aprovado":
        return ('<p>Sem teste dbt para esta regra. Ela é conferida pelo <b>avaliador independente</b>, '
                'que refaz o cálculo a partir das fontes, sem usar o pipeline.</p>')
    return '<p>Sem teste dbt para esta regra, e a execução <b>não foi avaliada</b>.</p>'


def _fio(regra, laudo) -> str:
    evidencias = "".join(
        f'<blockquote><p>“{e(" ".join(str(ev["excerpt"]).split()))}”</p>'
        f'<footer>{e(ev["source_id"])} · <b>{e(ev["locator"])}</b>'
        + (f' · {e(regra["papel"])}' if regra["papel"] else "") + "</footer></blockquote>"
        for ev in regra["evidencias"]) or '<p class="vazio">Sem evidência registrada no plano.</p>'
    return f"""
        <article class="fio">
          <h4>{e(regra['titulo'])} <code>{e(regra['chave'])}</code></h4>
          <ol class="passos">
            <li><span class="passo-rotulo">1 · O cliente disse</span>{evidencias}</li>
            <li><span class="passo-rotulo">2 · Regra confirmada</span>
              <p class="regra"><code>{e(regra['chave'])}</code> = <b>{e(_valor_regra(regra['valor']))}</b>
              <span class="tag tag-neutro">{e(regra['status'])}</span></p></li>
            <li><span class="passo-rotulo">3 · Onde está no SQL</span>{_codigo(regra['trecho'])}</li>
            <li><span class="passo-rotulo">4 · O que garante</span>{_garantia(regra, laudo)}</li>
          </ol>
        </article>"""


def _conta(k) -> str:
    r = k["refeito"]
    if not r:
        return '<p class="vazio">Não foi possível refazer este número a partir dos dados do pacote.</p>'
    mult = " × 100" if r["multiplicador"] == 100 else ""
    estado = ('<span class="tag tag-ok">✓ confere com dados/kpis.json</span>' if r["confere"] else
              '<span class="tag tag-falha">✗ diverge de dados/kpis.json</span>')
    return f"""
          <div class="conta">
            <div><span class="conta-n">{e(r['numerador'])}</span><span class="rotulo-fraco">{e(r['numerador_descricao'])}</span></div>
            <div class="conta-op">÷</div>
            <div><span class="conta-n">{e(r['denominador'])}</span><span class="rotulo-fraco">{e(r['denominador_descricao'])}</span></div>
            <div class="conta-op">{e(mult)} =</div>
            <div><span class="conta-n conta-final">{e(_numero(r['valor'], k['formato']))}</span>
            <span class="rotulo-fraco">refeito a partir de <code>{e(r['fonte'])}</code></span></div>
          </div>
          <p>{estado}</p>"""


def _cadeias(dossie) -> str:
    regras = {r["chave"]: r for r in dossie["regras"]}
    blocos = []
    for i, k in enumerate(dossie["kpis"]):
        fios = "".join(_fio(regras[c], dossie["laudo"]) for c in k["regras"] if c in regras) or \
            '<p class="vazio">O plano não liga regras a esta métrica.</p>'
        aceite = "".join(f"<li>{e(a)}</li>" for a in k["aceite"])
        blocos.append(f"""
      <section class="cadeia" id="cadeia-{e(k['chave'])}" {'' if i == 0 else 'hidden'}>
        <header class="cadeia-topo">
          <h3>{e(k['titulo'])}</h3>
          <dl class="definicao">
            <dt>Fórmula do plano</dt><dd>{e(k['formula'])}</dd>
            <dt>Denominador</dt><dd>{e(k['denominador'])}</dd>
            <dt>Grão</dt><dd>{e(k['grao'])}</dd>
          </dl>
        </header>
        <p class="rotulo-fraco">Cada regra abaixo é um fio que sai da entrevista e chega ao número.</p>
        <div class="fios">{fios}</div>
        <div class="numero-final">
          <span class="passo-rotulo">5 · O número</span>
          {_conta(k)}
          {f'<details><summary>Critérios de aceite do plano</summary><ul>{aceite}</ul></details>' if aceite else ''}
        </div>
      </section>""")
    return "".join(blocos)


# ---------------------------------------------------------------- linhagem


def _camada(no) -> str:
    if no["tipo"] == "source":
        return "bronze"
    if no["tipo"] == "test":
        return "teste"
    for prefixo in ("bronze", "prata", "ouro"):
        if no["nome"].startswith(prefixo):
            return prefixo
    return "modelo"


def _posicoes(linhagem):
    nos, arestas = linhagem["nos"], linhagem["arestas"]
    pais = {uid: [] for uid in nos}
    for origem, destino in arestas:
        pais[destino].append(origem)
    profundidade = {}

    def nivel(uid, caminho=()):
        if uid in profundidade:
            return profundidade[uid]
        if uid in caminho or nos[uid]["tipo"] == "source":
            return 0
        ps = [p for p in pais[uid] if nos[p]["tipo"] != "test"]
        profundidade[uid] = 1 + max((nivel(p, caminho + (uid,)) for p in ps), default=0) if ps else 0
        return profundidade[uid]

    colunas = {}
    modelos = [uid for uid, no in nos.items() if no["tipo"] == "model"]
    # Com nomes bronze_/prata_/ouro_, uma coluna por camada; senão, pela profundidade no grafo.
    por_camada = bool(modelos) and all(_camada(nos[u]) in ("bronze", "prata", "ouro") for u in modelos)
    ordem = {"bronze": 0, "prata": 1, "ouro": 2}
    for uid, no in nos.items():
        if no["tipo"] != "test":
            colunas.setdefault(ordem[_camada(no)] if por_camada else nivel(uid), []).append(uid)
    ultima = max(colunas, default=0) + 1
    testes = [uid for uid, no in nos.items() if no["tipo"] == "test"]
    if testes:
        colunas[ultima] = testes
    pos = {}
    for coluna, uids in colunas.items():
        for linha, uid in enumerate(sorted(uids, key=lambda u: nos[u]["nome"])):
            pos[uid] = (24 + coluna * PASSO_X, 44 + linha * PASSO_Y)
    return pos, colunas


def _svg(linhagem) -> str:
    pos, colunas = _posicoes(linhagem)
    largura = 24 + (max(colunas, default=0) + 1) * PASSO_X
    altura = 44 + max((len(v) for v in colunas.values()), default=1) * PASSO_Y + 10
    titulos = []
    for coluna, uids in sorted(colunas.items()):
        camadas = {_camada(linhagem["nos"][u]) for u in uids}
        nome = {"bronze": "Bronze (fontes)", "teste": "Testes"}.get(next(iter(camadas)) if len(camadas) == 1 else "",
                                                                    " / ".join(sorted(camadas)).capitalize())
        titulos.append(f'<text class="col-titulo" x="{24 + coluna * PASSO_X}" y="22">{e(nome)}</text>')
    linhas = []
    for origem, destino in linhagem["arestas"]:
        (x1, y1), (x2, y2) = pos[origem], pos[destino]
        x1, y1, y2 = x1 + LARGURA_NO, y1 + ALTURA_NO / 2, y2 + ALTURA_NO / 2
        meio = (x1 + x2) / 2
        classe = "aresta aresta-teste" if linhagem["nos"][destino]["tipo"] == "test" else "aresta"
        linhas.append(f'<path class="{classe}" d="M{x1:.0f},{y1:.0f} C{meio:.0f},{y1:.0f} {meio:.0f},{y2:.0f} '
                      f'{x2:.0f},{y2:.0f}"/>')
    nos = []
    for i, (uid, no) in enumerate(sorted(linhagem["nos"].items())):
        x, y = pos[uid]
        rotulo = no["nome"] if len(no["nome"]) <= 22 else no["nome"][:21] + "…"
        nos.append(f'<g class="no no-{_camada(no)}" data-no="{e(uid)}" data-painel="no-{i}" tabindex="0" '
                   f'role="button" aria-label="{e(no["tipo"])} {e(no["nome"])}">'
                   f'<rect x="{x}" y="{y}" width="{LARGURA_NO}" height="{ALTURA_NO}" rx="7"/>'
                   f'<text x="{x + 12}" y="{y + 21}">{e(rotulo)}</text></g>')
    return (f'<svg class="grafo" viewBox="0 0 {largura} {altura}" width="{largura}" height="{altura}" '
            f'role="img" aria-label="Linhagem do projeto dbt">{"".join(titulos)}{"".join(linhas)}{"".join(nos)}</svg>')


def _paineis_nos(linhagem) -> str:
    paineis = []
    for i, (uid, no) in enumerate(sorted(linhagem["nos"].items())):
        if no["colunas"]:
            colunas = "".join(f"<tr><td><code>{e(n)}</code></td><td>{e(t)}</td></tr>" for n, t in no["colunas"])
            tabela = f'<table class="colunas"><thead><tr><th>Coluna</th><th>Tipo</th></tr></thead>{colunas}</table>'
        elif no["tipo"] == "test":
            tabela = '<p class="rotulo-fraco">Teste: falha se a consulta devolver alguma linha.</p>'
        else:
            tabela = '<p class="vazio">colunas indisponíveis (sem catalog.json do dbt)</p>' \
                if not linhagem["tem_catalogo"] else '<p class="vazio">colunas indisponíveis para este nó</p>'
        sql = f'<pre class="sql sql-completo">{e(no["sql"])}</pre>' if no["sql"] else ""
        arquivo = f'<div class="arquivo">projeto_dbt/{e(no["arquivo"])}</div>' if no["arquivo"] else ""
        paineis.append(f'<div class="painel-no" id="no-{i}" hidden><h4>{e(no["nome"])} '
                       f'<span class="tag tag-neutro">{e(no["tipo"])}</span></h4>{arquivo}{tabela}{sql}</div>')
    return "".join(paineis)


def _secao_linhagem(dossie) -> str:
    linhagem = dossie["linhagem"]
    if not linhagem or not linhagem["nos"]:
        return '<p class="vazio">Linhagem indisponível: o pacote não tem o manifest.json do dbt.</p>'
    aviso = "" if linhagem["tem_catalogo"] else \
        '<p class="aviso">catalog.json indisponível: colunas indisponíveis nos nós.</p>'
    return f"""{aviso}
      <div class="linhagem">
        <div class="grafo-caixa">{_svg(linhagem)}</div>
        <aside class="painel" aria-live="polite">
          <p class="vazio" id="no-vazio">Clique num nó para ver colunas e SQL.</p>{_paineis_nos(linhagem)}
        </aside>
      </div>"""


# ---------------------------------------------------------------- agente


def _secao_agente(dossie) -> str:
    t, m = dossie["tempo"], dossie["medicao"]
    custo_brl = (m.get("custo_centavos") or 0) / 100 if m else None
    numeros = [
        ("Tempo", duracao_texto(t["duracao_s"])),
        ("Custo estimado", f"{moeda(m.get('custo_usd'), 'US$')}" if m else "indisponível"),
        ("Modelos escritos", t["escritas"]),
        ("Falhas de build/teste", t["falhas"]),
        ("Correções", t["correcoes"]),
        ("Recusas da política", t["recusas"]),
    ]
    cartoes = "".join(f'<div class="estat"><span>{e(v)}</span><small>{e(r)}</small></div>' for r, v in numeros)
    itens = "".join(
        f'<li class="ev ev-{e(i["classe"])}"><time>{e(i["t"])}</time><span class="ev-rotulo">{e(i["rotulo"])}'
        + (f' <small>tentativa {e(i["tentativa"])}</small>' if i["tentativa"] and i["tentativa"] != 1 else "")
        + f'</span><span class="ev-detalhe">{e(i["detalhe"])}</span></li>'
        for i in t["itens"]) or '<li class="vazio">Eventos indisponíveis.</li>'
    perfis = (f'<p class="rotulo-fraco">Antes de construir, o agente perfilou as fontes: {e(", ".join(t["perfis"]))}.</p>'
              if t["perfis"] else "")
    sintetico = ("Execução sintética (executor sem LLM real): tempo e custo não medem um modelo de linguagem."
                 if m.get("synthetic", True) else "")
    return f"""
      <p class="aviso-passado">Registro de uma execução passada (<code>{e(dossie['run_id'])}</code>, executor
        <code>{e(dossie['executor'])}</code>). Não é execução ao vivo. {e(sintetico)}</p>
      <div class="estats">{cartoes}</div>
      <p class="rotulo-fraco">≈ {e(moeda(custo_brl))} na taxa configurada da execução.</p>
      {perfis}
      <ol class="tempo">{itens}</ol>"""


# ---------------------------------------------------------------- leve para casa


def _secao_casa(dossie) -> str:
    linhas = []
    for r in dossie["regras"]:
        garante = ", ".join(f"<code>{e(t['arquivo'])}</code>" for t in r["testes"]) or "avaliador independente"
        linhas.append(f"<tr><td><code>{e(r['chave'])}</code></td><td>{e(_valor_regra(r['valor']))}</td>"
                      f"<td>{garante}</td></tr>")
    return f"""
      <div class="duas">
        <div>
          <h4>O que tem no pacote</h4>
          <ul class="arvore">
            <li><code>projeto_dbt/</code>: modelos escritos pelo agente, testes protegidos e <code>README.md</code></li>
            <li><code>dados/</code>: <code>kpis.json</code>, <code>por_pedido.csv</code>, <code>por_viagem.csv</code></li>
            <li><code>docs_dbt/</code>: manifest, catalog e run_results do dbt</li>
            <li><code>decisoes.md</code>: cada regra com a evidência e o teste</li>
            <li><code>execucao.md</code>: o que o agente fez</li>
            <li><code>manifesto.json</code>: sha256 de cada arquivo</li>
          </ul>
          <h4>Rodar de novo</h4>
          <pre class="sql">cd projeto_dbt
# ver README.md: mesma imagem da sandbox, sem rede
python /work/projeto/ingerir.py &lt; regras.json
dbt build          # modelos + testes
python /work/projeto/exportar.py</pre>
        </div>
        <div>
          <h4>Que teste garante cada decisão</h4>
          <table class="colunas"><thead><tr><th>Regra</th><th>Valor</th><th>Garantida por</th></tr></thead>
          {''.join(linhas)}</table>
        </div>
      </div>"""


# ---------------------------------------------------------------- página


def renderizar(dossie: dict) -> str:
    dados = {"pedidos": dossie["pedidos"], "ctes": dossie["ctes"], "exemplos": dossie["exemplos"]}
    exemplos = "".join(f'<button type="button" class="chip" data-pedido="{e(x["pedido_id"])}">{e(x["rotulo"])}</button>'
                       for x in dossie["exemplos"])
    selo = dossie["laudo"]
    return f"""<!doctype html>
<html lang="pt-BR">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Korda · entrega {e(dossie['run_id'])}</title>
<style>{CSS}</style>
</head>
<body>
<div class="faixa" role="note"><b>DADOS SINTÉTICOS</b> · registro de uma execução passada · nada aqui é dado real
  de cliente nem medida de resultado financeiro</div>
<main>
  <header class="topo">
    <p class="marca">Korda · entrega da infra de dados</p>
    <h1>Da conversa ao número</h1>
    <p class="sub">Projeto <code>{e(dossie['project_id'])}</code> · lote <code>{e(dossie['dataset'])}</code> ·
      plano <code title="{e(dossie['plan_version'])}">{e(str(dossie['plan_version'])[:12])}</code> ·
      execução <code>{e(dossie['run_id'])}</code></p>
    <p class="sub">{_selo_html(selo)}</p>
  </header>

  <section aria-labelledby="t-kpis">
    <h2 id="t-kpis">Os três indicadores</h2>
    <div class="kpis">{_cards_kpi(dossie)}</div>
  </section>

  <section aria-labelledby="t-cadeia" class="bloco">
    <h2 id="t-cadeia">De onde vem cada número</h2>
    {_cadeias(dossie)}
  </section>

  <section aria-labelledby="t-pedido" class="bloco">
    <h2 id="t-pedido">Confira um pedido até o arquivo de origem</h2>
    <p class="rotulo-fraco">{e(len(dossie['pedidos']))} pedidos em <code>dados/por_pedido.csv</code>. Escolha um caso
      ou digite o número do pedido.</p>
    <div class="busca">{exemplos}
      <label><span class="sr">Pedido</span><input id="pedido" list="lista-pedidos" placeholder="pedido_id"
        autocomplete="off"></label><datalist id="lista-pedidos"></datalist>
    </div>
    <div id="pedido-detalhe" class="pedido" aria-live="polite"></div>
  </section>

  <section aria-labelledby="t-linhagem" class="bloco">
    <h2 id="t-linhagem">Linhagem: fontes → prata → ouro</h2>
    <p class="rotulo-fraco">Desenhada a partir do <code>manifest.json</code> do dbt (<code>depends_on</code>).</p>
    {_secao_linhagem(dossie)}
  </section>

  <section aria-labelledby="t-agente" class="bloco">
    <h2 id="t-agente">Como o agente construiu</h2>
    {_secao_agente(dossie)}
  </section>

  <section aria-labelledby="t-casa" class="bloco">
    <h2 id="t-casa">Leve para casa</h2>
    {_secao_casa(dossie)}
  </section>
  <footer class="rodape">Gerado por código a partir do plano aprovado e dos arquivos da execução, sem chamadas de LLM.
    Os hashes de todos os arquivos estão em <code>manifesto.json</code>.</footer>
</main>
<script type="application/json" id="dados">{_json_seguro(dados)}</script>
<script>{JS}</script>
</body>
</html>
"""


CSS = """
:root{--papel:#f5f2ec;--cartao:#fffdf9;--tinta:#1c1a17;--fraco:#6b655c;--linha:#ddd6ca;--acento:#0e5f59;
--acento-claro:#e1efec;--ok:#2d6a31;--ok-fundo:#e5f1e3;--falha:#a3261b;--falha-fundo:#f8e3e0;--ambar:#f2c14e;
--marca:#fff2c2;--bronze:#a86b32;--prata:#6f7d86;--ouro:#b38a12;--teste:#5d4a8a;color-scheme:light}
@media (prefers-color-scheme:dark){:root{--papel:#151412;--cartao:#1f1d1a;--tinta:#ece7de;--fraco:#a39c90;
--linha:#3a3631;--acento:#5cc2b6;--acento-claro:#1d3532;--ok:#86c98b;--ok-fundo:#1e2f1f;--falha:#f08a7f;
--falha-fundo:#3a1f1c;--marca:#3d3416;color-scheme:dark}}
*{box-sizing:border-box}
body{margin:0;background:var(--papel);color:var(--tinta);font:15px/1.55 system-ui,-apple-system,"Segoe UI",Roboto,
"Helvetica Neue",Arial,sans-serif}
code,pre,time{font-family:ui-monospace,"SF Mono",Menlo,Consolas,"Liberation Mono",monospace;font-size:.88em}
.faixa{position:sticky;top:0;z-index:5;background:var(--ambar);color:#1c1a17;padding:.45rem 1rem;text-align:center;
font-size:.85rem;letter-spacing:.02em}
main{max-width:1180px;margin:0 auto;padding:1.5rem 1rem 4rem}
h1,h2,h3{font-family:"Iowan Old Style","Palatino Linotype",Palatino,Georgia,serif;font-weight:600;line-height:1.2}
h1{font-size:2.6rem;margin:.2rem 0 .4rem}
h2{font-size:1.55rem;margin:0 0 .6rem}
h3{font-size:1.3rem;margin:0}
h4{margin:.2rem 0 .5rem;font-size:1rem}
.marca{text-transform:uppercase;letter-spacing:.14em;font-size:.75rem;color:var(--acento);margin:0}
.sub{color:var(--fraco);margin:.2rem 0}
.bloco{margin-top:3rem;border-top:1px solid var(--linha);padding-top:1.5rem}
.rotulo-fraco{color:var(--fraco);font-size:.85rem;display:block}
.vazio{color:var(--fraco);font-style:italic}
.aviso{background:var(--marca);padding:.4rem .7rem;border-radius:6px;font-size:.85rem}
.aviso-passado{border-left:4px solid var(--ambar);padding:.3rem .8rem;background:var(--cartao)}
.kpis{display:grid;grid-template-columns:repeat(auto-fit,minmax(260px,1fr));gap:1rem}
.kpi{all:unset;cursor:pointer;display:flex;flex-direction:column;gap:.35rem;background:var(--cartao);
border:1px solid var(--linha);border-radius:14px;padding:1.1rem 1.2rem;transition:border-color .15s,box-shadow .15s}
.kpi:hover{border-color:var(--acento)}
.kpi:focus-visible{outline:3px solid var(--acento);outline-offset:2px}
.kpi[aria-pressed=true]{border-color:var(--acento);box-shadow:0 0 0 3px var(--acento-claro)}
.kpi-titulo{font-weight:600}
.kpi-valor{font-family:"Iowan Old Style",Georgia,serif;font-size:2.5rem;line-height:1.1;font-variant-numeric:tabular-nums}
.kpi-unidade{color:var(--fraco);font-size:.8rem}
.kpi-dica{color:var(--acento);font-size:.85rem;margin-top:.2rem}
.selo{display:inline-block;font-size:.78rem;border-radius:999px;padding:.15rem .6rem;line-height:1.4}
.selo-ok{background:var(--ok-fundo);color:var(--ok)}
.selo-falha{background:var(--falha-fundo);color:var(--falha)}
.selo-neutro{background:var(--linha);color:var(--tinta)}
.tag{display:inline-block;font-size:.75rem;border-radius:5px;padding:.05rem .45rem;margin-left:.3rem;
background:var(--linha)}
.tag-ok{background:var(--ok-fundo);color:var(--ok)}
.tag-falha{background:var(--falha-fundo);color:var(--falha)}
.cadeia-topo{display:grid;grid-template-columns:minmax(180px,1fr) 2fr;gap:1rem;align-items:start;margin-bottom:.6rem}
.definicao{display:grid;grid-template-columns:max-content 1fr;gap:.2rem .8rem;margin:0;font-size:.88rem}
.definicao dt{color:var(--fraco)}
.definicao dd{margin:0}
.fios{display:grid;gap:1rem}
.fio{background:var(--cartao);border:1px solid var(--linha);border-radius:14px;padding:1rem 1.2rem}
.fio h4 code{color:var(--fraco);font-weight:400}
.passos{list-style:none;margin:0;padding:0 0 0 1.1rem;border-left:2px solid var(--acento-claro);display:grid;gap:.9rem}
.passos>li{position:relative}
.passos>li::before{content:"";position:absolute;left:-1.47rem;top:.35rem;width:.6rem;height:.6rem;border-radius:50%;
background:var(--acento)}
.passo-rotulo{display:block;font-size:.72rem;text-transform:uppercase;letter-spacing:.1em;color:var(--acento);
margin-bottom:.25rem;font-weight:600}
blockquote{margin:.2rem 0;padding:.5rem .9rem;border-left:3px solid var(--ambar);background:var(--papel);
border-radius:0 8px 8px 0}
blockquote p{margin:0;font-family:"Iowan Old Style",Georgia,serif;font-size:1.02rem}
blockquote footer{font-size:.78rem;color:var(--fraco);margin-top:.3rem}
.regra{margin:0}
.arquivo{font-family:ui-monospace,Menlo,Consolas,monospace;font-size:.78rem;color:var(--fraco);margin-bottom:.2rem}
pre.sql{background:#1b1f23;color:#e6e1d6;border-radius:9px;padding:.6rem 0;margin:.2rem 0;overflow-x:auto;
font-size:.8rem;line-height:1.5}
pre.sql-completo{padding:.6rem .8rem;max-height:340px}
.ln{display:block;padding:0 .8rem;white-space:pre}
.ln i{display:inline-block;width:2.4rem;color:#7f786c;font-style:normal;user-select:none}
.ln.marcada{background:#3b3413;box-shadow:inset 3px 0 0 var(--ambar)}
.ln.corte{color:#7f786c}
.testes{margin:0;padding-left:1.1rem}
.numero-final{margin-top:1.1rem;background:var(--cartao);border:2px solid var(--acento);border-radius:14px;
padding:1rem 1.2rem}
.conta{display:flex;flex-wrap:wrap;align-items:center;gap:.6rem 1rem}
.conta>div{display:flex;flex-direction:column}
.conta-n{font-family:"Iowan Old Style",Georgia,serif;font-size:1.6rem;font-variant-numeric:tabular-nums}
.conta-final{color:var(--acento);font-size:2rem}
.conta-op{font-size:1.4rem;color:var(--fraco)}
.busca{display:flex;flex-wrap:wrap;gap:.5rem;align-items:center;margin:.6rem 0 1rem}
.chip{border:1px solid var(--linha);background:var(--cartao);color:var(--tinta);border-radius:999px;
padding:.3rem .8rem;cursor:pointer;font:inherit;font-size:.85rem}
.chip:hover,.chip[aria-pressed=true]{border-color:var(--acento);color:var(--acento)}
input{font:inherit;padding:.35rem .6rem;border-radius:8px;border:1px solid var(--linha);background:var(--cartao);
color:var(--tinta);width:11rem}
.sr{position:absolute;width:1px;height:1px;overflow:hidden;clip:rect(0 0 0 0)}
.pedido{display:grid;grid-template-columns:repeat(auto-fit,minmax(300px,1fr));gap:1rem}
.cartao{background:var(--cartao);border:1px solid var(--linha);border-radius:14px;padding:1rem 1.2rem}
.cartao dl{display:grid;grid-template-columns:max-content 1fr;gap:.15rem .8rem;margin:0;font-size:.9rem}
.cartao dt{color:var(--fraco)}
.cartao dd{margin:0;font-variant-numeric:tabular-nums}
table.colunas{border-collapse:collapse;width:100%;font-size:.85rem}
table.colunas th,table.colunas td{text-align:left;border-bottom:1px solid var(--linha);padding:.3rem .4rem}
tr.este td{background:var(--acento-claro);font-weight:600}
.hash{word-break:break-all;font-size:.75rem;color:var(--fraco)}
.linhagem{display:grid;grid-template-columns:1fr;gap:1rem}
.grafo-caixa{overflow-x:auto;background:var(--cartao);border:1px solid var(--linha);border-radius:14px;padding:.4rem}
.grafo{display:block;max-width:none}
.col-titulo{font-size:12px;fill:var(--fraco);letter-spacing:.06em;text-transform:uppercase}
.aresta{fill:none;stroke:var(--linha);stroke-width:1.6}
.aresta-teste{stroke-dasharray:4 3}
.no{cursor:pointer}
.no rect{fill:var(--cartao);stroke-width:2}
.no text{font-size:12.5px;fill:var(--tinta);font-family:ui-monospace,Menlo,Consolas,monospace}
.no-bronze rect{stroke:var(--bronze)}
.no-prata rect{stroke:var(--prata)}
.no-ouro rect{stroke:var(--ouro);stroke-width:2.6}
.no-teste rect{stroke:var(--teste);stroke-dasharray:4 2}
.no-modelo rect{stroke:var(--acento)}
.no:hover rect,.no:focus rect,.no.ativo rect{fill:var(--acento-claro)}
.no:focus{outline:none}
.painel{background:var(--cartao);border:1px solid var(--linha);border-radius:14px;padding:1rem}
.estats{display:grid;grid-template-columns:repeat(auto-fit,minmax(140px,1fr));gap:.7rem;margin:1rem 0 .3rem}
.estat{background:var(--cartao);border:1px solid var(--linha);border-radius:12px;padding:.7rem .9rem;display:flex;
flex-direction:column}
.estat span{font-family:"Iowan Old Style",Georgia,serif;font-size:1.5rem}
.estat small{color:var(--fraco)}
.tempo{list-style:none;padding:0;margin:1rem 0 0;border-left:2px solid var(--linha)}
.ev{display:grid;grid-template-columns:4.2rem 15rem 1fr;gap:.6rem;padding:.35rem .8rem;position:relative;
font-size:.9rem}
.ev::before{content:"";position:absolute;left:-.4rem;top:.7rem;width:.6rem;height:.6rem;border-radius:50%;
background:var(--fraco)}
.ev-ok::before{background:var(--ok)}
.ev-falha::before{background:var(--falha)}
.ev-recusa::before{background:var(--ambar);box-shadow:0 0 0 2px var(--falha)}
.ev-recusa .ev-rotulo{color:var(--falha);font-weight:600}
.ev time{color:var(--fraco)}
.ev-detalhe{color:var(--fraco);word-break:break-word}
.duas{display:grid;grid-template-columns:repeat(auto-fit,minmax(320px,1fr));gap:1.5rem}
.arvore{padding-left:1.1rem}
details{margin-top:.6rem}
summary{cursor:pointer;color:var(--acento)}
.rodape{margin-top:3rem;color:var(--fraco);font-size:.82rem;border-top:1px solid var(--linha);padding-top:1rem}
@media (max-width:760px){h1{font-size:2rem}.cadeia-topo,.linhagem{grid-template-columns:1fr}
.ev{grid-template-columns:3.6rem 1fr}.ev-detalhe{grid-column:2}}
"""

JS = r"""
(function(){
  var dados = JSON.parse(document.getElementById('dados').textContent);
  function el(tag, attrs, filhos){
    var n = document.createElement(tag);
    if (attrs) for (var k in attrs) { if (k === 'texto') n.textContent = attrs[k]; else n.setAttribute(k, attrs[k]); }
    (filhos || []).forEach(function(f){ if (f) n.appendChild(typeof f === 'string' ? document.createTextNode(f) : f); });
    return n;
  }
  function reais(centavos){
    if (centavos === null || centavos === undefined || centavos === '') return 'indisponível';
    var v = Number(centavos) / 100;
    return 'R$ ' + v.toLocaleString('pt-BR', {minimumFractionDigits: 2, maximumFractionDigits: 2});
  }
  function kg(decimos){ return (Number(decimos) / 10).toLocaleString('pt-BR') + ' kg'; }
  function simnao(v){ return v === '1' ? 'sim' : (v === '0' ? 'não' : v); }

  // KPIs: um clique mostra a cadeia daquele indicador.
  var kpis = document.querySelectorAll('.kpi');
  kpis.forEach(function(b){
    b.addEventListener('click', function(){
      kpis.forEach(function(o){ o.setAttribute('aria-pressed', String(o === b)); });
      document.querySelectorAll('.cadeia').forEach(function(c){ c.hidden = c.id !== 'cadeia-' + b.dataset.kpi; });
      document.getElementById('t-cadeia').scrollIntoView({behavior: 'smooth', block: 'start'});
    });
  });

  // Linhagem: nó clicado abre o painel com colunas e SQL.
  var nos = document.querySelectorAll('.no');
  function abrir(g){
    nos.forEach(function(o){ o.classList.toggle('ativo', o === g); });
    document.querySelectorAll('.painel-no').forEach(function(p){ p.hidden = p.id !== g.dataset.painel; });
    var vazio = document.getElementById('no-vazio'); if (vazio) vazio.hidden = true;
  }
  nos.forEach(function(g){
    g.addEventListener('click', function(){ abrir(g); });
    g.addEventListener('keydown', function(ev){ if (ev.key === 'Enter' || ev.key === ' ') { ev.preventDefault(); abrir(g); } });
  });

  // Drill-down por pedido.
  var porId = {};
  var lista = document.getElementById('lista-pedidos');
  dados.pedidos.forEach(function(p){ porId[p.pedido_id] = p; });
  dados.pedidos.slice(0, 5000).forEach(function(p){ lista.appendChild(el('option', {value: p.pedido_id})); });
  var alvo = document.getElementById('pedido-detalhe');
  var campo = document.getElementById('pedido');

  function linhaDl(dl, rotulo, valor){ dl.appendChild(el('dt', {texto: rotulo})); dl.appendChild(el('dd', {texto: valor})); }

  function mostrar(id){
    var p = porId[id];
    alvo.textContent = '';
    document.querySelectorAll('.chip').forEach(function(c){ c.setAttribute('aria-pressed', String(c.dataset.pedido === id)); });
    if (!p) { alvo.appendChild(el('p', {'class': 'vazio', texto: 'Pedido não encontrado em dados/por_pedido.csv.'})); return; }
    var dl = el('dl');
    linhaDl(dl, 'Viagem', p.viagem_id + ' (' + p.tipo_viagem + ')');
    linhaDl(dl, 'Prazo / realizada', p.data_prevista + ' / ' + (p.data_realizada || 'sem data'));
    linhaDl(dl, 'Itens pedidos / entregues', p.qt_itens + ' / ' + p.qt_entregue);
    linhaDl(dl, 'No prazo', simnao(p.no_prazo));
    linhaDl(dl, 'Completo', simnao(p.completo));
    linhaDl(dl, 'OTIF', simnao(p.otif));
    linhaDl(dl, 'Peso', kg(p.peso_decimos_kg));
    linhaDl(dl, 'Entra no custo', simnao(p.elegivel_custo));
    linhaDl(dl, 'Frete rateado', p.elegivel_custo === '1' ? reais(Math.round(Number(p.custo_frete_rateado) * 100)) : '—');
    var origem = el('dl');
    linhaDl(origem, 'Pedido', p.arquivo_pedido + ', linha ' + p.linha_pedido);
    linhaDl(origem, 'Entrega', p.arquivo_entrega + ', linha ' + p.linha_entrega);
    linhaDl(origem, 'NF-e', p.chave_nfe);
    alvo.appendChild(el('div', {'class': 'cartao'}, [el('h4', {texto: 'Pedido ' + p.pedido_id}), dl,
      el('h4', {texto: 'De onde veio (fonte, linha do CSV)'}), origem]));

    var caixa = el('div', {'class': 'cartao'}, [el('h4', {texto: 'Frete: CT-e de origem e rateio por peso'})]);
    if (!p.ctes.length) {
      caixa.appendChild(el('p', {'class': 'vazio', texto: 'Nenhum CT-e válido cobre este pedido: ele fica fora do custo por entrega.'}));
    }
    p.ctes.forEach(function(ref){
      var c = dados.ctes[ref.chave_cte];
      if (!c) return;
      var info = el('dl');
      linhaDl(info, 'Chave', c.chave_cte);
      linhaDl(info, 'Arquivo XML', c.arquivo);
      linhaDl(info, 'Frete do CT-e', reais(c.frete_centavos));
      caixa.appendChild(info);
      caixa.appendChild(el('p', {'class': 'hash', texto: 'sha256 ' + c.sha256}));
      var corpo = el('tbody');
      var soma = 0, peso = 0;
      c.pedidos.forEach(function(o){ peso += Number(o.peso_decimos_kg); });
      c.pedidos.forEach(function(o){
        soma += Number(o.parcela_centavos);
        var pct = peso ? (Number(o.peso_decimos_kg) / peso * 100).toLocaleString('pt-BR', {maximumFractionDigits: 1}) + '%' : '—';
        corpo.appendChild(el('tr', o.pedido_id === p.pedido_id ? {'class': 'este'} : null, [
          el('td', {texto: o.pedido_id}), el('td', {texto: kg(o.peso_decimos_kg)}), el('td', {texto: pct}),
          el('td', {texto: reais(o.parcela_centavos)})]));
      });
      caixa.appendChild(el('table', {'class': 'colunas'}, [
        el('thead', null, [el('tr', null, [el('th', {texto: 'Pedido'}), el('th', {texto: 'Peso'}),
          el('th', {texto: 'Parte do peso'}), el('th', {texto: 'Parcela'})])]), corpo]));
      var confere = soma === Number(c.frete_centavos);
      caixa.appendChild(el('p', null, [el('span', {'class': 'tag ' + (confere ? 'tag-ok' : 'tag-falha'),
        texto: (confere ? '✓ ' : '✗ ') + 'soma das parcelas ' + reais(soma) + (confere ? ' = ' : ' ≠ ') + 'frete do CT-e ' + reais(c.frete_centavos)})]));
    });
    alvo.appendChild(caixa);
  }
  document.querySelectorAll('.chip').forEach(function(c){
    c.addEventListener('click', function(){ campo.value = c.dataset.pedido; mostrar(c.dataset.pedido); });
  });
  campo.addEventListener('change', function(){ mostrar(campo.value.trim()); });
  campo.addEventListener('keydown', function(ev){ if (ev.key === 'Enter') mostrar(campo.value.trim()); });
  var primeiro = dados.exemplos.length ? dados.exemplos[0].pedido_id : (dados.pedidos[0] || {}).pedido_id;
  if (primeiro) { campo.value = primeiro; mostrar(primeiro); }
})();
"""
