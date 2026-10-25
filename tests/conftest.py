import os
import sys

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from comment_intel import pipeline, store  # noqa: E402


@pytest.fixture(autouse=True)
def _no_api_keys(monkeypatch):
    """Tests are offline: never let a real key on the machine reach the code."""
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.delenv("YOUTUBE_API_KEY", raising=False)
    monkeypatch.delenv("COMMENT_INTEL_MODEL", raising=False)


@pytest.fixture
def cfg():
    return pipeline.load_config(os.path.join(ROOT, "config.yaml"))


@pytest.fixture
def db(tmp_path):
    conn = store.connect(str(tmp_path / "test.db"))
    yield conn
    conn.close()


def make_comment(cid, text, likes=0, video="synthetic-vid-01", author="@JaneDoe"):
    return {"comment_id": cid, "video_id": video, "text": text, "likes": likes,
            "author": author, "published_at": "2026-01-01T00:00:00Z"}
