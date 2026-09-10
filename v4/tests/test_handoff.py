import hashlib
import importlib.util
import json
from pathlib import Path
from zipfile import ZipFile


def load_builder():
    spec = importlib.util.spec_from_file_location(
        "handoff", Path(__file__).parents[1] / "scripts/build_handoff.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_archive_excludes_local_credentials_and_reports(tmp_path):
    files = {
        ".env": "SECRET",
        ".env.txt": "SECRET",
        "private.env": "SECRET",
        ".env.example": "MTR_PASSWORD=",
        "pyproject.toml": "[project]\nname = 'hcamm-matchtrader'\n",
        "poetry.lock": "# Locked dependencies\n",
        "poetry.toml": "[virtualenvs]\nin-project = true\n",
        "src/matchtrader/api.py": "pass\n",
        "src/matchtrader/.env.json": "SECRET",
        "data/trades.csv": "PRIVATE",
        "docs/guide.md": "Instructions",
        ".agents/skills/client/SKILL.md": "Skill",
        ".venv/file.py": "PRIVATE",
        "screenshots/private.png": "PRIVATE",
        "frontend/src/App.vue": "<template>Dashboard</template>",
        "frontend/package-lock.json": "{}",
        "frontend/src/react/Activity.jsx": "export default function Activity() {}",
        "frontend/dist/assets/bundle.js": "PRIVATE BUILD",
        "frontend/node_modules/dependency/index.js": "DEPENDENCY",
        "frontend/.env.local": "SECRET",
    }
    for name, value in files.items():
        path = tmp_path / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(value)
    output = tmp_path / "dist/test.zip"
    manifest = load_builder().build(tmp_path, output)
    assert {row["path"] for row in manifest} == {
        ".env.example",
        "pyproject.toml",
        "poetry.lock",
        "poetry.toml",
        "src/matchtrader/api.py",
        "docs/guide.md",
        ".agents/skills/client/SKILL.md",
        "frontend/src/App.vue",
        "frontend/package-lock.json",
        "frontend/src/react/Activity.jsx",
    }
    with ZipFile(output) as archive:
        assert all(name.startswith("matchtrader-python/v4/") for name in archive.namelist())
        recorded = json.loads(archive.read("matchtrader-python/v4/HANDOFF-MANIFEST.json"))
        for row in recorded:
            content = archive.read("matchtrader-python/v4/" + row["path"])
            assert hashlib.sha256(content).hexdigest() == row["sha256"]
            assert len(content) == row["bytes"]
