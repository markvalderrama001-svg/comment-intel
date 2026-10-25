from datetime import date

from comment_intel import briefing, comments_digest, per_channel_report, store
from conftest import make_comment

AS_OF = date(2026, 1, 31)


def _seed(db):
    store.save_video(db, "synthetic-vid-01", "Demo Channel", "Close Basics (Demo)")
    store.save_comment(db, make_comment("synthetic-c-1", "How do I close | fast?", likes=9),
                       "Demo Channel")
    store.save_comment(db, make_comment("synthetic-c-2", "ok", likes=0, author="@AlexRivera"),
                       "Demo Channel")
    store.save_idea(db, {"title": "Low idea", "channel": "Demo Channel", "score": 6,
                         "category": "question", "rationale": "meh"})
    store.save_idea(db, {"title": "Close | in a day", "channel": "Demo Channel", "score": 9,
                         "category": "how-to", "rationale": "Asked a lot.",
                         "source_comment": "How do I close | fast?",
                         "author": "@JaneDoe", "video_id": "synthetic-vid-01"})
    db.commit()


def test_ideas_report_ranks_by_score_and_links_lineage(db):
    _seed(db)
    md = per_channel_report.render_ideas(db, "Demo Channel", AS_OF)
    assert md.startswith("# Demo Channel: Video Ideas")
    assert "Updated 2026-01-31 · 2 ideas" in md
    assert "## 1. Close | in a day" in md and "## 2. Low idea" in md
    assert "| 1 | 9/10 | how-to | Close \\| in a day |" in md  # pipe escaped in table
    assert "**Credit the commenter:** @JaneDoe" in md
    assert "[Close Basics (Demo)](https://www.youtube.com/watch?v=synthetic-vid-01)" in md
    assert "> How do I close | fast?" in md


def test_ideas_report_empty_channel(db):
    assert "_No ideas yet._" in per_channel_report.render_ideas(db, "Nobody", AS_OF)


def test_comments_report_most_liked_first(db):
    _seed(db)
    md = per_channel_report.render_comments(db, "Demo Channel", AS_OF)
    assert md.index("[9 likes] @JaneDoe") < md.index("[0 likes] @AlexRivera")


def test_write_all_creates_two_files_per_channel(db, tmp_path):
    _seed(db)
    paths = per_channel_report.write_all(db, str(tmp_path), AS_OF)
    names = sorted(p.split("\\")[-1].split("/")[-1] for p in paths)
    assert names == ["Demo Channel - Comments.md", "Demo Channel - Video Ideas.md"]


def test_briefing_delivers_each_idea_once(db, tmp_path):
    _seed(db)
    first = open(briefing.write(db, str(tmp_path), AS_OF), encoding="utf-8").read()
    assert "**2 new ideas**" in first
    assert briefing.render(db, AS_OF).endswith("_No new ideas today._\n")


def test_digest_counts(db):
    _seed(db)
    assert "**2 comments** captured across 1 channels" in comments_digest.render(db, AS_OF)
