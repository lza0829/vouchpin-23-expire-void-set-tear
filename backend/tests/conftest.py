from __future__ import annotations
import os
import tempfile

os.environ.setdefault("DATA_DIR", tempfile.mkdtemp(prefix="vouchpin-test-"))

import pytest
from fastapi.testclient import TestClient

import app.db as db
from app.seed import seed_if_empty
from app.main import app


@pytest.fixture()
def client(tmp_path, monkeypatch):
    db_path = tmp_path / "test.db"
    monkeypatch.setattr(db, "DB_PATH", db_path)
    seed_if_empty()
    return TestClient(app)
