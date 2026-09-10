"""Build a portable source handoff using an explicit file allowlist."""

import argparse
import hashlib
import json
from pathlib import Path
from zipfile import ZIP_DEFLATED, ZipFile

ROOT_FILES = {
    "README.md",
    "agent.md",
    "AGENTS.md",
    "pyproject.toml",
    ".env.example",
    ".gitignore",
    ".dockerignore",
    "Dockerfile",
    "compose.yaml",
    "poetry.lock",
    "poetry.toml",
}
ARCHIVE_ROOT = "matchtrader-python/v4"
TREES = {"src", "tests", "scripts", "docs", ".agents", "frontend", "quantower"}
SUFFIXES = {".py", ".md", ".json", ".yaml", ".yml", ".js", ".jsx", ".vue", ".css", ".html", ".cs", ".csproj"}
EXCLUDED = {
    "__pycache__",
    ".pytest_cache",
    ".ruff_cache",
    "data",
    ".venv",
    "node_modules",
    "dist",
    "test-results",
    "playwright-report",
    "bin",
    "obj",
}


def selected_files(root: Path):
    """Symlinks and arbitrary runtime folders never enter the archive."""
    root = root.resolve()
    for path in sorted(root.rglob("*")):
        relative = path.relative_to(root)
        if not path.is_file() or path.is_symlink():
            continue
        if any((root / Path(*relative.parts[:n])).is_symlink() for n in range(1, len(relative.parts))):
            continue
        if any(part in EXCLUDED for part in relative.parts):
            continue
        if len(relative.parts) == 1:
            allowed = relative.name in ROOT_FILES
        else:
            allowed = relative.parts[0] in TREES and path.suffix in SUFFIXES
            allowed = allowed and not any(
                part.startswith(".env") or part.endswith(".env") for part in relative.parts
            )
        if allowed:
            yield path, relative.as_posix()


def build(root: Path, output: Path):
    files = list(selected_files(root))
    output.parent.mkdir(parents=True, exist_ok=True)
    manifest = []
    with ZipFile(output, "w", compression=ZIP_DEFLATED) as archive:
        for path, name in files:
            content = path.read_bytes()
            archive.writestr(ARCHIVE_ROOT + "/" + name, content)
            manifest.append(
                {"path": name, "bytes": len(content), "sha256": hashlib.sha256(content).hexdigest()}
            )
        archive.writestr(ARCHIVE_ROOT + "/HANDOFF-MANIFEST.json", json.dumps(manifest, indent=2))
    return manifest


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=Path("dist/matchtrader-v4-handoff.zip"))
    args = parser.parse_args()
    result = build(Path(__file__).resolve().parents[1], args.output)
    print(f"Packaged {len(result)} files: {args.output.resolve()}")
