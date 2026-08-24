from pathlib import Path

import pytest


@pytest.fixture(autouse=True)
def isolated_database(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("FASTBOT_DATABASE", str(tmp_path / "fastbot.db"))
    from fastbot.config import settings
    settings.cache_clear()
    from fastbot import db
    db.init_db()
    yield
    settings.cache_clear()
