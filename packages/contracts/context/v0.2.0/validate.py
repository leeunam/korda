"""Validate the interview context and optional continuity with a previous revision."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

import jsonschema

ROOT = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(ROOT / "services/context"))
from korda_context.domain import ContextDocument  # noqa: E402


def validate(document: dict, previous: dict | None = None) -> ContextDocument:
    schema = json.loads(Path(__file__).with_name("context.schema.json").read_text(encoding="utf-8"))
    jsonschema.Draft202012Validator(schema, format_checker=jsonschema.FormatChecker()).validate(document)
    result = ContextDocument.model_validate(document)
    if previous is not None:
        prior = ContextDocument.model_validate(previous)
        if result.project_id != prior.project_id or result.revision != prior.revision + 1:
            raise ValueError("history requires the next revision of the same project")
        if result.required_topics != prior.required_topics or result.created_at != prior.created_at:
            raise ValueError("project configuration cannot be rewritten by a context revision")
        if not set(prior.processed_input_ids) <= set(result.processed_input_ids):
            raise ValueError("processed input history was lost")
        for name in ("evidence", "claims", "entities", "relations", "gaps"):
            old = {item.id: item for item in getattr(prior, name)}
            new = {item.id: item for item in getattr(result, name)}
            if not old.keys() <= new.keys():
                raise ValueError(f"{name} history was lost")
            for key, item in old.items():
                updated = new[key]
                if name == "evidence" and item != updated:
                    raise ValueError("evidence history cannot be rewritten")
                fixed = {
                    "claims": ("topic", "key", "kind", "statement", "value", "unit", "time_scope"),
                    "entities": ("topic", "name", "kind"),
                    "relations": ("topic", "source_id", "target_id", "kind"),
                    "gaps": ("topic", "key"),
                }.get(name, ())
                if any(getattr(item, field) != getattr(updated, field) for field in fixed):
                    raise ValueError(f"{name} history cannot be rewritten")
                if hasattr(item, "evidence_ids") and not set(item.evidence_ids) <= set(updated.evidence_ids):
                    raise ValueError(f"{name} evidence history was lost")
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("files", nargs="+", type=Path)
    parser.add_argument("--previous", type=Path)
    arguments = parser.parse_args()
    previous = json.loads(arguments.previous.read_text(encoding="utf-8")) if arguments.previous else None
    try:
        for file in arguments.files:
            result = validate(json.loads(file.read_text(encoding="utf-8")), previous)
            print(f"{file.name}: valid v0.2.0 project={result.project_id} revision={result.revision}")
            previous = result.model_dump(mode="json") if arguments.previous else None
    except (ValueError, jsonschema.ValidationError) as error:
        print(f"Invalid context: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
