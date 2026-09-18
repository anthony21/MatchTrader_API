import pytest

from matchtrader.dashboard.cli import main


def test_dashboard_requires_built_frontend(tmp_path):
    with pytest.raises(SystemExit):
        main(["--assets", str(tmp_path)])
