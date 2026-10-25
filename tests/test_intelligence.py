import json
from types import SimpleNamespace

import pytest

from comment_intel import intelligence as intel

TH = {"min_likes": 2, "min_length": 40}


@pytest.mark.parametrize("text,likes,expected", [
    ("first!", 0, False),                       # junk
    ("nice", 1, False),                         # short, not upvoted
    ("nice", 2, True),                          # crowd upvoted it
    ("Is this in the playlist?", 0, True),      # a real question (>= 15 chars)
    ("why?", 0, False),                         # question but too short
    ("x" * 40, 0, True),                        # substantive length
    ("x" * 39, 0, False),
    ("", 0, False),
    (None, 0, False),
])
def test_prefilter(text, likes, expected):
    assert intel.is_high_signal(text, likes, TH) is expected


def test_parse_ideas_handles_prose_and_garbage():
    assert intel.parse_ideas('Sure! [{"title": "A", "score": 7}] hope that helps') == \
        [{"title": "A", "score": 7}]
    assert intel.parse_ideas("no json here") == []
    assert intel.parse_ideas("[not valid json]") == []
    assert intel.parse_ideas('[1, "x", {"title": "B"}]') == [{"title": "B"}]


def test_clean_idea_clamps_and_attaches_lineage():
    comments = [{"comment_id": "synthetic-c-1", "text": "How do I close?", "likes": 3,
                 "author": "@JaneDoe", "video_id": "synthetic-vid-01"}]
    idea = intel.clean_idea({"comment_index": 0, "title": "  Close  fast ", "score": 14,
                             "category": "Unknown"}, comments)
    assert idea["title"] == "Close fast"
    assert idea["score"] == 10
    assert idea["category"] == "curiosity"
    assert idea["author"] == "@JaneDoe" and idea["video_id"] == "synthetic-vid-01"
    assert idea["source_comment"] == "How do I close?"


def test_clean_idea_rejects_bad_rows():
    assert intel.clean_idea({"title": "", "score": 5}, []) is None
    assert intel.clean_idea({"title": "X", "score": "high"}, []) is None
    # out-of-range index is ignored, not an error
    assert "author" not in intel.clean_idea({"title": "X", "score": 5, "comment_index": 9}, [])


class FakeMessages:
    def __init__(self, reply):
        self.reply, self.calls = reply, []

    def create(self, **kw):
        self.calls.append(kw)
        return SimpleNamespace(content=[SimpleNamespace(type="text", text=self.reply)])


def test_claude_scorer_uses_configured_model_and_parses_reply():
    reply = json.dumps([{"comment_index": 0, "title": "Month-end close in a day",
                         "score": 8, "category": "how-to", "rationale": "Asked often."}])
    fake = SimpleNamespace(messages=FakeMessages(reply))
    scorer = intel.ClaudeScorer("claude-haiku-4-5", client=fake)
    comments = [{"comment_id": "synthetic-c-1", "text": "How do I close in a day?",
                 "likes": 4, "author": "@SamLee", "video_id": "synthetic-vid-01"}]
    ideas = scorer.score("Demo Channel", comments)
    call = fake.messages.calls[0]
    assert call["model"] == "claude-haiku-4-5"
    assert "[0] (likes:4) How do I close in a day?" in call["messages"][0]["content"]
    assert ideas[0]["title"] == "Month-end close in a day"
    assert ideas[0]["author"] == "@SamLee"
