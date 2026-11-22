"""Baixa as fontes públicas de calibração para data/external/ e registra procedência.

Uso:
    python3 data/synthetic/calibration/download.py            # baixa o que for automático
    python3 data/synthetic/calibration/download.py --manual   # só confere arquivos já presentes
    python3 data/synthetic/calibration/download.py --only anp_anuario_2026_t3_21

Para cada fonte grava data/external/<id>/manifest.json com URL, data de acesso,
tamanho e sha256. Divergência de checksum é reportada, não corrigida: a fonte
pode ter sido republicada e a calibração precisa ser revista por uma pessoa.
Só biblioteca padrão.
"""

from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import sys
import urllib.error
import urllib.request
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
EXTERNAL = ROOT / "data" / "external"
SOURCES = HERE / "sources.json"
USER_AGENT = "korda-calibration/0.1 (+https://github.com/leeunam/korda)"
TIMEOUT_S = 60


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


def process_source(source: dict, manual: bool) -> list[str]:
    """Baixa/confere uma fonte e devolve a lista de problemas encontrados."""
    problems: list[str] = []
    folder = EXTERNAL / source["id"]
    folder.mkdir(parents=True, exist_ok=True)
    now = dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")
    entries = []

    if source.get("modo") == "manual" and not source.get("files"):
        present = sorted(p for p in folder.iterdir() if p.is_file() and p.name != "manifest.json")
        if not present:
            problems.append(f"{source['id']}: fonte manual ausente. {source.get('instrucoes', '')}")
        for path in present:
            entries.append({"arquivo": path.name, "url": source.get("pagina"), "obtido_em": now,
                            "bytes": path.stat().st_size, "sha256": sha256_of(path), "modo": "manual"})
    for item in source.get("files", []):
        dest = folder / item["dest"]
        if not manual:
            try:
                fetch(item["url"], dest)
            except (urllib.error.URLError, TimeoutError, OSError) as exc:
                problems.append(f"{source['id']}/{item['dest']}: download falhou ({exc}). "
                                f"Baixe manualmente {item['url']} para {dest.relative_to(ROOT)}.")
        if not dest.is_file():
            if manual:
                problems.append(f"{source['id']}/{item['dest']}: arquivo ausente em {dest.relative_to(ROOT)}.")
            continue
        actual = sha256_of(dest)
        expected = item.get("sha256")
        if expected and actual != expected:
            problems.append(f"{source['id']}/{item['dest']}: sha256 {actual} difere do registrado {expected}. "
                            "A fonte pode ter mudado; revise a calibração antes de atualizar sources.json.")
        entries.append({"arquivo": item["dest"], "url": item["url"], "obtido_em": now,
                        "bytes": dest.stat().st_size, "sha256": actual, "sha256_esperado": expected,
                        "modo": "manual" if manual else "automatico"})

    manifest = {"id": source["id"], "titulo": source["titulo"], "licenca": source["licenca"],
                "pagina": source.get("pagina"), "arquivos": entries}
    (folder / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
                                          encoding="utf-8")
    return problems


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--manual", action="store_true", help="não acessa a rede; só confere e registra")
    parser.add_argument("--only", action="append", help="id da fonte (pode repetir)")
    args = parser.parse_args(argv)

    sources = json.loads(SOURCES.read_text(encoding="utf-8"))["sources"]
    if args.only:
        sources = [s for s in sources if s["id"] in args.only]

    all_problems: list[str] = []
    for source in sources:
        problems = process_source(source, args.manual)
        status = "ok" if not problems else "PENDENTE"
        print(f"[{status}] {source['id']}")
        all_problems.extend(problems)

    if all_problems:
        print("\nPendências:")
        for problem in all_problems:
            print(f"- {problem}")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
