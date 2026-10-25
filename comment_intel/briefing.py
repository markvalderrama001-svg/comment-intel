"""Report: cross-channel briefing of ideas not yet delivered.

`write` marks the rendered ideas as delivered, so each idea appears in exactly
one briefing (an exactly-once hand-off, like posting a batch only once).
"""
import os
from datetime import date


def _pending(db):
    return db.execute("""SELECT idea_id, title, source_comment, channel, score, rationale,
                                category, author
                         FROM ideas WHERE delivered = 0
                         ORDER BY score DESC, idea_id""").fetchall()


def render(db, as_of: date | None = None, rows=None) -> str:
    as_of = as_of or date.today()
    rows = _pending(db) if rows is None else rows
    if not rows:
        return f"# Video Idea Briefing - {as_of.isoformat()}\n\n_No new ideas today._\n"
    out = [f"# Video Idea Briefing - {as_of.isoformat()}", "",
           f"**{len(rows)} new ideas** mined from your comment sections.", "", "---"]
    for i, (_id, title, src, channel, score, why, cat, author) in enumerate(rows, 1):
        out += [
            "", f"## {i}. {title}",
            f"**Score:** {score}/10 | **Channel:** {channel} | **Type:** {cat}"
            + (f" | **From:** {author}" if author else ""),
            "", f"> {(src or '').strip()}",
            "", f"**Why it's strong:** {why}", "", "---",
        ]
    return "\n".join(out) + "\n"


def write(db, out_dir: str, as_of: date | None = None) -> str:
    as_of = as_of or date.today()
    os.makedirs(out_dir, exist_ok=True)
    rows = _pending(db)
    path = os.path.join(out_dir, f"Video Idea Briefing {as_of.isoformat()}.md")
    with open(path, "w", encoding="utf-8", newline="\n") as f:
        f.write(render(db, as_of, rows))
    # Only flag the exact rows that were written, never ones that arrived mid-render.
    db.executemany("UPDATE ideas SET delivered = 1 WHERE idea_id = ?", [(r[0],) for r in rows])
    db.commit()
    return path
