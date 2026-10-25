"""Orchestration: extract -> load -> filter -> score -> report, with an audit row per run.

Each scoring batch is committed atomically together with the `processed` flags
for exactly the comments in that batch. If the LLM call fails halfway through
a run, the finished batches stay committed and the rest are simply picked up
on the next run: nothing is lost and nothing is scored twice.
"""
import os
from collections import OrderedDict
from datetime import date

import yaml

from . import briefing, comments_digest, per_channel_report, store
from . import intelligence as intel

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def load_config(path: str | None = None) -> dict:
    path = path or os.path.join(ROOT, "config.yaml")
    with open(path, encoding="utf-8") as f:
        cfg = yaml.safe_load(f)
    cfg["_root"] = os.path.dirname(os.path.abspath(path))
    cfg["llm"]["model"] = os.environ.get("COMMENT_INTEL_MODEL", cfg["llm"]["model"])
    return cfg


def resolve(cfg: dict, rel: str) -> str:
    return rel if os.path.isabs(rel) else os.path.join(cfg["_root"], rel)


def new_stats() -> dict:
    return {c: 0 for c in store.RUN_STAT_COLUMNS}


# ---------------------------------------------------------------- extract + load

def ingest_youtube(db, yc, cfg, stats):
    """Pull comments for every configured channel via the YouTube Data API."""
    from . import youtube_client as yt
    already = db.execute("SELECT COUNT(*) FROM comments").fetchone()[0]
    th = cfg["thresholds"]
    max_videos = th["max_videos_backfill"] if already == 0 else th.get("max_videos_daily", 15)
    print(f"{'Backfilling archive' if already == 0 else 'Checking recent videos'} "
          f"(up to {max_videos} videos per channel)...")
    for ch in cfg["channels"]:
        pl = yt.get_upload_playlist(yc, ch["channel_id"])
        for vid in yt.list_video_ids(yc, pl, max_videos):
            for c in yt.fetch_comments(yc, vid):
                stats["comments_seen"] += 1
                stats["comments_new"] += store.save_comment(db, c, ch["name"])
    db.commit()
    # Titles for any videos we don't know yet, so reports can link the source video.
    missing = [r[0] for r in db.execute(
        "SELECT DISTINCT c.video_id FROM comments c "
        "LEFT JOIN videos v ON c.video_id = v.video_id WHERE v.video_id IS NULL").fetchall()]
    for vid, title in yt.fetch_video_titles(yc, missing).items():
        row = db.execute("SELECT channel FROM comments WHERE video_id = ? LIMIT 1",
                         (vid,)).fetchone()
        store.save_video(db, vid, row[0] if row else None, title)
    db.commit()


def ingest_fixtures(db, source, cfg, stats):
    """Demo extract: same load path as live mode, reading synthetic JSON instead."""
    for name in source.channels:
        for v in source.videos(name):
            store.save_video(db, v["video_id"], name, v["title"])
        for c in source.comments(name):
            stats["comments_seen"] += 1
            stats["comments_new"] += store.save_comment(db, c, name)
    db.commit()


# ---------------------------------------------------------------- transform

def score_unprocessed(db, scorer, cfg, stats=None, min_score=None) -> list:
    """Pre-filter and score every unprocessed comment. Returns the newly stored ideas."""
    stats = stats if stats is not None else new_stats()
    min_score = cfg["llm"]["min_score"] if min_score is None else min_score
    batch_size = cfg["llm"]["batch_size"]

    by_channel = OrderedDict()
    for cid, channel, text, likes, author, video_id in store.unprocessed_comments(db):
        by_channel.setdefault(channel, []).append(
            {"comment_id": cid, "text": text, "likes": likes,
             "author": author, "video_id": video_id})

    fresh = []
    for channel, rows in by_channel.items():
        keep = [r for r in rows if intel.is_high_signal(r["text"], r["likes"], cfg["thresholds"])]
        keep_ids = {r["comment_id"] for r in keep}
        dropped = [r["comment_id"] for r in rows if r["comment_id"] not in keep_ids]
        stats["comments_filtered"] += len(dropped)
        store.mark_processed(db, dropped)  # evaluated (and rejected) for free
        db.commit()
        print(f"  {channel}: {len(rows)} new, {len(keep)} high-signal, "
              f"{len(dropped)} filtered out")

        for i in range(0, len(keep), batch_size):
            chunk = keep[i:i + batch_size]
            ideas = scorer.score(channel, chunk)  # raises -> batch stays unprocessed
            for idea in ideas:
                if idea["score"] < min_score:
                    stats["ideas_below_threshold"] += 1
                    continue
                idea["channel"] = channel
                if store.save_idea(db, idea):
                    stats["ideas_new"] += 1
                    fresh.append(idea)
                else:
                    stats["ideas_duplicate"] += 1
            store.mark_processed(db, [c["comment_id"] for c in chunk])
            stats["comments_scored"] += len(chunk)
            db.commit()  # ideas + processed flags land together
    store.backfill_authors(db)
    return fresh


# ---------------------------------------------------------------- full run

def run(cfg, *, mode: str, scorer, db_path: str, reports_dir: str,
        youtube=None, source=None, as_of: date | None = None, with_briefing=False) -> dict:
    db = store.connect(db_path)
    try:
        run_id = store.start_run(db, mode, scorer.name)
        stats = new_stats()
        if source is not None:
            ingest_fixtures(db, source, cfg, stats)
        else:
            ingest_youtube(db, youtube, cfg, stats)
        print(f"Loaded {stats['comments_seen']} comments "
              f"({stats['comments_new']} new, {stats['comments_seen'] - stats['comments_new']} "
              "already stored). Scoring with", scorer.name)
        score_unprocessed(db, scorer, cfg, stats)
        paths = per_channel_report.write_all(db, reports_dir, as_of)
        paths.append(comments_digest.write(db, reports_dir, as_of))
        if with_briefing:
            paths.append(briefing.write(db, reports_dir, as_of))
        store.finish_run(db, run_id, stats)
        return {"run_id": run_id, "stats": stats, "paths": paths}
    finally:
        db.close()
