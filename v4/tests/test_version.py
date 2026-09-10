import json
import re
import tomllib
from pathlib import Path

from matchtrader.version import EVENT_SCHEMA_VERSION, MAPPING_SCHEMA_VERSION, VERSION


def test_release_metadata_and_independent_schema_versions():
    root = Path(__file__).parents[1]
    assert tomllib.loads((root / 'pyproject.toml').read_text())['project']['version'] == VERSION
    assert json.loads((root / 'frontend/package.json').read_text())['version'] == VERSION
    for value in (VERSION, EVENT_SCHEMA_VERSION, MAPPING_SCHEMA_VERSION):
        assert re.fullmatch(r'\d+\.\d+\.\d+', value)
