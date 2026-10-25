"""End-to-end: the full --demo pipeline on the bundled synthetic fixtures."""
import os
from datetime import date

import pytest
import yaml

from comment_intel import pipeline, run_pipeline, store
from comment_intel.demo import FixtureSource, HeuristicScorer, load_fixtures
from conftest import ROOT

AS_OF = date(2026, 1, 31)
SAMPLE = os.path.join(ROOT, "examples", "demo-channel-video-ideas.md")
SAMPLE_SOURCE = "Demo Channel - Bookkeeping Basics - Video Ideas.md"  # the report the demo writes


def _run(cfg, tmp_path, scorer=None):
    return pipeline.run(
        cfg, mode="demo", scorer=scorer or HeuristicScorer(),
        db_path=str(tmp_path / "demo.db"), reports_dir=str(tmp_path / "reports"),
        source=FixtureSource(load_fixtures(pipeline.resolve(cfg, cfg["demo"]["fixtures"]))),
        as_of=AS_OF)


def test_demo_run_end_to_end(cfg, tmp_path):
    result = _run(cfg, tmp_path)
    s = result["stats"]
    assert s["comments_seen"] == 27
    assert s["comments_new"] == 26              # one re-delivered comment ignored
    assert s["comments_scored"] + s["comments_filtered"] == 26
    assert s["comments_filtered"] > 0          # junk never reaches the scorer
    assert s["ideas_duplicate"] == 1           # same question from two viewers
    assert s["ideas_new"] > 5
    files = sorted(os.listdir(tmp_path / "reports"))
    assert "Demo Channel - Bookkeeping Basics - Video Ideas.md" in files
    assert "Demo Channel - Spreadsheet Lab - Comments.md" in files


def test_demo_run_is_idempotent(cfg, tmp_path):
    _run(cfg, tmp_path)
    again = _run(cfg, tmp_path)["stats"]
    assert again["comments_new"] == 0
    assert again["comments_scored"] == 0
    assert again["ideas_new"] == 0
    db = store.connect(str(tmp_path / "demo.db"))
    assert db.execute("SELECT COUNT(*) FROM runs WHERE finished_at IS NOT NULL").fetchone()[0] == 2
    db.close()


def test_demo_output_is_deterministic_and_matches_committed_example(cfg, tmp_path):
    _run(cfg, tmp_path)
    produced = (tmp_path / "reports" / SAMPLE_SOURCE).read_text(encoding="utf-8")
    with open(SAMPLE, encoding="utf-8") as f:
        assert produced == f.read()


class FlakyScorer(HeuristicScorer):
    """Fails on the second batch, like an API outage mid-run."""

    def __init__(self):
        self.calls = 0

    def score(self, channel, comments):
        self.calls += 1
        if self.calls == 2:
            raise RuntimeError("simulated API outage")
        return super().score(channel, comments)


def test_failed_batch_is_retried_not_lost(cfg, tmp_path):
    cfg["llm"]["batch_size"] = 5
    with pytest.raises(RuntimeError):
        _run(cfg, tmp_path, FlakyScorer())
    db = store.connect(str(tmp_path / "demo.db"))
    pending = len(store.unprocessed_comments(db))
    db.close()
    assert pending > 0                          # failed batch kept for next run
    retry = _run(cfg, tmp_path)["stats"]
    assert retry["comments_scored"] + retry["comments_filtered"] == pending
    assert retry["comments_new"] == 0          # nothing re-ingested
    assert retry["ideas_new"] > 0


def test_cli_demo_without_api_key(cfg, tmp_path, capsys):
    conf = dict(cfg)
    conf.pop("_root")
    conf["demo"] = {"fixtures": os.path.join(ROOT, "fixtures", "comments.json"),
                    "db": str(tmp_path / "cli.db"), "reports_dir": str(tmp_path / "out")}
    cfg_path = tmp_path / "config.yaml"
    cfg_path.write_text(yaml.safe_dump(conf), encoding="utf-8")
    rc = run_pipeline.main(["--demo", "--config", str(cfg_path), "--as-of", "2026-01-31",
                            "--briefing"])
    assert rc == 0
    out = capsys.readouterr().out
    assert "offline-heuristic" in out
    assert (tmp_path / "out" / "Video Idea Briefing 2026-01-31.md").exists()


def test_cli_live_mode_refuses_without_keys(capsys):
    assert run_pipeline.main([]) == 2
