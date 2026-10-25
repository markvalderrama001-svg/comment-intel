"""YouTube client against a fake API object (no network)."""
from types import SimpleNamespace

from comment_intel import youtube_client as yt


class _Req:
    def __init__(self, fn):
        self.fn = fn

    def execute(self):
        return self.fn()


def _thread(cid, text):
    return {"snippet": {"topLevelComment": {"id": cid, "snippet": {
        "textDisplay": text, "likeCount": 1, "authorDisplayName": "@JaneDoe",
        "publishedAt": "2026-01-01T00:00:00Z"}}}}


class FakeYouTube:
    def __init__(self, pages, errors=()):
        self.pages, self.errors, self.calls = pages, list(errors), 0

    def commentThreads(self):
        def list_(**kw):
            def run():
                self.calls += 1
                if self.errors:
                    raise self.errors.pop(0)
                return self.pages[kw.get("pageToken")]
            return _Req(run)
        return SimpleNamespace(list=list_)


def _http_error(status):
    err = yt.HttpError.__new__(yt.HttpError)
    err.resp = SimpleNamespace(status=status)
    return err


def test_fetch_comments_follows_pages():
    fake = FakeYouTube({None: {"items": [_thread("synthetic-c-1", "a")], "nextPageToken": "p2"},
                        "p2": {"items": [_thread("synthetic-c-2", "b")]}})
    out = list(yt.fetch_comments(fake, "synthetic-vid-01", sleep=lambda s: None))
    assert [c["comment_id"] for c in out] == ["synthetic-c-1", "synthetic-c-2"]
    assert out[0]["video_id"] == "synthetic-vid-01"


def test_fetch_comments_skips_disabled_video():
    fake = FakeYouTube({}, errors=[_http_error(403)])
    assert list(yt.fetch_comments(fake, "synthetic-vid-01", sleep=lambda s: None)) == []


def test_fetch_comments_retries_rate_limit_then_succeeds():
    slept = []
    fake = FakeYouTube({None: {"items": [_thread("synthetic-c-1", "a")]}},
                       errors=[_http_error(429), _http_error(503)])
    out = list(yt.fetch_comments(fake, "synthetic-vid-01", sleep=slept.append))
    assert len(out) == 1 and fake.calls == 3
    assert slept == [2, 4]  # exponential back-off
