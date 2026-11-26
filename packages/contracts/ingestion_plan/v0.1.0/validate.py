"""Valida a seção de ingestão do plano: JSON Schema + regras semânticas.

Uso: python3 packages/contracts/ingestion_plan/v0.1.0/validate.py <plano.json> [...]
Requer requirements-contracts.txt (jsonschema). Sai com 1 se algum arquivo for inválido.

Regras além do schema (o que o schema sozinho não expressa):
- toda fonte tem evidência ou lacuna: o que a entrevista não cobre vira lacuna, não suposição;
- volume com base `suposicao` exige uma lacuna aberta na mesma fonte;
- `incremental_campo` exige `incremental_key`; os outros métodos não a aceitam;
- `postgres` e `api_http` exigem `credentials_env`; arquivos e pastas não recebem credencial;
- testes de aceite obrigatórios: completude e idempotência para todas as fontes, incremental
  para fontes incrementais, mudança de esquema e resiliência para `api_http` e `postgres`;
- lacuna bloqueante aberta impede `pronto_para_aprovacao`;
- ids únicos e referências (lacunas, fontes) existentes; `per_day_min <= per_day_max`.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import jsonschema

SCHEMA = json.loads((Path(__file__).parent / "ingestion_plan.schema.json").read_text(encoding="utf-8"))
COM_REDE = {"postgres", "api_http"}


def erros_semanticos(plano: dict) -> list[str]:
    erros: list[str] = []
    fontes = {f["id"]: f for f in plano["sources"]}
    if len(fontes) != len(plano["sources"]):
        erros.append("ids de fonte repetidos")
    lacunas = {g["id"]: g for g in plano["gaps"]}
    if len(lacunas) != len(plano["gaps"]):
        erros.append("ids de lacuna repetidos")
    for g in plano["gaps"]:
        if g["source_id"] not in fontes:
            erros.append(f"lacuna {g['id']}: fonte inexistente {g['source_id']}")

    for f in plano["sources"]:
        fid = f["id"]
        if not f["evidence_ids"] and not f["gap_ids"]:
            erros.append(f"{fid}: sem evidência nem lacuna")
        for gid in f["gap_ids"]:
            if gid not in lacunas:
                erros.append(f"{fid}: lacuna inexistente {gid}")
            elif lacunas[gid]["source_id"] != fid:
                erros.append(f"{fid}: lacuna {gid} pertence a outra fonte")
        abertas = [g for g in plano["gaps"] if g["source_id"] == fid and g["state"] == "aberta"]
        incremental = f["method"] == "incremental_campo"
        if incremental != (f["incremental_key"] is not None):
            erros.append(f"{fid}: incremental_key só existe (e é obrigatória) com incremental_campo")
        if f["kind"] in COM_REDE and not f["credentials_env"]:
            erros.append(f"{fid}: {f['kind']} exige credentials_env")
        if f["kind"] not in COM_REDE and f["credentials_env"]:
            erros.append(f"{fid}: {f['kind']} não recebe credencial")
        for o in f["objects"]:
            v = o["expected_volume"]
            if v["per_day_min"] > v["per_day_max"]:
                erros.append(f"{fid}.{o['name']}: per_day_min > per_day_max")
            if v["basis"] == "suposicao" and not abertas:
                erros.append(f"{fid}.{o['name']}: volume suposto exige lacuna aberta na fonte")

        exigidos = {"completude", "idempotencia"}
        if incremental:
            exigidos.add("incremental")
        if f["kind"] in COM_REDE:
            exigidos |= {"mudanca_esquema", "resiliencia"}
        cobertos = {t["kind"] for t in plano["acceptance_tests"] if fid in t["source_ids"]}
        for falta in sorted(exigidos - cobertos):
            erros.append(f"{fid}: falta teste de aceite '{falta}'")

    for t in plano["acceptance_tests"]:
        for sid in t["source_ids"]:
            if sid not in fontes:
                erros.append(f"teste {t['id']}: fonte inexistente {sid}")
    bloqueantes = [g["id"] for g in plano["gaps"] if g["blocking"] and g["state"] == "aberta"]
    if bloqueantes and plano["state"] == "pronto_para_aprovacao":
        erros.append(f"lacunas bloqueantes abertas impedem pronto_para_aprovacao: {bloqueantes}")
    return erros


def validar(plano: dict) -> list[str]:
    validador = jsonschema.Draft202012Validator(SCHEMA)
    erros = [f"{'/'.join(map(str, e.absolute_path)) or '(raiz)'}: {e.message}"
             for e in sorted(validador.iter_errors(plano), key=lambda e: list(e.absolute_path))]
    return erros or erros_semanticos(plano)


def main(argv: list[str]) -> int:
    if not argv:
        print(__doc__.splitlines()[2], file=sys.stderr)
        return 2
    falhou = False
    for caminho in argv:
        erros = validar(json.loads(Path(caminho).read_text(encoding="utf-8")))
        print(f"{caminho}: {'ok' if not erros else 'INVÁLIDO'}")
        for e in erros:
            print(f"  - {e}")
        falhou |= bool(erros)
    return 1 if falhou else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
