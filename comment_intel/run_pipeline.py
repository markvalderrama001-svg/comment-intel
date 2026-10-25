"""CLI entry point.

  py -m comment_intel --demo            offline run on bundled synthetic comments
  py -m comment_intel --demo --reset    same, starting from an empty demo database
  py -m comment_intel                   live run (needs YOUTUBE_API_KEY + ANTHROPIC_API_KEY)

Safe to schedule daily (Windows Task Scheduler / cron): every run is idempotent.
"""
import argparse
import os
from datetime import date

from . import pipeline


def _load_env(root: str):
    try:
        from dotenv import load_dotenv
    except ImportError:
        return
    load_dotenv(os.path.join(root, ".env"))


def _key_present(name: str) -> bool:
    v = os.environ.get(name, "").strip()
    return bool(v) and not v.startswith("your_")


def build_parser():
    p = argparse.ArgumentParser(prog="comment-intel", description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--demo", action="store_true",
                   help="run on fixtures/ instead of the YouTube API")
    p.add_argument("--offline", action="store_true",
                   help="force the deterministic offline scorer even if ANTHROPIC_API_KEY is set")
    p.add_argument("--reset", action="store_true", help="delete the demo database first")
    p.add_argument("--briefing", action="store_true",
                   help="also write a cross-channel briefing of undelivered ideas")
    p.add_argument("--as-of", type=date.fromisoformat, default=None,
                   help="report date (YYYY-MM-DD); defaults to today")
    p.add_argument("--config", default=None, help="path to config.yaml")
    p.add_argument("--out", default=None, help="override the reports folder")
    return p


def main(argv=None) -> int:
    args = build_parser().parse_args(argv)
    cfg = pipeline.load_config(args.config)
    _load_env(cfg["_root"])
    cfg["llm"]["model"] = os.environ.get("COMMENT_INTEL_MODEL", cfg["llm"]["model"])

    if args.offline or not _key_present("ANTHROPIC_API_KEY"):
        if not args.demo:
            print("ANTHROPIC_API_KEY is not set. Live mode needs it; use --demo to run offline.")
            return 2
        from .demo import HeuristicScorer
        scorer = HeuristicScorer()
    else:
        from .intelligence import ClaudeScorer
        scorer = ClaudeScorer(cfg["llm"]["model"])

    if args.demo:
        from .demo import FixtureSource, load_fixtures
        db_path = pipeline.resolve(cfg, cfg["demo"]["db"])
        reports = args.out or pipeline.resolve(cfg, cfg["demo"]["reports_dir"])
        if args.reset and os.path.exists(db_path):
            os.remove(db_path)
        source = FixtureSource(load_fixtures(pipeline.resolve(cfg, cfg["demo"]["fixtures"])))
        result = pipeline.run(cfg, mode="demo", scorer=scorer, db_path=db_path,
                              reports_dir=reports, source=source, as_of=args.as_of,
                              with_briefing=args.briefing)
    else:
        if not _key_present("YOUTUBE_API_KEY"):
            print("YOUTUBE_API_KEY is not set (see .env.example).")
            return 2
        from . import youtube_client as yt
        result = pipeline.run(cfg, mode="live", scorer=scorer,
                              db_path=pipeline.resolve(cfg, cfg["paths"]["db"]),
                              reports_dir=args.out or pipeline.resolve(cfg, cfg["paths"]["reports_dir"]),
                              youtube=yt.make_client(os.environ["YOUTUBE_API_KEY"]),
                              as_of=args.as_of, with_briefing=args.briefing)

    s = result["stats"]
    print(f"Run #{result['run_id']}: {s['comments_scored']} scored, "
          f"{s['comments_filtered']} filtered, {s['ideas_new']} new ideas, "
          f"{s['ideas_duplicate']} duplicates skipped, "
          f"{s['ideas_below_threshold']} below threshold.")
    print("Reports:")
    for p in result["paths"]:
        print(f"  {os.path.relpath(p, cfg['_root'])}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
