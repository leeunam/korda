"""Extrai agregados das fontes públicas e grava calibration.yaml.

Uso:
    python3 data/synthetic/calibration/build_calibration.py

Entradas:
    data/external/anp_anuario_2026_t3_21/   (baixado por download.py, não versionado)
    data/external/antt_rntrc_veiculos/      (manual; parser pendente)
    data/synthetic/reference/municipios/    (versionado, MIT)
    data/synthetic/spec/area_atendimento.csv

Saída: data/synthetic/calibration/calibration.yaml, só com agregados e procedência.
Nenhuma linha bruta das fontes é copiada para os dados sintéticos.
Só biblioteca padrão; o YAML é escrito à mão em formato simples.
"""

from __future__ import annotations

import csv
import json
import math
import statistics
import sys
import unicodedata
from pathlib import Path

HERE = Path(__file__).resolve().parent
SYNTHETIC = HERE.parent
ROOT = HERE.parents[2]
EXTERNAL = ROOT / "data" / "external"
MUNICIPIOS = SYNTHETIC / "reference" / "municipios" / "municipios.csv"
ESTADOS = SYNTHETIC / "reference" / "municipios" / "estados.csv"
AREA = SYNTHETIC / "spec" / "area_atendimento.csv"
OUTPUT = HERE / "calibration.yaml"

ANP_ID = "anp_anuario_2026_t3_21"
ANP_FILE = "anuario-2026-dados_abertos-tabela3-21.csv"
ANTT_ID = "antt_rntrc_veiculos"
EARTH_RADIUS_KM = 6371.0


def normalize(text: str) -> str:
    """Compara nomes de UF sem acento, caixa ou espaços extras."""
    decomposed = unicodedata.normalize("NFKD", text)
    return " ".join("".join(c for c in decomposed if not unicodedata.combining(c)).lower().split())


def load_uf_names(path: Path = ESTADOS) -> dict[str, str]:
    """Mapeia nome normalizado da UF -> sigla (ex.: 'sao paulo' -> 'SP')."""
    with path.open(encoding="utf-8-sig", newline="") as handle:
        return {normalize(row["nome"]): row["uf"] for row in csv.DictReader(handle)}


def parse_anp_diesel(path: Path, uf_names: dict[str, str]) -> dict[str, dict[int, float]]:
    """Lê a tabela 3.21 (UTF-8 com BOM, ';', vírgula decimal) -> {UF: {ano: R$/litro}}."""
    prices: dict[str, dict[int, float]] = {}
    with path.open(encoding="utf-8-sig", newline="") as handle:
        reader = csv.reader(handle, delimiter=";")
        header = next(reader)
        if len(header) < 4:
            raise ValueError(f"Cabeçalho inesperado na tabela 3.21: {header}")
        for row in reader:
            if len(row) < 4 or not row[2].strip():
                continue
            name, value, year = row[1], row[2], row[3]
            uf = uf_names.get(normalize(name))
            if uf is None:
                raise ValueError(f"UF não reconhecida na tabela 3.21: {name!r}")
            prices.setdefault(uf, {})[int(year)] = float(value.strip().replace(",", "."))
    return prices


def latest_year(prices: dict[str, dict[int, float]]) -> int:
    """Ano mais recente presente para todas as UFs."""
    return min(max(years) for years in prices.values())


def haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlambda = math.radians(lon2 - lon1)
    a = math.sin(dphi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(dlambda / 2) ** 2
    return 2 * EARTH_RADIUS_KM * math.asin(math.sqrt(a))


def load_area(path: Path = AREA) -> list[dict[str, str]]:
    with path.open(encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle))


def distances_from_sede(area: list[dict[str, str]], municipios_path: Path = MUNICIPIOS) -> list[dict]:
    with municipios_path.open(encoding="utf-8", newline="") as handle:
        coords = {row["codigo_ibge"]: (float(row["latitude"]), float(row["longitude"]))
                  for row in csv.DictReader(handle)}
    sedes = [row for row in area if row["papel"] == "sede"]
    if len(sedes) != 1:
        raise ValueError("area_atendimento.csv precisa de exatamente uma linha com papel=sede")
    origin = coords[sedes[0]["codigo_ibge"]]
    result = []
    for row in area:
        if row["papel"] != "atendido":
            continue
        lat, lon = coords[row["codigo_ibge"]]
        result.append({"codigo_ibge": row["codigo_ibge"], "municipio": row["municipio"], "uf": row["uf"],
                       "km_linha_reta": round(haversine_km(*origin, lat, lon), 1)})
    return result


def read_manifest(source_id: str) -> dict:
    path = EXTERNAL / source_id / "manifest.json"
    return json.loads(path.read_text(encoding="utf-8")) if path.is_file() else {}


def q(value: str) -> str:
    return json.dumps(value, ensure_ascii=False)


def render(diesel: dict | None, distances: list[dict], sede: dict, antt_status: str) -> str:
    lines = [
        "# Gerado por data/synthetic/calibration/build_calibration.py. Não editar à mão.",
        "# Só agregados de fontes públicas; procedência em sources.json e data/external/<id>/manifest.json.",
        "# RASCUNHO para K03: regras de KPI ainda dependem de K02.",
        "",
        "diesel_preco_medio_consumidor:",
    ]
    if diesel is None:
        lines += ["  status: pendente", "  motivo: \"rode download.py; arquivo da ANP ausente em data/external/\""]
    else:
        lines += [
            f"  fonte: {q(diesel['fonte'])}",
            f"  arquivo: {q(ANP_FILE)}",
            f"  sha256: {q(diesel['sha256'])}",
            f"  obtido_em: {q(diesel['obtido_em'])}",
            "  unidade: R$/litro (valores correntes, média ponderada por vendas das distribuidoras)",
            f"  ano: {diesel['ano']}",
            f"  uf_sede: {sede['uf']}",
            f"  valor_uf_sede: {diesel['por_uf'][sede['uf']]:.4f}",
            "  por_uf:",
        ]
        lines += [f"    {uf}: {price:.4f}" for uf, price in sorted(diesel["por_uf"].items())]

    kms = [d["km_linha_reta"] for d in distances]
    lines += [
        "",
        "distancias_da_sede:",
        "  fonte: \"kelvins/municipios-brasileiros (MIT), commit 503e2f7; área em spec/area_atendimento.csv\"",
        "  metodo: \"haversine (raio 6371 km); distância de estrada = linha reta × fator_estrada de empresa.yaml\"",
        f"  sede: {q(sede['municipio'] + '/' + sede['uf'])}",
        f"  km_linha_reta_min: {min(kms):.1f}",
        f"  km_linha_reta_mediana: {statistics.median(kms):.1f}",
        f"  km_linha_reta_max: {max(kms):.1f}",
        "  municipios:",
    ]
    for d in sorted(distances, key=lambda d: d["km_linha_reta"]):
        lines.append(f"    - {{codigo_ibge: {d['codigo_ibge']}, municipio: {q(d['municipio'])}, "
                     f"uf: {d['uf']}, km_linha_reta: {d['km_linha_reta']:.1f}}}")

    lines += ["", "frota_rntrc:", f"  status: {antt_status}",
              "  motivo: \"dados.antt.gov.br sem resposta em 22/11/2026; ver instrucoes em sources.json\"",
              "  uso_previsto: \"proporção por tipo/carroceria na UF sede para conferir a frota suposta em empresa.yaml\""]
    return "\n".join(lines) + "\n"


def main() -> int:
    uf_names = load_uf_names()
    area = load_area()
    sede = next(row for row in area if row["papel"] == "sede")
    distances = distances_from_sede(area)

    diesel = None
    anp_path = EXTERNAL / ANP_ID / ANP_FILE
    if anp_path.is_file():
        prices = parse_anp_diesel(anp_path, uf_names)
        year = latest_year(prices)
        manifest = read_manifest(ANP_ID)
        entry = next((f for f in manifest.get("arquivos", []) if f["arquivo"] == ANP_FILE), {})
        diesel = {"fonte": manifest.get("titulo", ANP_ID), "sha256": entry.get("sha256", "desconhecido"),
                  "obtido_em": entry.get("obtido_em", "desconhecido"), "ano": year,
                  "por_uf": {uf: years[year] for uf, years in prices.items()}}
    else:
        print(f"Aviso: {anp_path.relative_to(ROOT)} ausente; bloco de diesel ficará pendente.", file=sys.stderr)

    antt_dir = EXTERNAL / ANTT_ID
    antt_files = [p for p in antt_dir.glob("*") if p.is_file() and p.name != "manifest.json"] if antt_dir.is_dir() else []
    antt_status = "arquivo_presente_parser_pendente" if antt_files else "pendente"

    OUTPUT.write_text(render(diesel, distances, sede, antt_status), encoding="utf-8")
    print(f"Gravado {OUTPUT.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
