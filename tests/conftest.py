import os
import sys
import tempfile
from pathlib import Path

# Must happen before importing common: point everything at a throwaway data dir and disable cloud sync.
_TMP = Path(tempfile.mkdtemp(prefix="watcher-test-"))
os.environ["WATCHER_DATA_DIR"] = str(_TMP / "data")
os.environ["WATCHER_REPORTS_DIR"] = str(_TMP / "reports")
os.environ["WATCHER_CLOUD_URL"] = ""
os.environ["INGEST_TOKEN"] = ""
os.environ["ANTHROPIC_API_KEY"] = "test-key-not-real"
os.environ.pop("PRIVATE_PATTERN", None)
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import pytest  # noqa: E402

import common  # noqa: E402

assert "watcher-test-" in str(common.DB_PATH), "tests must never touch the real DB"


@pytest.fixture
def con(tmp_path):
    c = common.db(tmp_path / "t.db")
    for f in common.SHOTS.iterdir():
        f.unlink()
    yield c
    c.close()
