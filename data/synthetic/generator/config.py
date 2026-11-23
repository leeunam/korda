"""Leitura da configuração de uma empresa e dos dados de referência que o gerador usa."""

from __future__ import annotations

import csv
import datetime as dt
import math
from dataclasses import dataclass
from pathlib import Path

import yaml

SYNTHETIC = Path(__file__).resolve().parents[1]
EMPRESAS = SYNTHETIC / "empresas"
OUTPUT = SYNTHETIC / "output"
MUNICIPIOS = SYNTHETIC / "reference" / "municipios" / "municipios.csv"
CALIBRATION = SYNTHETIC / "calibration" / "calibration.yaml"
EARTH_RADIUS_KM = 6371.0


@dataclass
class Municipio:
    codigo_ibge: str
    nome: str
    uf: str
    lat: float
    lon: float
    peso_demanda: float
    papel: str


@dataclass
class Contexto:
    empresa_id: str
    cfg: dict
    sede: Municipio
    area: list[Municipio]
    municipios: dict[str, Municipio]   # todos os municípios de referência (para transferências)
    diesel_r_l: float


def haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    a = (math.sin(math.radians(lat2 - lat1) / 2) ** 2
         + math.cos(phi1) * math.cos(phi2) * math.sin(math.radians(lon2 - lon1) / 2) ** 2)
    return 2 * EARTH_RADIUS_KM * math.asin(math.sqrt(a))


def _uf_por_codigo() -> dict[str, str]:
    estados = MUNICIPIOS.parent / "estados.csv"
    with estados.open(encoding="utf-8-sig", newline="") as handle:
        return {row["codigo_uf"]: row["uf"] for row in csv.DictReader(handle)}


def load_municipios() -> dict[str, Municipio]:
    ufs = _uf_por_codigo()
    with MUNICIPIOS.open(encoding="utf-8", newline="") as handle:
        return {row["codigo_ibge"]: Municipio(row["codigo_ibge"], row["nome"], ufs[row["codigo_uf"]],
                                              float(row["latitude"]), float(row["longitude"]), 0.0, "")
                for row in csv.DictReader(handle)}


def load(empresa_id: str) -> Contexto:
    folder = EMPRESAS / empresa_id
    cfg = yaml.safe_load((folder / "empresa.yaml").read_text(encoding="utf-8"))
    if cfg["empresa_id"] != empresa_id:
        raise ValueError(f"empresa_id {cfg['empresa_id']!r} não corresponde à pasta {empresa_id!r}")
    municipios = load_municipios()
    area = []
    with (folder / cfg["empresa"]["area_atendimento"]).open(encoding="utf-8", newline="") as handle:
        for row in csv.DictReader(handle):
            ref = municipios[row["codigo_ibge"]]
            area.append(Municipio(ref.codigo_ibge, ref.nome, ref.uf, ref.lat, ref.lon,
                                  float(row["peso_demanda"]), row["papel"]))
    sedes = [m for m in area if m.papel == "sede"]
    if len(sedes) != 1:
        raise ValueError(f"{empresa_id}: área precisa de exatamente uma sede")
    calibration = yaml.safe_load(CALIBRATION.read_text(encoding="utf-8"))
    diesel = calibration["diesel_preco_medio_consumidor"]["por_uf"][sedes[0].uf]
    return Contexto(empresa_id, cfg, sedes[0], area, municipios, float(diesel))


def empresas_disponiveis() -> list[str]:
    return sorted(p.name for p in EMPRESAS.iterdir() if (p / "empresa.yaml").is_file())


# ----------------------------------------------------------------- dias úteis


def is_business_day(day: dt.date, sabado: bool) -> bool:
    return day.weekday() < 5 or (sabado and day.weekday() == 5)


def add_business_days(day: dt.date, n: int, sabado: bool) -> dt.date:
    current = day
    while n > 0:
        current += dt.timedelta(days=1)
        if is_business_day(current, sabado):
            n -= 1
    return current


def sub_business_days(day: dt.date, n: int, sabado: bool) -> dt.date:
    current = day
    while n > 0:
        current -= dt.timedelta(days=1)
        if is_business_day(current, sabado):
            n -= 1
    return current


def same_or_next_business_day(day: dt.date, sabado: bool) -> dt.date:
    current = day
    while not is_business_day(current, sabado):
        current += dt.timedelta(days=1)
    return current
