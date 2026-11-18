"""Validate repository scaffolding and local Markdown links, not product behavior."""

from pathlib import Path
import re
import sys
from urllib.parse import unquote, urlsplit


ROOT = Path(__file__).resolve().parents[1]
REQUIRED = (
    "README.md",
    "LICENSE",
    "AGENTS.md",
    "CONTRIBUTING.md",
    "SECURITY.md",
    "docs/scope.md",
    "docs/architecture.md",
    "docs/hackathon.md",
    "docs/workflow.md",
    ".github/ISSUE_TEMPLATE/task.yml",
    ".github/ISSUE_TEMPLATE/bug.yml",
    ".github/pull_request_template.md",
    ".github/workflows/ci.yml",
)
SKIP_DIRS = {".git", ".venv", "venv", "node_modules", "__pycache__", "artifacts", "runs"}


def source_files():
    for path in ROOT.rglob("*"):
        if path.is_file() and not any(part in SKIP_DIRS for part in path.relative_to(ROOT).parts):
            if path.suffix in {".md", ".py", ".yml", ".yaml", ".json", ".toml"}:
                yield path


def main():
    errors = []
    for relative in REQUIRED:
        if not (ROOT / relative).is_file():
            errors.append(f"Missing required file: {relative}")

    checked = 0
    for path in source_files():
        checked += 1
        relative = path.relative_to(ROOT)
        try:
            text = path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            errors.append(f"Invalid UTF-8: {relative}")
            continue
        if re.search(r"^(?:<{7} |={7}$|>{7} )", text, flags=re.MULTILINE):
            errors.append(f"Unresolved merge marker: {relative}")
        if path.suffix == ".py":
            try:
                compile(text, str(relative), "exec")
            except SyntaxError as exc:
                errors.append(f"Python syntax: {relative}:{exc.lineno}: {exc.msg}")
        if path.suffix != ".md":
            continue
        prose = re.sub(r"```.*?```", "", text, flags=re.DOTALL)
        for destination in re.findall(r"\]\(([^\s)]+)(?:\s+\"[^\"]*\")?\)", prose):
            destination = destination.strip("<>")
            parts = urlsplit(destination)
            if parts.scheme or parts.netloc or not parts.path:
                continue
            target = (path.parent / unquote(parts.path)).resolve()
            if not target.is_relative_to(ROOT):
                errors.append(f"Link outside repository: {relative} -> {destination}")
            elif not target.exists():
                errors.append(f"Broken local link: {relative} -> {destination}")

    if errors:
        print("Repository structure check failed:")
        for error in errors:
            print(f"- {error}")
        return 1
    print(f"Repository structure valid ({checked} text files checked).")
    print("This checks scaffolding, local link targets and Python syntax; it does not test the product.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
