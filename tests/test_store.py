from comment_intel import store
from conftest import make_comment


def test_fingerprint_collapses_case_punctuation_and_spacing():
    a = store.fingerprint("How to Reconcile a Credit Card?")
    b = store.fingerprint("how to   reconcile a credit card!!")
    assert a == b
    assert len(a) == 40  # SHA1 hex


def test_fingerprint_distinguishes_different_ideas():
    assert store.fingerprint("How to reconcile a credit card") != \
        store.fingerprint("How to reconcile a bank account")


def test_save_comment_is_idempotent(db):
    c = make_comment("synthetic-c-1", "How do I close the books?")
    assert store.save_comment(db, c, "Demo Channel") is True
    assert store.save_comment(db, c, "Demo Channel") is False
    assert db.execute("SELECT COUNT(*) FROM comments").fetchone()[0] == 1


def test_save_comment_does_not_overwrite_processed_flag(db):
    c = make_comment("synthetic-c-1", "How do I close the books?")
    store.save_comment(db, c, "Demo Channel")
    store.mark_processed(db, ["synthetic-c-1"])
    store.save_comment(db, c, "Demo Channel")  # re-fetched on a later run
    assert db.execute("SELECT processed FROM comments").fetchone()[0] == 1


def test_save_idea_rejects_duplicate_fingerprint(db):
    idea = {"title": "How to reconcile a credit card", "channel": "Demo Channel", "score": 8}
    assert store.save_idea(db, idea) is True
    assert store.save_idea(db, {**idea, "title": "HOW TO RECONCILE A CREDIT CARD?"}) is False
    assert db.execute("SELECT COUNT(*) FROM ideas").fetchone()[0] == 1


def test_mark_processed_only_touches_given_ids(db):
    for i in range(3):
        store.save_comment(db, make_comment(f"synthetic-c-{i}", "text"), "Demo Channel")
    store.mark_processed(db, ["synthetic-c-0", "synthetic-c-2"])
    left = [r[0] for r in store.unprocessed_comments(db)]
    assert left == ["synthetic-c-1"]


def test_backfill_authors_matches_on_comment_text(db):
    store.save_comment(db, make_comment("synthetic-c-9", "Please explain deferred revenue for annual plans",
                                        author="@AlexRivera", video="synthetic-vid-07"), "Demo Channel")
    store.save_idea(db, {"title": "Deferred revenue explained", "channel": "Demo Channel",
                         "source_comment": "Please explain deferred revenue for annual plans"})
    store.backfill_authors(db)
    assert db.execute("SELECT author, video_id FROM ideas").fetchone() == \
        ("@AlexRivera", "synthetic-vid-07")


def test_run_audit_row(db):
    run_id = store.start_run(db, "demo", "offline-heuristic")
    store.finish_run(db, run_id, {"comments_seen": 5, "ideas_new": 2})
    row = db.execute("SELECT mode, scorer, comments_seen, ideas_new, finished_at "
                     "FROM runs WHERE run_id = ?", (run_id,)).fetchone()
    assert row[:4] == ("demo", "offline-heuristic", 5, 2)
    assert row[4] is not None
