"""Load: idempotent SQLite storage.

Three layers of de-duplication make every run safe to repeat:
  1. comments.comment_id is the PRIMARY KEY and rows go in with INSERT OR IGNORE,
     so re-fetching the same comment is a no-op.
  2. comments.processed marks rows already sent to the scorer, so a comment is
     never paid for (scored) twice.
  3. ideas.fingerprint is a SHA1 of the normalized idea title under a UNIQUE
     constraint, so the same idea phrased with different casing/punctuation is
     stored once.
Every run is also written to the `runs` table as an audit trail.
"""
import hashlib
import os
import re
import sqlite3
from datetime import datetime, timezone

SCHEMA = """
CREATE TABLE IF NOT EXISTS comments(
  comment_id TEXT PRIMARY KEY, video_id TEXT, channel TEXT,
  text TEXT, likes INTEGER, author TEXT, published_at TEXT,
  processed INTEGER DEFAULT 0);
CREATE TABLE IF NOT EXISTS ideas(
  idea_id INTEGER PRIMARY KEY AUTOINCREMENT,
  fingerprint TEXT UNIQUE, title TEXT, source_comment TEXT,
  channel TEXT, score INTEGER, rationale TEXT, category TEXT,
  author TEXT, video_id TEXT,
  created_at TEXT DEFAULT CURRENT_TIMESTAMP,
  delivered INTEGER DEFAULT 0);
CREATE TABLE IF NOT EXISTS videos(
  video_id TEXT PRIMARY KEY, channel TEXT, title TEXT);
CREATE TABLE IF NOT EXISTS runs(
  run_id INTEGER PRIMARY KEY AUTOINCREMENT,
  started_at TEXT, finished_at TEXT, mode TEXT, scorer TEXT,
  comments_seen INTEGER, comments_new INTEGER, comments_scored INTEGER,
  comments_filtered INTEGER, ideas_new INTEGER, ideas_duplicate INTEGER,
  ideas_below_threshold INTEGER);
"""

RUN_STAT_COLUMNS = ["comments_seen", "comments_new", "comments_scored", "comments_filtered",
                    "ideas_new", "ideas_duplicate", "ideas_below_threshold"]


def connect(path="data/comments.db"):
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    db = sqlite3.connect(path)
    db.executescript(SCHEMA)
    return db


def save_video(db, video_id, channel, title):
    db.execute("INSERT OR REPLACE INTO videos(video_id, channel, title) VALUES (?,?,?)",
               (video_id, channel, title))


def save_comment(db, c, channel) -> bool:
    """Insert one comment. Returns True if it was new, False if already stored."""
    cur = db.execute("""INSERT OR IGNORE INTO comments
      (comment_id, video_id, channel, text, likes, author, published_at)
      VALUES (?,?,?,?,?,?,?)""",
      (c["comment_id"], c["video_id"], channel, c["text"],
       c["likes"], c["author"], c["published_at"]))
    return cur.rowcount == 1


def normalize_title(title: str) -> str:
    """Lower-case, drop punctuation, collapse whitespace."""
    norm = re.sub(r"[^a-z0-9 ]", "", (title or "").lower())
    return re.sub(r"\s+", " ", norm).strip()


def fingerprint(title: str) -> str:
    """Stable key so the same idea phrased two ways collapses to one row."""
    return hashlib.sha1(normalize_title(title).encode()).hexdigest()


def unprocessed_comments(db):
    return db.execute(
        "SELECT comment_id, channel, text, likes, author, video_id FROM comments "
        "WHERE processed = 0 ORDER BY channel, comment_id").fetchall()


def mark_processed(db, comment_ids):
    """Mark exactly the comments handled in this run (not a blanket UPDATE)."""
    db.executemany("UPDATE comments SET processed = 1 WHERE comment_id = ?",
                   [(cid,) for cid in comment_ids])


def save_idea(db, idea) -> bool:
    """Returns False if this idea (by fingerprint) was already stored."""
    fp = fingerprint(idea["title"])
    try:
        db.execute("""INSERT INTO ideas
          (fingerprint, title, source_comment, channel, score, rationale, category,
           author, video_id)
          VALUES (?,?,?,?,?,?,?,?,?)""",
          (fp, idea["title"], idea.get("source_comment", ""), idea["channel"],
           idea.get("score", 0), idea.get("rationale", ""), idea.get("category", ""),
           idea.get("author"), idea.get("video_id")))
        return True
    except sqlite3.IntegrityError:
        return False


def _norm(s: str) -> str:
    return re.sub(r"\s+", " ", (s or "").strip()).lower()


def _match_comment(norm_comments, source_comment):
    """Find which comment an idea came from; return (author, video_id)."""
    src = _norm(source_comment)
    if len(src) < 8:
        return (None, None)
    key = src[:35]
    for ntext, author, video_id in norm_comments:
        if key and key in ntext:
            return (author, video_id)
        if len(ntext) >= 20 and ntext[:20] in src:
            return (author, video_id)
    return (None, None)


def backfill_authors(db):
    """Fallback lineage: fill commenter + source video for ideas missing them
    (e.g. when the model echoed the comment text but not its index)."""
    channels = [r[0] for r in db.execute("SELECT DISTINCT channel FROM ideas").fetchall()]
    for ch in channels:
        norm_comments = [(_norm(t), a, v) for t, a, v in db.execute(
            "SELECT text, author, video_id FROM comments WHERE channel = ?", (ch,)).fetchall()]
        rows = db.execute(
            "SELECT idea_id, source_comment FROM ideas "
            "WHERE channel = ? AND (author IS NULL OR author = '' OR video_id IS NULL)",
            (ch,)).fetchall()
        for idea_id, src in rows:
            author, video_id = _match_comment(norm_comments, src)
            if author or video_id:
                db.execute("UPDATE ideas SET author = ?, video_id = ? WHERE idea_id = ?",
                           (author, video_id, idea_id))
    db.commit()


def _now():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def start_run(db, mode: str, scorer: str) -> int:
    cur = db.execute("INSERT INTO runs(started_at, mode, scorer) VALUES (?,?,?)",
                     (_now(), mode, scorer))
    db.commit()
    return cur.lastrowid


def finish_run(db, run_id: int, stats: dict):
    sets = ", ".join(f"{c} = ?" for c in RUN_STAT_COLUMNS)
    db.execute(f"UPDATE runs SET finished_at = ?, {sets} WHERE run_id = ?",
               [_now(), *[stats.get(c, 0) for c in RUN_STAT_COLUMNS], run_id])
    db.commit()
