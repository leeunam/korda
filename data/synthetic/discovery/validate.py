"""Confere os materiais fictícios da descoberta, sem executar agentes ou acessar a rede."""

import json
from pathlib import Path, PurePosixPath
from typing import Literal
from urllib.parse import urlsplit

from pydantic import BaseModel, ConfigDict, Field, field_validator

HERE = Path(__file__).resolve().parent
CASE = HERE / "01_demo"


class FixtureModel(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, str_min_length=1)


class Participant(FixtureModel):
    id: str
    name: str
    role: Literal["operacao", "financeiro", "dados"]


def synthetic_url(value):
    parsed = urlsplit(value)
    if parsed.scheme != "https" or not (parsed.hostname or "").endswith(".example"):
        raise ValueError("a fixture usa somente URLs fictícias https em .example")
    return value


class Form(FixtureModel):
    fixture_version: Literal["1.0.0"]
    synthetic: Literal[True]
    company_id: Literal["01_demo"]
    company_name: str
    site_url: str
    headquarters: str
    period_start: str = Field(pattern=r"^\d{4}-\d{2}-\d{2}$")
    period_end: str = Field(pattern=r"^\d{4}-\d{2}-\d{2}$")
    goal: str
    declared_systems: list[str] = Field(min_length=1)
    participants: list[Participant] = Field(min_length=1)

    _url = field_validator("site_url")(synthetic_url)


class ResearchSource(FixtureModel):
    id: str
    origin: Literal["fornecida", "descoberta"]
    scope: Literal["empresa", "setor"]
    version: str
    captured_on: str = Field(pattern=r"^\d{4}-\d{2}-\d{2}$")
    original_url: str
    path: str

    _url = field_validator("original_url")(synthetic_url)

    @field_validator("path")
    @classmethod
    def research_path(cls, value):
        path = PurePosixPath(value)
        if "\\" in value or path.is_absolute() or ".." in path.parts:
            raise ValueError("caminho de pesquisa precisa ser relativo a inputs/")
        if path.parts[0] != "pesquisa" or path.suffix != ".md":
            raise ValueError("somente páginas de pesquisa entram no catálogo")
        return value


class Turn(FixtureModel):
    id: str
    session_id: str
    participant_id: str
    intent: str
    question_example: str
    answer: str


class Script(FixtureModel):
    fixture_version: Literal["1.0.0"]
    synthetic: Literal[True]
    company_id: Literal["01_demo"]
    turns: list[Turn] = Field(min_length=1)


def read_json(path):
    return json.loads(path.read_text(encoding="utf-8"))


def unique_ids(items):
    ids = [item.id for item in items]
    if len(set(ids)) != len(ids):
        raise ValueError("IDs repetidos na fixture")


def load_fixture(case=CASE):
    inputs = (case / "inputs").resolve()
    form = Form.model_validate(read_json(inputs / "formulario.json"))
    sources = [ResearchSource.model_validate(item) for item in read_json(inputs / "fontes.json")]
    script = Script.model_validate(read_json(case / "personas" / "roteiro.json"))
    for group in (form.participants, sources, script.turns):
        unique_ids(group)
    participants = {p.id for p in form.participants}
    if any(t.participant_id not in participants for t in script.turns):
        raise ValueError("turno com participante desconhecido")
    for source in sources:
        path = (inputs / source.path).resolve()
        if not path.is_relative_to(inputs) or not path.is_file():
            raise ValueError("página ausente ou fora de inputs/")
        if "sintético" not in path.read_text(encoding="utf-8").lower():
            raise ValueError("página precisa identificar seu caráter sintético")
    return form, sources, script


if __name__ == "__main__":
    form, sources, script = load_fixture()
    print(f"[ok] {form.company_id}: formulário, {len(sources)} páginas e {len(script.turns)} falas sintéticas")
