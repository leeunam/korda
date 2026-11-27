"use client";

import Link from "next/link";
import { useEffect, useRef, useState, type FormEvent } from "react";
import { ArrowLeftIcon, ArrowPathIcon, ArrowDownTrayIcon } from "@heroicons/react/24/outline";
import { caminhoProjeto, consultar, legivel, type Fonte, type Lacuna, type Plano, type Projeto } from "@/lib/operador";
import "./operador.css";

const reais = new Intl.NumberFormat("pt-BR", { style: "currency", currency: "BRL" });
const numero = new Intl.NumberFormat("pt-BR", { maximumFractionDigits: 4 });

function identificador(entrada: string) {
  return /^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$/.test(entrada);
}

function Lacunas({ fonte }: { fonte: Fonte }) {
  const pendencias = [...(fonte.pendencias ?? []), ...(fonte.lacunas ?? [])]
    .filter((item) => item.state !== "respondida");
  const perguntas = [...new Set(pendencias.map(item => typeof item === "string" ? item : textoLacuna(item)))];
  if (!perguntas.length) return null;
  return <div data-testid="lacunas"><h3>Pendências da entrevista</h3><ul className="op-gaps">
    {perguntas.map(pergunta => <li key={pergunta}>{pergunta}</li>)}
  </ul></div>;
}

function textoLacuna(item: Lacuna) {
  return item.question || item.pergunta || item.motivo || item.mensagem || item.detail ||
    legivel(item.campo || item.rule_key || item.key || item.topic || item.id || "Informação pendente");
}

function Revisao({ plano }: { plano: Plano }) {
  return <>
    <dl className="op-meta">
      <div><dt>Versão do plano</dt><dd className="op-hash" data-testid="plan-version">{plano.plan_version}</dd></div>
      <div><dt>Origem</dt><dd>{plano.context_id} · revisão {plano.context_revision}</dd></div>
      <div><dt>Destino autorizado no plano</dt><dd>{plano.destination}</dd></div>
      <div><dt>Lote sintético</dt><dd>01_demo · ingestão {plano.ingestion_level.toUpperCase()}</dd></div>
      {plano.cost_estimate_brl_cents != null && <div><dt>Custo estimado</dt><dd>{reais.format(plano.cost_estimate_brl_cents / 100)}</dd></div>}
    </dl>
    <details className="op-details"><summary>Indicadores e regras do plano</summary>
      <h4>Indicadores</h4><dl className="op-review">{Object.entries(plano.metrics).map(([id, m]) =>
        <div key={id}><dt>{legivel(id)} {m.unit && <small>({m.unit})</small>}</dt><dd>{m.formula || legivel(m.state || "")}</dd></div>)}</dl>
      <h4>Regras</h4><dl className="op-review">{Object.entries(plano.rules).map(([id, regra]) =>
        <div key={id}><dt>{legivel(id)}</dt><dd>{regra.value == null ? "A confirmar" :
          typeof regra.value === "object" ? JSON.stringify(regra.value) : String(regra.value)}
          {(regra.status || regra.state) && <> · {legivel(regra.status || regra.state || "")}</>}
          {regra.confirmed_by?.role && <div>Confirmada por {legivel(regra.confirmed_by.role)}</div>}
          {!!regra.evidence_ids?.length && <div><small>Evidências</small> <span className="op-hash">{regra.evidence_ids.join(", ")}</span></div>}
          </dd></div>)}</dl>
      {(plano.gaps || []).some(g => g.state !== "respondida") &&
        <><h4>Lacunas abertas</h4><ul>{plano.gaps.filter(g => g.state !== "respondida").map((g, i) => <li key={i}>{textoLacuna(g)}</li>)}</ul></>}
    </details>
  </>;
}

function Decisao({ entrega = false, bloqueado, decidir }: {
  entrega?: boolean; bloqueado: boolean; decidir: (aprovada: boolean, pessoa: string) => void;
}) {
  const [pessoa, digitar] = useState("");
  return <form className="op-decision" onSubmit={e => e.preventDefault()}>
    <label>Responsável pela decisão {entrega ? "da entrega" : "do plano"}
      <input value={pessoa} maxLength={120} onChange={e => digitar(e.target.value)} autoComplete="off" required />
    </label>
    <div className="op-actions">
      <button type="button" className="op-primary" disabled={bloqueado || !pessoa.trim()} onClick={() => decidir(true, pessoa.trim())}>
        {entrega ? "Autorizar entrega" : "Aprovar plano"}
      </button>
      <button type="button" disabled={bloqueado || !pessoa.trim()} onClick={() => decidir(false, pessoa.trim())}>
        Rejeitar {entrega ? "entrega" : "plano"}
      </button>
    </div>
  </form>;
}

export function OperatorPanel() {
  const [id, mudarId] = useState("");
  const [projeto, mostrar] = useState<Projeto | null>(null);
  const [revisao, digitarRevisao] = useState("");
  const [fonte, consultarFonte] = useState<Fonte | null>(null);
  const [revisaoVista, lembrarRevisao] = useState(-1);
  const [erro, informarErro] = useState("");
  const [ocupado, marcar] = useState(false);
  const emCurso = useRef(false);
  const geracao = useRef(0);

  const base = projeto ? caminhoProjeto(projeto.project_id) : "";
  const plano = projeto?.plan;
  const run = projeto?.run;
  const fonteVisivel = fonte || projeto?.source;
  const planoSuperado = !!plano && revisaoVista > plano.context_revision;
  const runAtual = !!run && run.plan_version === plano?.plan_version;
  const acompanhar = !!run && ["executando", "enfileirada", "iniciando"].includes(run.state);

  useEffect(() => {
    if (!acompanhar || ocupado) return;
    const controle = new AbortController();
    let aguardando = false;
    const timer = window.setInterval(async () => {
      if (aguardando || emCurso.current) return;
      const versao = geracao.current;
      aguardando = true;
      try {
        const estado = await consultar<Projeto>(base, undefined, controle.signal);
        if (!controle.signal.aborted && geracao.current === versao) { mostrar(estado); informarErro(""); }
      } catch (e) {
        if (!controle.signal.aborted && geracao.current === versao) informarErro((e as Error).message);
      } finally { aguardando = false; }
    }, 1800);
    return () => { controle.abort(); window.clearInterval(timer); };
  }, [acompanhar, ocupado, base]);

  async function agir(operacao: () => Promise<void>) {
    if (emCurso.current) return;
    emCurso.current = true;
    geracao.current++;
    marcar(true);
    informarErro("");
    try { await operacao(); }
    catch (e) { informarErro(e instanceof Error ? e.message : "A operação não pôde ser concluída."); }
    finally { emCurso.current = false; marcar(false); }
  }

  function abrir(e: FormEvent) {
    e.preventDefault();
    if (!identificador(id.trim())) { informarErro("Informe o identificador do projeto da descoberta."); return; }
    void agir(async () => {
      if (id.trim() !== projeto?.project_id) { mostrar(null); consultarFonte(null); lembrarRevisao(-1); digitarRevisao(""); }
      mostrar(await consultar<Projeto>(caminhoProjeto(id.trim())));
    });
  }
  function buscar(ultima: boolean) {
    if (!ultima && !/^(0|[1-9]\d{0,12})$/.test(revisao)) return;
    void agir(async () => {
      consultarFonte(null);
      const consultada = await consultar<Fonte>(base + "/fonte" + (ultima ? "" : "?revision=" + revisao));
      consultarFonte(consultada);
      digitarRevisao(String(consultada.revision));
      lembrarRevisao(anterior => Math.max(anterior, consultada.revision));
    });
  }
  function comando(acao: string, dados: Record<string, unknown>) {
    void agir(async () => {
      if (acao === "importar") consultarFonte(null);
      mostrar(await consultar<Projeto>(base + "/" + acao, dados));
    });
  }

  return <main className="op" lang="pt-BR">
    <header className="op-head"><div><Link href="/run" className="op-logo" aria-label="Korda · grafo de exemplo">
      {/* eslint-disable-next-line @next/next/no-img-element */}
      <img src="/korda-wordmark-white.svg" alt="Korda" width="78" height="22" /></Link>
      <span>Painel do operador</span></div><Link href="/run" className="op-link"><ArrowLeftIcon />Grafo de exemplo</Link></header>
    <div className="op-body">
      <h1>Operação do projeto</h1>
      <section className="op-card" aria-label="Selecionar projeto">
        <form className="op-inline" onSubmit={abrir}><label>Projeto
          <input value={id} onChange={e => mudarId(e.target.value)} required maxLength={128} placeholder="ID da entrevista" autoComplete="off" />
        </label><button className="op-primary" disabled={ocupado || !id.trim()}>Abrir projeto</button></form>
      </section>
      {erro && <p className="op-error" role="alert">{erro}</p>}
      {projeto && <div className="op-grid"><section className="op-card">
        <div className="op-row"><h2>Descoberta</h2><button className="op-refresh" disabled={ocupado}
          onClick={() => void agir(async () => mostrar(await consultar<Projeto>(base)))}><ArrowPathIcon />Atualizar projeto</button></div>
        <p className="op-muted">Consulte a revisão congelada da entrevista do projeto <strong>{projeto.project_id}</strong>.</p>
        <button disabled={ocupado} onClick={() => buscar(true)}>Consultar última revisão</button>
        <form className="op-inline" onSubmit={e => {e.preventDefault(); buscar(false);}}><label>Revisão da descoberta
          <input value={revisao} onChange={e => {digitarRevisao(e.target.value); consultarFonte(null);}} type="number" min="0" max="9999999999999" required />
        </label><button disabled={ocupado || !/^(0|[1-9]\d{0,12})$/.test(revisao)}>Consultar revisão</button></form>
        {fonteVisivel && <div className="op-inset"><h3>{fonte ? "Revisão consultada" : "Revisão importada"} · {fonteVisivel.revision}</h3>
          <div className="op-muted">{legivel(fonteVisivel.estado)}</div>
          <dl className="op-meta"><div><dt>Contexto</dt><dd>{fonteVisivel.context_id}</dd></div>
            <div><dt>SHA-256 da revisão</dt><dd className="op-hash" data-testid="source-hash">{fonteVisivel.sha256}</dd></div></dl>
          <Lacunas fonte={fonteVisivel} />
          {fonte && <button className="op-primary" disabled={ocupado || fonte.revision !== Number(revisao)}
            onClick={() => comando("importar", { revision: fonte.revision, context_sha256: fonte.sha256 })}>Importar revisão</button>}
        </div>}
      </section>
      <section className="op-card"><h2>Plano de execução</h2>
        {plano ? <><p className="op-state" data-state={plano.state}>{legivel(plano.state)}</p><Revisao plano={plano} />
          {planoSuperado && <p className="op-warning" role="status">A revisão {revisaoVista} é mais recente que este plano. Importe a revisão atual para decidir.</p>}
          {["aguardando_aprovacao", "plano_rejeitado"].includes(plano.state) &&
            <Decisao key={plano.plan_version} bloqueado={ocupado || planoSuperado} decidir={(aprovar, pessoa) =>
              comando("decidir-plano", { plan_version: plano.plan_version, aprovar, pessoa })} />}
          {plano.state === "plano_aprovado" && (!runAtual || run?.state === "falhou") &&
            <button className="op-primary" disabled={ocupado || planoSuperado} onClick={() => comando("executar", { plan_version: plano.plan_version,
              ...(runAtual && run?.state === "falhou" ? { retry_run_id: run.run_id } : {}) })}>
              {runAtual && run?.state === "falhou" ? "Tentar execução novamente" : "Iniciar execução"}</button>}
        </> : <p className="op-muted">{projeto.source?.estado === "pendente" ? "Resolva as pendências na entrevista e importe a nova revisão." : "Importe uma revisão pronta para gerar o plano."}</p>}
      </section>
      {run && <section className="op-card op-wide"><h2>Execução e entrega</h2><p className="op-state" data-testid="run-state" data-state={run.state} role="status">{legivel(run.state)}</p>
        <dl className="op-meta"><div><dt>Execução</dt><dd className="op-hash" data-testid="run-id">{run.run_id}</dd></div>
          <div><dt>Versão executada</dt><dd className="op-hash">{run.plan_version}</dd></div><div><dt>Destino</dt><dd>{run.destination}</dd></div></dl>
        {run.kpis && <div className="op-kpis" data-testid="kpis">{Object.entries(run.kpis).map(([k,v]) =>
          <div key={k}><span>{legivel(k)}</span><strong>{v == null ? "Sem valor" : k === "custo_frete_por_entrega" ? reais.format(v) : numero.format(v) + (k.endsWith("_pct") ? "%" : "")}</strong></div>)}</div>}
        {run.avaliacao && <p className="op-inset" data-testid="avaliacao"><strong>Avaliação {run.avaliacao.aprovado ? "aprovada" : "recusada"}</strong>
          {" · "}{run.avaliacao.divergencias} divergência(s) · {legivel(run.avaliacao.classe)}</p>}
        {runAtual && ["aguardando_aprovacao_entrega", "entrega_rejeitada"].includes(run.state) &&
          <Decisao key={run.run_id} entrega bloqueado={ocupado || planoSuperado} decidir={(aprovar, pessoa) =>
            comando("decidir-entrega", { run_id: run.run_id, plan_version: run.plan_version, aprovar, pessoa })} />}
        {runAtual && run.state === "entrega_autorizada" && <button className="op-primary" disabled={ocupado || planoSuperado}
          onClick={() => comando("promover", { run_id: run.run_id, plan_version: run.plan_version })}>Promover entrega</button>}
        {run.state === "promovida" && <div className="op-files"><h3>Arquivos entregues</h3>
          {run.arquivos.map(nome => <a key={nome} download={nome}
            href={base + "/runs/" + encodeURIComponent(run.run_id) + "/arquivos/" + encodeURIComponent(nome)}><ArrowDownTrayIcon />{nome}</a>)}</div>}
      </section>}</div>}
    </div>
  </main>;
}
