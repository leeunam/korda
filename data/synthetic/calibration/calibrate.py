"""Calibração dos dados sintéticos em um único passo: obter fontes, registrar procedência e agregar.

Uso:
    python3 data/synthetic/calibration/calibrate.py            # baixa, confere, registra e agrega
    python3 data/synthetic/calibration/calibrate.py --offline  # sem rede: usa o que já está em data/external/

Etapas:
  1. Obter: baixa cada fonte de sources.json para data/external/<id>/ (ignorado pelo Git).
     Fontes em modo manual são só conferidas (o arquivo deve ser colocado à mão).
  2. Registrar: grava manifest.json (versionado, ao lado deste script) com URL, licença,
     data de obtenção, tamanho e sha256 de cada arquivo, a conferência das cópias versionadas
     em reference/ e o status de cada fonte. Checksum divergente é reportado, nunca corrigido.
  3. Agregar: grava calibration.yaml só com agregados (diesel por UF, distâncias da sede,
     status da frota RNTRC). Nenhuma linha bruta das fontes entra nos dados sintéticos.

Sai com código 1 se alguma fonte estiver pendente ou divergente (as saídas são gravadas mesmo assim).
Só biblioteca padrão; o YAML é escrito à mão em formato simples.
"""

from __future__ import annotations

import argparse
import csv
import datetime as dt
import hashlib
import json
import math
import statistics
import sys
import unicodedata
import urllib.error
import urllib.request
from pathlib import Path

HERE = Path(__file__).resolve().parent
SYNTHETIC = HERE.parent
ROOT = HERE.parents[2]
EXTERNAL = ROOT / "data" / "external"
SOURCES = HERE / "sources.json"
MANIFEST = HERE / "manifest.json"
OUTPUT = HERE / "calibration.yaml"
MUNICIPIOS = SYNTHETIC / "reference" / "municipios" / "municipios.csv"
ESTADOS = SYNTHETIC / "reference" / "municipios" / "estados.csv"
EMPRESAS = SYNTHETIC / "empresas"
AREA = EMPRESAS / "01_demo" / "area_atendimento.csv"   # padrão dos testes

ANP_ID = "anp_anuario_2026_t3_21"
ANP_FILE = "anuario-2026-dados_abertos-tabela3-21.csv"
ANTT_ID = "antt_rntrc_veiculos"
USER_AGENT = "korda-calibration/0.1 (+https://github.com/leeunam/korda)"
TIMEOUT_S = 60
EARTH_RADIUS_KM = 6371.0
# Arquivos que não são dados da fonte (ex.: manifesto antigo do download.py).
IGNORED_IN_EXTERNAL = {"manifest.json", ".DS_Store"}


# --------------------------------------------------------------------------- 1. obter


def sha256_of(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 16), b""):
            digest.update(chunk)
    return digest.hexdigest()


def fetch(url: str, dest: Path) -> None:
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(request, timeout=TIMEOUT_S) as response:
        data = response.read()
    dest.write_bytes(data)


def previous_entries() -> dict[tuple[str, str], dict]:
    """Entradas do manifesto anterior, para manter a data de obtenção quando o arquivo não mudou."""
    if not MANIFEST.is_file():
        return {}
    data = json.loads(MANIFEST.read_text(encoding="utf-8"))
    return {(s["id"], f["arquivo"]): f for s in data.get("fontes", []) for f in s.get("arquivos", [])}


def obtain_source(source: dict, offline: bool, previous: dict, now: str) -> dict:
    """Obtém/confere uma fonte e devolve sua entrada no manifesto."""
    folder = EXTERNAL / source["id"]
    folder.mkdir(parents=True, exist_ok=True)
    problems: list[str] = []
    files: list[dict] = []

    declared = source.get("files", [])
    if source.get("modo") == "manual" and not declared:
        declared = [{"url": source.get("pagina"), "dest": p.name, "sha256": None}
                    for p in sorted(folder.iterdir())
                    if p.is_file() and p.name not in IGNORED_IN_EXTERNAL]
        if not declared:
            problems.append(f"fonte manual ausente. {source.get('instrucoes', '')}".strip())

    for item in declared:
        dest = folder / item["dest"]
        if not offline and source.get("modo") != "manual":
            try:
                fetch(item["url"], dest)
            except (urllib.error.URLError, TimeoutError, OSError) as exc:
                problems.append(f"{item['dest']}: download falhou ({exc}); baixe {item['url']} "
                                f"para {dest.relative_to(ROOT)} e rode com --offline.")
        if not dest.is_file():
            if offline:
                problems.append(f"{item['dest']}: ausente em {dest.relative_to(ROOT)}.")
            continue
        actual = sha256_of(dest)
        expected = item.get("sha256")
        if expected and actual != expected:
            problems.append(f"{item['dest']}: sha256 {actual} difere do registrado {expected}; "
                            "a fonte pode ter mudado. Revise a calibração antes de atualizar sources.json.")
        old = previous.get((source["id"], item["dest"]), {})
        obtained = old.get("obtido_em") if old.get("sha256") == actual else now
        files.append({"arquivo": item["dest"], "url": item["url"], "bytes": dest.stat().st_size,
                      "sha256": actual, "sha256_esperado": expected, "obtido_em": obtained})

    copy = None
    if source.get("copia_versionada"):
        copy_dir = ROOT / source["copia_versionada"]
        mismatched = [item["dest"] for item in source.get("files", [])
                      if not (copy_dir / item["dest"]).is_file()
                      or sha256_of(copy_dir / item["dest"]) != item.get("sha256")]
        copy = {"caminho": source["copia_versionada"], "confere_com_sha256": not mismatched}
        if mismatched:
            problems.append(f"cópia versionada difere do registrado: {', '.join(mismatched)}")

    divergent = any("difere" in p for p in problems)
    status = "divergente" if divergent else ("pendente" if problems else "ok")
    entry = {"id": source["id"], "titulo": source["titulo"], "licenca": source["licenca"],
             "pagina": source.get("pagina"), "modo": source.get("modo"), "status": status,
             "arquivos": files}
    if copy:
        entry["copia_versionada"] = copy
    if problems:
        entry["pendencias"] = problems
    return entry


# --------------------------------------------------------------------------- 3. agregar


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


def q(value: str) -> str:
    return json.dumps(value, ensure_ascii=False)


def render(diesel: dict | None, areas: dict[str, tuple[dict, list[dict]]], antt: dict) -> str:
    lines = [
        "# Gerado por data/synthetic/calibration/calibrate.py. Não editar à mão.",
        "# Só agregados de fontes públicas; procedência completa em manifest.json.",
        "# RASCUNHO para K03: regras de KPI ainda dependem de K02.",
        "",
        "diesel_preco_medio_consumidor:",
    ]
    if diesel is None:
        lines += ["  status: pendente", "  motivo: \"arquivo da ANP ausente em data/external/; ver manifest.json\""]
    else:
        lines += [
            f"  fonte: {q(diesel['fonte'])}",
            f"  arquivo: {q(ANP_FILE)}",
            f"  sha256: {q(diesel['sha256'])}",
            f"  obtido_em: {q(diesel['obtido_em'])}",
            "  unidade: R$/litro (valores correntes, média ponderada por vendas das distribuidoras)",
            f"  ano: {diesel['ano']}",
            "  por_uf:",
        ]
        lines += [f"    {uf}: {price:.4f}" for uf, price in sorted(diesel["por_uf"].items())]

    lines += [
        "",
        "distancias_da_sede:",
        "  fonte: \"kelvins/municipios-brasileiros (MIT), commit 503e2f7; área em empresas/<id>/area_atendimento.csv\"",
        "  metodo: \"haversine (raio 6371 km); distância de estrada = linha reta × fator_estrada de empresa.yaml\"",
    ]
    for empresa, (sede, distances) in sorted(areas.items()):
        kms = [d["km_linha_reta"] for d in distances]
        lines += [
            f"  {empresa}:",
            f"    sede: {q(sede['municipio'] + '/' + sede['uf'])}",
            f"    km_linha_reta_min: {min(kms):.1f}",
            f"    km_linha_reta_mediana: {statistics.median(kms):.1f}",
            f"    km_linha_reta_max: {max(kms):.1f}",
            "    municipios:",
        ]
        for d in sorted(distances, key=lambda d: (d["km_linha_reta"], d["codigo_ibge"])):
            lines.append(f"      - {{codigo_ibge: {d['codigo_ibge']}, municipio: {q(d['municipio'])}, "
                         f"uf: {d['uf']}, km_linha_reta: {d['km_linha_reta']:.1f}}}")

    antt_status = antt.get("status", "pendente")
    if antt_status == "ok":
        antt_status = "arquivo_presente_parser_pendente"
    lines += ["", "frota_rntrc:", f"  status: {antt_status}",
              "  motivo: \"parser só será escrito após conhecer as colunas reais; ver manifest.json\"",
              "  uso_previsto: \"proporção por tipo/carroceria na UF sede para conferir a frota suposta em empresa.yaml\""]
    return "\n".join(lines) + "\n"


def aggregate(manifest_by_id: dict[str, dict]) -> str:
    areas = {}
    for path in sorted(EMPRESAS.glob("*/area_atendimento.csv")):
        area = load_area(path)
        areas[path.parent.name] = (next(r for r in area if r["papel"] == "sede"), distances_from_sede(area))

    diesel = None
    anp_path = EXTERNAL / ANP_ID / ANP_FILE
    anp = manifest_by_id.get(ANP_ID, {})
    if anp_path.is_file() and anp.get("status") != "divergente":
        prices = parse_anp_diesel(anp_path, load_uf_names())
        year = latest_year(prices)
        entry = next((f for f in anp.get("arquivos", []) if f["arquivo"] == ANP_FILE), {})
        diesel = {"fonte": anp.get("titulo", ANP_ID), "sha256": entry.get("sha256", "desconhecido"),
                  "obtido_em": entry.get("obtido_em", "desconhecido"), "ano": year,
                  "por_uf": {uf: years[year] for uf, years in prices.items()}}
    return render(diesel, areas, manifest_by_id.get(ANTT_ID, {}))


# --------------------------------------------------------------------------- orquestração


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--offline", action="store_true", help="não acessa a rede; usa data/external/")
    args = parser.parse_args(argv)

    now = dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")
    previous = previous_entries()
    sources = json.loads(SOURCES.read_text(encoding="utf-8"))["sources"]

    print("1/3 Obter fontes")
    entries = []
    for source in sources:
        entry = obtain_source(source, args.offline, previous, now)
        entries.append(entry)
        print(f"  [{entry['status']}] {entry['id']}")

    print("2/3 Registrar procedência")
    manifest = {"_comentario": "Gerado por calibrate.py. Procedência das fontes públicas usadas na calibração.",
                "fontes": entries}
    MANIFEST.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"  gravado {MANIFEST.relative_to(ROOT)}")

    print("3/3 Agregar")
    OUTPUT.write_text(aggregate({e["id"]: e for e in entries}), encoding="utf-8")
    print(f"  gravado {OUTPUT.relative_to(ROOT)}")

    pending = [e for e in entries if e["status"] != "ok"]
    if pending:
        print("\nPendências:")
        for e in pending:
            for p in e.get("pendencias", []):
                print(f"- {e['id']}: {p}")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
