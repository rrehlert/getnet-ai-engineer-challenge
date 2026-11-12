import pytest

from app.settings import get_settings


@pytest.fixture(autouse=True)
def state_dir_in_tmp(tmp_path, monkeypatch):
    """Any app built without an injected store (or index) keeps its state under `tmp_path`, never in the repo."""
    monkeypatch.setenv("STATE_DIR", str(tmp_path / "state"))
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()
