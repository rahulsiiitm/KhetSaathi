import pytest

import store


@pytest.fixture(autouse=True)
def isolated_database(tmp_path, monkeypatch):
    """Give every test its own SQLite file so tests never share cache or health state."""
    monkeypatch.setattr(store, "DB_PATH", tmp_path / "test.db")
