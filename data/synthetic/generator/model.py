"""Simulação determinística dos FATOS de uma transportadora fictícia.

Produz clientes, veículos, viagens, pedidos e entregas "limpos". As anomalias
de entrega e de CT-e são plantadas depois, em anomalies.py, e registradas.
Uma instância de random.Random(semente) por empresa garante reprodutibilidade.
"""

from __future__ import annotations

import datetime as dt
import math
import random
from dataclasses import dataclass, field
from decimal import ROUND_HALF_UP, Decimal

from config import (Contexto, Municipio, add_business_days, haversine_km, is_business_day,
                    same_or_next_business_day, sub_business_days)

PREFIXOS = ["Alfa", "Bravo", "Cedro", "Delta", "Ébano", "Farol", "Guará", "Horizonte", "Ipê", "Jatobá",
            "Lince", "Mirante", "Nobre", "Orvalho", "Prisma", "Quartzo", "Ribeira", "Sabiá", "Tucano",
            "Umbu", "Vereda", "Xisto", "Zênite", "Aroeira", "Buriti", "Carnaúba", "Dourado", "Embaúba"]
SETORES = ["Alimentos", "Autopeças", "Cosméticos", "Embalagens", "Ferragens", "Farma", "Têxtil",
           "Eletrônicos", "Papelaria", "Bebidas", "Utilidades", "Química", "Pet", "Higiene"]
SUFIXOS = ["Comércio Ltda", "Distribuidora Ltda", "Indústria Ltda", "Atacado Ltda"]
LOGRADOUROS = ["Rua das Acácias", "Avenida Central", "Rua Projetada A", "Rua do Comércio",
               "Avenida dos Pinheiros", "Rua Sete", "Estrada Municipal B", "Rua da Estação"]
BAIRROS = ["Centro", "Distrito Industrial", "Jardim Novo", "Vila Operária", "Parque Empresarial"]


def money(value: float | Decimal) -> Decimal:
    return Decimal(str(value)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def cnpj_ficticio(base8: str, filial: int = 1) -> str:
    """CNPJ com os dois dígitos verificadores propositalmente INVÁLIDOS (não coincide com CNPJ real)."""
    corpo = f"{base8}{filial:04d}"
    nums = [int(c) for c in corpo]
    pesos1 = [5, 4, 3, 2, 9, 8, 7, 6, 5, 4, 3, 2]
    d1 = 11 - sum(a * b for a, b in zip(nums, pesos1)) % 11
    d1 = 0 if d1 >= 10 else d1
    pesos2 = [6] + pesos1
    d2 = 11 - sum(a * b for a, b in zip(nums + [d1], pesos2)) % 11
    d2 = 0 if d2 >= 10 else d2
    return f"{corpo}{(d1 + 1) % 10}{(d2 + 1) % 10}"


@dataclass
class Cliente:
    id: int
    razao: str
    cnpj: str
    ie: str
    municipio: Municipio
    logradouro: str
    numero: str
    bairro: str
    cep: str
    interno: bool = False   # True para o "cliente" de transferência (filial)


@dataclass
class Veiculo:
    id: str
    placa: str
    tipo: str
    cap_kg: float
    cap_m3: float
    consumo_km_l: float


@dataclass
class Pedido:
    id: int
    cliente: Cliente
    dt_emissao: dt.date
    dt_prevista: dt.date
    prazo_dias: int
    qt_itens: int
    peso_kg: float
    volume_m3: float
    valor: Decimal
    dist_km: float
    chave_nfe: str = ""
    caso_explicavel: bool = False


@dataclass
class Entrega:
    id: int
    viagem_id: int
    pedido: Pedido
    seq: int
    qt_entregue: int
    dt_realizada: dt.datetime | None
    status: str
    formato_misto: int | None = None   # índice em formato.formatos_mistos, se plantado


@dataclass
class Viagem:
    id: int
    veiculo: Veiculo
    data: dt.date
    dt_saida: dt.datetime
    tipo: str
    km: float = 0.0
    entregas: list[Entrega] = field(default_factory=list)
    acima_capacidade: bool = False


@dataclass
class Mundo:
    ctx: Contexto
    rng: random.Random
    taxas: dict[str, float]
    clientes: list[Cliente]
    veiculos: list[Veiculo]
    viagens: list[Viagem]
    pedidos: list[Pedido]
    entregas: list[Entrega]


def _taxas(cfg: dict, rng: random.Random) -> dict[str, float]:
    taxas = {}
    for chave, faixa in sorted(cfg["anomalias"].items()):
        if isinstance(faixa, dict):
            taxas[chave] = rng.uniform(faixa["min"], faixa["max"]) / 100
    if cfg["transferencias"].get("ativo"):
        faixa = cfg["transferencias"]["viagens_pct"]
        taxas["transferencia_viagens_pct"] = rng.uniform(faixa["min"], faixa["max"]) / 100
    return taxas


def _cliente(rng: random.Random, cid: int, municipio: Municipio, razao: str | None = None) -> Cliente:
    razao = razao or f"{rng.choice(PREFIXOS)} {rng.choice(SETORES)} {rng.choice(SUFIXOS)} (fictícia)"
    base = f"{rng.randrange(10**7, 10**8)}"
    return Cliente(cid, razao, cnpj_ficticio(base), f"{rng.randrange(10**9, 10**12)}", municipio,
                   rng.choice(LOGRADOUROS), str(rng.randint(10, 3999)), rng.choice(BAIRROS),
                   f"{rng.randint(10000, 99999)}{rng.randint(0, 999):03d}")


def _placa(rng: random.Random) -> str:
    letras = "ABCDEFGHJKLMNPRSTUVWXYZ"
    return f"KRD{rng.randint(0, 9)}{rng.choice(letras)}{rng.randint(0, 99):02d}"


def _chave_nfe(rng: random.Random, pedido: Pedido) -> str:
    from cte_xml import chave_acesso
    cuf = pedido.cliente.municipio.codigo_ibge[:2]
    aamm = pedido.dt_emissao.strftime("%y%m")
    return chave_acesso(cuf, aamm, pedido.cliente.cnpj, "55", 1, pedido.id, 1, rng.randrange(10**8))


def simulate(ctx: Contexto) -> Mundo:
    cfg = ctx.cfg
    rng = random.Random(cfg["semente"])
    taxas = _taxas(cfg, rng)
    sabado_util = cfg["regras_referencia"]["prazo_conta_sabado"]
    fator_estrada = cfg["custos_operacao"]["fator_estrada"]["valor"]

    # ---- clientes: municípios sorteados pelos pesos da área
    area = ctx.area
    pesos = [m.peso_demanda for m in area]
    clientes = [_cliente(rng, 1001 + i, rng.choices(area, pesos)[0]) for i in range(cfg["clientes"]["quantidade"])]
    transf = cfg["transferencias"]
    cliente_interno = None
    if transf.get("ativo"):
        mun = ctx.municipios[str(transf["cliente"]["municipio_ibge"])]
        cliente_interno = _cliente(rng, 1001 + len(clientes), mun, transf["cliente"]["razao"])
        cliente_interno.interno = True
        clientes.append(cliente_interno)

    # ---- frota
    veiculos = []
    for grupo in cfg["frota"]["veiculos"]:
        for i in range(grupo["quantidade"]):
            veiculos.append(Veiculo(f"{grupo['tipo'][:1]}{len(veiculos) + 1:02d}", _placa(rng), grupo["tipo"],
                                    float(grupo["capacidade_kg"]), float(grupo["capacidade_m3"]),
                                    float(grupo["consumo_km_l"])))

    pcfg, vcfg = cfg["pedido"], cfg["viagens"]
    caso = cfg.get("caso_explicavel", {})
    caso_data = dt.date.fromisoformat(str(caso["data"])) if caso.get("ativo") else None
    inicio = dt.date.fromisoformat(str(cfg["periodo"]["inicio"]))

    def distancia(m: Municipio) -> float:
        return haversine_km(ctx.sede.lat, ctx.sede.lon, m.lat, m.lon) * fator_estrada

    viagens: list[Viagem] = []
    pedidos: list[Pedido] = []
    entregas: list[Entrega] = []
    next_pedido, next_viagem, next_entrega = 100001, 5001, 700001

    for d in range(cfg["periodo"]["dias_corridos"]):
        dia = inicio + dt.timedelta(days=d)
        if dia.weekday() not in cfg["periodo"]["dias_operacao"]:
            continue
        ativos = list(veiculos)
        if dia.weekday() == 5:
            ativos = sorted(rng.sample(veiculos, math.ceil(len(veiculos) * cfg["periodo"]["fracao_frota_sabado"])),
                            key=lambda v: v.id)
        caso_viagem = None
        if caso_data == dia:
            caso_viagem = max(ativos, key=lambda v: (v.cap_m3, v.id)).id

        for veiculo in ativos:
            transferencia = cliente_interno is not None and rng.random() < taxas.get("transferencia_viagens_pct", 0)
            saida = dt.datetime.combine(dia, dt.time(7, rng.randint(0, 50)))
            viagem = Viagem(next_viagem, veiculo, dia, saida, transf.get("tipo_viagem", "TRF") if transferencia else "DIST")
            next_viagem += 1

            acima = (not transferencia) and rng.random() < taxas["viagem_acima_capacidade_pct"]
            viagem.acima_capacidade = acima
            occ = rng.uniform(1.03, 1.12) if acima else rng.uniform(vcfg["ocupacao_alvo"]["min"], vcfg["ocupacao_alvo"]["max"])

            fixos: list[tuple[int, float, float]] = []
            if veiculo.id == caso_viagem:
                fixos = [(p["id"], float(p["peso_kg"]), float(p["volume_m3"])) for p in caso["pedidos"]]

            if transferencia:
                n = rng.randint(transf["pedidos_por_viagem"]["min"], transf["pedidos_por_viagem"]["max"])
                destinos = [cliente_interno] * n
            else:
                n = rng.randint(vcfg["entregas_por_viagem"]["min"], vcfg["entregas_por_viagem"]["max"]) - len(fixos)
                destinos = rng.choices([c for c in clientes if not c.interno], k=n)

            # pesos relativos e densidades; carga total ajustada à ocupação-alvo na restrição limitante
            shares = [rng.lognormvariate(0, 0.6) for _ in destinos]
            total = sum(shares)
            shares = [s / total for s in shares]
            dens = [rng.uniform(pcfg["densidade_kg_m3"]["min"], pcfg["densidade_kg_m3"]["max"]) for _ in destinos]
            fixo_kg = sum(f[1] for f in fixos)
            fixo_m3 = sum(f[2] for f in fixos)
            alvo_kg = occ * veiculo.cap_kg - fixo_kg
            alvo_m3 = occ * veiculo.cap_m3 - fixo_m3
            m3_por_kg = sum(s / dn for s, dn in zip(shares, dens))
            carga_kg = min(alvo_kg, alvo_m3 / m3_por_kg)

            itens = [(None, c, max(1.0, round(carga_kg * s, 1)), dn) for c, s, dn in zip(destinos, shares, dens)]
            for fid, fkg, fm3 in fixos:
                itens.append((fid, clientes[0], fkg, fkg / fm3))
            itens.sort(key=lambda it: (distancia(it[1].municipio), it[1].id))

            for seq, (fid, cliente, peso, densidade) in enumerate(itens, start=1):
                dist = distancia(cliente.municipio)
                prazo = pcfg["prazo_dias_uteis"]["ate_100_km" if dist <= 100 else "acima_100_km"]
                base = same_or_next_business_day(dia, sabado_util)
                folga = 0 if (fid or rng.random() < pcfg["folga_entrega_dias_uteis"]["zero"]) else 1
                prevista = add_business_days(base, folga, sabado_util)
                emissao = sub_business_days(prevista, prazo, sabado_util)
                if fid:
                    pid = fid
                    volume = next(f[2] for f in fixos if f[0] == fid)
                    valor = money(peso * 50)
                    qt = 4
                else:
                    pid = next_pedido
                    next_pedido += 1
                    volume = round(peso / densidade, 3) or 0.001
                    valor = money(peso * rng.uniform(pcfg["valor_mercadoria_r_por_kg"]["min"],
                                                     pcfg["valor_mercadoria_r_por_kg"]["max"]))
                    qt = rng.randint(pcfg["itens"]["min"], pcfg["itens"]["max"])
                pedido = Pedido(pid, cliente, emissao, prevista, prazo, qt, peso, volume, valor, dist,
                                caso_explicavel=bool(fid))
                pedido.chave_nfe = _chave_nfe(rng, pedido)
                pedidos.append(pedido)

                hora = saida + dt.timedelta(minutes=40 * seq + rng.randint(0, 25))
                if transferencia:
                    ent = Entrega(next_entrega, viagem.id, pedido, seq, qt, None, transf["status_entrega"])
                else:
                    # entrega normal: dentro do prazo e completa (anomalias vêm depois)
                    if hora.date() > prevista:
                        hora = dt.datetime.combine(prevista, dt.time(18, 0))
                    ent = Entrega(next_entrega, viagem.id, pedido, seq, qt, hora, "ENTREGUE")
                next_entrega += 1
                viagem.entregas.append(ent)
                entregas.append(ent)

            viagem.km = round(2 * max(e.pedido.dist_km for e in viagem.entregas) + 4 * len(viagem.entregas), 1)
            viagens.append(viagem)

    return Mundo(ctx, rng, taxas, clientes, veiculos, viagens, pedidos, entregas)


def is_util(day: dt.date, ctx: Contexto) -> bool:
    return is_business_day(day, ctx.cfg["regras_referencia"]["prazo_conta_sabado"])
