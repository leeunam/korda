"""Planta as anomalias de entrega e monta os CT-e (agrupamento, valor, cancelamento, duplicata).

Tudo o que é plantado vai para `registro` (tipo, entidade, id, detalhe), exportado em
output/<empresa>/_gerador/anomalias_plantadas.csv. O gabarito NÃO lê esse registro.
"""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass, field
from decimal import Decimal

from cte_xml import chave_acesso
from model import Mundo, Pedido, Viagem, money

JUSTIFICATIVAS = ["Erro de digitacao no valor do frete", "Tomador informado incorretamente",
                  "Destinatario com endereco divergente", "Duplicidade de emissao no sistema"]


@dataclass
class Cte:
    numero: int
    chave: str
    viagem: Viagem
    pedidos: list[Pedido]
    vTPrest: Decimal
    dh_emissao: dt.datetime
    protocolo: str
    cancelado: bool = False
    substitui: str | None = None      # chave do CT-e cancelado que este substitui
    duplicado: bool = False
    evento: dict | None = None        # dados do cancelamento
    caso_explicavel: str | None = None
    extras: dict = field(default_factory=dict)


def plant_delivery_anomalies(mundo: Mundo, registro: list[dict]) -> None:
    rng, taxas = mundo.rng, mundo.taxas
    normais = [e for e in mundo.entregas if e.dt_realizada is not None and not e.pedido.caso_explicavel]
    n = len(normais)
    pool = list(normais)
    rng.shuffle(pool)

    def take(k, predicate=lambda e: True):
        chosen = [e for e in pool if predicate(e)][:k]
        for e in chosen:
            pool.remove(e)
        return chosen

    for e in take(round(taxas["entrega_atrasada_pct"] * n)):
        atraso = rng.randint(1, 3)
        dia = e.pedido.dt_prevista + dt.timedelta(days=atraso)
        if dia.weekday() == 6:
            dia += dt.timedelta(days=1)
        e.dt_realizada = dt.datetime.combine(dia, e.dt_realizada.time())
        registro.append({"tipo": "entrega_atrasada", "entidade": "pedido", "id": e.pedido.id,
                         "detalhe": f"prevista {e.pedido.dt_prevista} realizada {dia}"})
    for e in take(round(taxas["entrega_incompleta_pct"] * n), lambda e: e.pedido.qt_itens >= 2):
        e.qt_entregue = e.pedido.qt_itens - rng.randint(1, e.pedido.qt_itens - 1)
        e.status = "PARCIAL"
        registro.append({"tipo": "entrega_incompleta", "entidade": "pedido", "id": e.pedido.id,
                         "detalhe": f"{e.qt_entregue} de {e.pedido.qt_itens}"})
    for e in take(round(taxas["entrega_sem_data_pct"] * n)):
        e.dt_realizada = None
        registro.append({"tipo": "entrega_sem_data", "entidade": "pedido", "id": e.pedido.id, "detalhe": ""})

    formatos = mundo.ctx.cfg["formato"]["formatos_mistos"]
    com_data = [e for e in mundo.entregas if e.dt_realizada is not None]
    for e in rng.sample(com_data, round(taxas["data_formato_misto_pct"] * len(com_data))):
        e.formato_misto = rng.randrange(len(formatos))
        registro.append({"tipo": "data_formato_misto", "entidade": "entrega", "id": e.id,
                         "detalhe": formatos[e.formato_misto]})

    for v in mundo.viagens:
        if v.acima_capacidade:
            registro.append({"tipo": "viagem_acima_capacidade", "entidade": "viagem", "id": v.id, "detalhe": v.veiculo.tipo})
        if v.tipo != "DIST":
            registro.append({"tipo": "viagem_transferencia", "entidade": "viagem", "id": v.id,
                             "detalhe": f"{len(v.entregas)} pedidos internos"})


def _valor_frete(mundo: Mundo, viagem: Viagem, pedidos: list[Pedido], n_ctes_viagem: int) -> Decimal:
    frete = mundo.ctx.cfg["frete"]
    peso = sum(p.peso_kg for p in pedidos)
    dist = max(p.dist_km for p in pedidos)
    r_kg = next(f["r_kg"] for f in frete["r_por_kg_por_faixa_km"] if dist <= f["ate_km"])
    km = dist * mundo.ctx.diesel_r_l / viagem.veiculo.consumo_km_l * frete["fator_margem_km"] / n_ctes_viagem
    ad = float(sum(p.valor for p in pedidos)) * frete["ad_valorem_pct"] / 100
    return money(max(frete["frete_minimo_r"], peso * r_kg + km + ad))


def build_ctes(mundo: Mundo, registro: list[dict]) -> list[Cte]:
    cfg, rng, taxas = mundo.ctx.cfg, mundo.rng, mundo.taxas
    caso = cfg.get("caso_explicavel", {})
    caso_ids = {p["id"] for p in caso.get("pedidos", [])} if caso.get("ativo") else set()

    # 1) agrupamento: um CT-e por pedido; parte dos CT-e cobre 2-4 pedidos do mesmo cliente na mesma viagem
    grupos: list[tuple[Viagem, list[Pedido]]] = []
    candidatos: list[tuple[Viagem, list[Pedido]]] = []
    for v in mundo.viagens:
        por_cliente: dict[int, list[Pedido]] = {}
        for e in v.entregas:
            if e.pedido.caso_explicavel:
                continue
            por_cliente.setdefault(e.pedido.cliente.id, []).append(e.pedido)
        for lista in por_cliente.values():
            if len(lista) >= 2:
                candidatos.append((v, lista))
    rng.shuffle(candidatos)
    em_grupo: set[int] = set()
    total = sum(1 for p in mundo.pedidos if not p.caso_explicavel)
    multi = 0
    for v, lista in candidatos:
        if total and multi / total >= taxas["cte_multi_pedido_pct"]:
            break
        k = min(len(lista), rng.choice([2, 2, 2, 3, 4]))
        escolhidos = lista[:k]
        grupos.append((v, escolhidos))
        em_grupo.update(p.id for p in escolhidos)
        total -= k - 1
        multi += 1
    for v in mundo.viagens:
        for e in v.entregas:
            if e.pedido.id not in em_grupo and not e.pedido.caso_explicavel:
                grupos.append((v, [e.pedido]))

    # caso explicável: CT-e de 2 pedidos com valor fixo; terceiro pedido com CT-e próprio
    fixos: dict[tuple[int, ...], Decimal] = {}
    if caso_ids:
        v_caso = next(v for v in mundo.viagens if any(e.pedido.id in caso_ids for e in v.entregas))
        by_id = {e.pedido.id: e.pedido for e in v_caso.entregas}
        dois = tuple(caso["cte_dois_pedidos"]["pedidos"])
        grupos.append((v_caso, [by_id[i] for i in dois]))
        fixos[dois] = money(caso["cte_dois_pedidos"]["vTPrest"])
        um = caso["cte_cancelado_reemitido"]["pedido"]
        grupos.append((v_caso, [by_id[um]]))
        fixos[(um,)] = money(caso["cte_cancelado_reemitido"]["vTPrest_cancelado"])

    grupos.sort(key=lambda g: (g[0].data, g[0].id, min(p.id for p in g[1])))
    n_por_viagem: dict[int, int] = {}
    for v, _ in grupos:
        n_por_viagem[v.id] = n_por_viagem.get(v.id, 0) + 1

    emit = mundo.ctx.cfg["empresa"]
    cnpj_emit = _cnpj_emit(emit["cnpj_base"])
    cuf = mundo.ctx.sede.codigo_ibge[:2]

    ctes: list[Cte] = []

    def novo(v: Viagem, pedidos: list[Pedido], valor: Decimal, dh: dt.datetime) -> Cte:
        numero = len(ctes) + 1
        chave = chave_acesso(cuf, dh.strftime("%y%m"), cnpj_emit, "57", 1, numero, 1, rng.randrange(10**8))
        protocolo = f"1{cuf}{dh.strftime('%y')}{numero:010d}"
        cte = Cte(numero, chave, v, pedidos, valor, dh, protocolo)
        ctes.append(cte)
        return cte

    for v, pedidos in grupos:
        chave_fixa = tuple(p.id for p in pedidos)
        valor = fixos.get(chave_fixa) or _valor_frete(mundo, v, pedidos, n_por_viagem[v.id])
        dh = dt.datetime.combine(v.data, dt.time(5, 30)) + dt.timedelta(minutes=len(ctes) % 90)
        cte = novo(v, pedidos, valor, dh)
        if chave_fixa in fixos:
            cte.caso_explicavel = "dois_pedidos" if len(chave_fixa) == 2 else "cancelado_reemitido"
        if len(pedidos) > 1:
            registro.append({"tipo": "cte_multi_pedido", "entidade": "cte", "id": cte.chave,
                             "detalhe": "+".join(str(p.id) for p in pedidos)})

    # 2) cancelamento com reemissão
    elegiveis = [c for c in ctes if c.caso_explicavel is None]
    n_cancel = min(len(elegiveis), round(taxas["cte_cancelado_pct"] * len(ctes)))
    cancelar = rng.sample(elegiveis, n_cancel)
    cancelar += [c for c in ctes if c.caso_explicavel == "cancelado_reemitido"]
    for original in sorted(cancelar, key=lambda c: c.numero):
        original.cancelado = True
        dh_ev = original.dh_emissao + dt.timedelta(hours=1)
        original.evento = {"dh": dh_ev, "protocolo": f"1{cuf}{dh_ev.strftime('%y')}{900000 + original.numero:010d}",
                           "justificativa": rng.choice(JUSTIFICATIVAS)}
        valor = original.vTPrest
        if original.caso_explicavel:
            valor = money(caso["cte_cancelado_reemitido"]["vTPrest_reemitido"])
        sub = novo(original.viagem, original.pedidos, valor, original.dh_emissao + dt.timedelta(hours=2))
        sub.substitui = original.chave
        sub.caso_explicavel = original.caso_explicavel
        registro.append({"tipo": "cte_cancelado", "entidade": "cte", "id": original.chave,
                         "detalhe": f"reemitido como {sub.chave}"})

    # 3) duplicatas: o mesmo XML recebido duas vezes (só CT-e autorizados e não cancelados)
    validos = [c for c in ctes if not c.cancelado and c.caso_explicavel is None]
    n_dup = min(len(validos), round(taxas["cte_duplicado_pct"] * len(validos)))
    duplicar = rng.sample(validos, n_dup)
    if caso.get("ativo") and caso["cte_dois_pedidos"].get("duplicado"):
        duplicar += [c for c in ctes if c.caso_explicavel == "dois_pedidos"]
    for c in duplicar:
        c.duplicado = True
        registro.append({"tipo": "cte_duplicado", "entidade": "cte", "id": c.chave, "detalhe": ""})
    return ctes


def _cnpj_emit(base8: str) -> str:
    from model import cnpj_ficticio
    return cnpj_ficticio(base8)
