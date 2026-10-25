"""MCP server: the same pipeline, exposed as tools an assistant can call on demand.

Run:  py mcp_server/server.py          (live, needs YOUTUBE_API_KEY / ANTHROPIC_API_KEY)
      COMMENT_INTEL_DEMO=1 py mcp_server/server.py   (offline, synthetic fixtures)

Tools are read-and-report only: nothing here posts, replies to or edits comments.
"""
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, ".."))

from mcp.server.fastmcp import FastMCP  # noqa: E402

from comment_intel import briefing, pipeline, store  # noqa: E402
from comment_intel import intelligence as intel  # noqa: E402
from comment_intel.run_pipeline import _key_present, _load_env  # noqa: E402

CFG = pipeline.load_config()
_load_env(CFG["_root"])
DEMO = os.environ.get("COMMENT_INTEL_DEMO") == "1"
DB_PATH = pipeline.resolve(CFG, CFG["demo"]["db"] if DEMO else CFG["paths"]["db"])
mcp = FastMCP("comment-intel")


def _scorer():
    if _key_present("ANTHROPIC_API_KEY"):
        return intel.ClaudeScorer(CFG["llm"]["model"])
    if DEMO:
        from comment_intel.demo import HeuristicScorer
        return HeuristicScorer()
    raise RuntimeError("ANTHROPIC_API_KEY is not set.")


@mcp.tool()
def scan_comments(max_videos: int = 20) -> str:
    """Pull fresh comments from all channels and store new ones (duplicates are ignored)."""
    db = store.connect(DB_PATH)
    stats = pipeline.new_stats()
    try:
        if DEMO:
            from comment_intel.demo import FixtureSource, load_fixtures
            src = FixtureSource(load_fixtures(pipeline.resolve(CFG, CFG["demo"]["fixtures"])))
            pipeline.ingest_fixtures(db, src, CFG, stats)
        else:
            from comment_intel import youtube_client as yt
            cfg = {**CFG, "thresholds": {**CFG["thresholds"],
                                         "max_videos_backfill": max_videos,
                                         "max_videos_daily": max_videos}}
            pipeline.ingest_youtube(db, yt.make_client(os.environ["YOUTUBE_API_KEY"]), cfg, stats)
    finally:
        db.close()
    return (f"Scanned {stats['comments_seen']} comments across {len(CFG['channels'])} "
            f"channels; {stats['comments_new']} were new.")


@mcp.tool()
def generate_ideas(min_score: int = 6) -> list:
    """Score unprocessed high-signal comments into video ideas. Returns only new ideas."""
    db = store.connect(DB_PATH)
    try:
        return pipeline.score_unprocessed(db, _scorer(), CFG, min_score=min_score)
    finally:
        db.close()


@mcp.tool()
def get_briefing() -> str:
    """Return the undelivered ideas as a Markdown briefing (does not mark them delivered)."""
    db = store.connect(DB_PATH)
    try:
        return briefing.render(db)
    finally:
        db.close()


@mcp.resource("briefing://latest")
def latest_briefing() -> str:
    """The current briefing, exposed as a readable resource."""
    return get_briefing()


if __name__ == "__main__":
    mcp.run()
