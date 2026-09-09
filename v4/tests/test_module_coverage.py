from pathlib import Path

import matchtrader


def test_every_library_module_has_a_specific_test_file():
    source = Path(matchtrader.__file__).parent
    tests = Path(__file__).parent
    missing = []
    for module in source.rglob("*.py"):
        relative = module.relative_to(source)
        expected = tests / relative.parent / ("test_" + relative.name)
        if not expected.exists():
            missing.append(str(relative))
    assert missing == [], f"Modules without a dedicated unit test: {missing}"
