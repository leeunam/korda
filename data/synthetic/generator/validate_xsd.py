"""Valida todos os XML de CT-e gerados contra os XSD versionados do CT-e 4.00.

Uso:
    .venv/bin/python data/synthetic/generator/validate_xsd.py --all
    .venv/bin/python data/synthetic/generator/validate_xsd.py --empresa 01_demo

- cteProc       -> procCTe_v4.00.xsd; o conteúdo de infModal/rodo -> cteModalRodoviario_v4.00.xsd
- procEventoCTe -> procEventoCTe_v4.00.xsd; detEvento/evCancCTe -> evCancCTe_v4.00.xsd
Sai com código 1 se qualquer arquivo falhar.
"""

from __future__ import annotations

import argparse
import sys
from functools import lru_cache
from pathlib import Path

from lxml import etree

SYNTHETIC = Path(__file__).resolve().parents[1]
XSD_DIR = SYNTHETIC / "reference" / "cte-xsd" / "PL_CTe_400"
OUTPUT = SYNTHETIC / "output"
EMPRESAS = SYNTHETIC / "empresas"
NS = "{http://www.portalfiscal.inf.br/cte}"


@lru_cache(maxsize=None)
def schema(name: str) -> etree.XMLSchema:
    return etree.XMLSchema(etree.parse(str(XSD_DIR / name)))


def validate_file(path: Path) -> list[str]:
    doc = etree.parse(str(path))
    root = doc.getroot()
    checks: list[tuple[str, etree._Element]] = []
    if root.tag == f"{NS}cteProc":
        checks.append(("procCTe_v4.00.xsd", root))
        rodo = root.find(f".//{NS}infModal/{NS}rodo")
        if rodo is None:
            return [f"{path.name}: infModal/rodo ausente"]
        checks.append(("cteModalRodoviario_v4.00.xsd", rodo))
    elif root.tag == f"{NS}procEventoCTe":
        checks.append(("procEventoCTe_v4.00.xsd", root))
        canc = root.find(f".//{NS}detEvento/{NS}evCancCTe")
        if canc is None:
            return [f"{path.name}: evCancCTe ausente"]
        checks.append(("evCancCTe_v4.00.xsd", canc))
    else:
        return [f"{path.name}: raiz inesperada {root.tag}"]

    errors = []
    for xsd, element in checks:
        sch = schema(xsd)
        target = etree.ElementTree(etree.fromstring(etree.tostring(element)))
        if not sch.validate(target):
            for err in list(sch.error_log)[:3]:
                errors.append(f"{path.name} [{xsd}] linha {err.line}: {err.message}")
    return errors


def validate_dir(folder: Path) -> tuple[int, list[str]]:
    files = sorted(folder.glob("*.xml"))
    errors: list[str] = []
    for path in files:
        errors.extend(validate_file(path))
    return len(files), errors


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--empresa")
    group.add_argument("--all", action="store_true")
    args = parser.parse_args(argv)
    empresas = sorted(p.name for p in EMPRESAS.iterdir() if p.is_dir()) if args.all else [args.empresa]

    failed = False
    for empresa in empresas:
        count, errors = validate_dir(OUTPUT / empresa / "cte")
        status = "ok" if not errors and count else "FALHOU"
        print(f"[{status}] {empresa}: {count} XML validados, {len(errors)} erro(s)")
        for err in errors[:20]:
            print(f"  - {err}")
        failed = failed or bool(errors) or count == 0
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
