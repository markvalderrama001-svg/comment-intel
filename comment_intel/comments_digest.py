"""Report: raw comments digest across all channels, so a human can browse the
source material and spot ideas the scorer ranked low or missed."""
import os
from datetime import date


def render(db, as_of: date | None = None) -> str:
    as_of = as_of or date.today()
    channels = [r[0] for r in db.execute(
        "SELECT DISTINCT channel FROM comments ORDER BY channel").fetchall()]
    body, total = [], 0
    for ch in channels:
        rows = db.execute(
            "SELECT text, likes, author FROM comments WHERE channel = ? "
            "ORDER BY likes DESC, length(text) DESC, comment_id", (ch,)).fetchall()
        body.append(f"\n---\n\n## {ch} ({len(rows)} comments)\n")
        for text, likes, author in rows:
            total += 1
            body.append(f"**[{likes or 0} likes]** {author}")
            body.append(f"> {(text or '').strip()}\n")
    head = [f"# Raw Comments Digest - {as_of.isoformat()}", "",
            f"**{total} comments** captured across {len(channels)} channels, most-liked first.",
            ""]
    return "\n".join(head + body) + "\n"


def write(db, out_dir: str, as_of: date | None = None) -> str:
    as_of = as_of or date.today()
    os.makedirs(out_dir, exist_ok=True)
    path = os.path.join(out_dir, f"Raw Comments Digest {as_of.isoformat()}.md")
    with open(path, "w", encoding="utf-8", newline="\n") as f:
        f.write(render(db, as_of))
    return path
