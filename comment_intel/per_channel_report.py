"""Report: per-channel Markdown files.

Each channel gets two files, overwritten every run so they always reflect the
current state of the database:
  "<Channel> - Video Ideas.md"   ranked ideas with lineage back to the comment
  "<Channel> - Comments.md"      the raw comment feed, most-liked first
"""
import os
import re
from datetime import date


def _safe(name: str) -> str:
    return re.sub(r'[<>:"/\\|?*]', "", name).strip()


def _quote(text: str) -> str:
    return "\n".join(f"> {line}" if line else ">" for line in (text or "").strip().splitlines())


def _cell(text: str) -> str:
    return (text or "").replace("|", "\\|").replace("\n", " ")


def _video_link(video_id, vtitle) -> str:
    return f"[{vtitle or video_id}](https://www.youtube.com/watch?v={video_id})"


def render_ideas(db, channel: str, as_of: date | None = None) -> str:
    as_of = as_of or date.today()
    ideas = db.execute(
        "SELECT i.title, i.source_comment, i.score, i.rationale, i.category, "
        "       i.author, i.video_id, v.title "
        "FROM ideas i LEFT JOIN videos v ON i.video_id = v.video_id "
        "WHERE i.channel = ? ORDER BY i.score DESC, i.idea_id", (channel,)).fetchall()
    out = [f"# {channel}: Video Ideas", "",
           f"_Updated {as_of.isoformat()} · {len(ideas)} ideas, best first. "
           "Draft for human review; nothing here is published automatically._", ""]
    if not ideas:
        out.append("_No ideas yet._")
        return "\n".join(out) + "\n"
    out += ["| # | Score | Type | Title |", "|---:|---:|---|---|"]
    for i, (title, _src, score, _why, cat, *_lineage) in enumerate(ideas, 1):
        out.append(f"| {i} | {score}/10 | {cat} | {_cell(title)} |")
    out.append("")
    for i, (title, src, score, why, cat, author, video_id, vtitle) in enumerate(ideas, 1):
        out += ["---", "", f"## {i}. {title}", "", f"**Score {score}/10** · {cat}", ""]
        if author:
            out += [f"- **Credit the commenter:** {author}"]
        if video_id:
            out += [f"- **Source video:** {_video_link(video_id, vtitle)}"]
        if author or video_id:
            out.append("")
        if src:
            out += [_quote(src), ""]
        out += [f"**Why it's strong:** {why or ''}", ""]
    return "\n".join(out)


def render_comments(db, channel: str, as_of: date | None = None) -> str:
    as_of = as_of or date.today()
    comments = db.execute(
        "SELECT c.text, c.likes, c.author, c.video_id, v.title "
        "FROM comments c LEFT JOIN videos v ON c.video_id = v.video_id "
        "WHERE c.channel = ? ORDER BY c.likes DESC, length(c.text) DESC, c.comment_id",
        (channel,)).fetchall()
    out = [f"# {channel}: Comment Feed", "",
           f"_Updated {as_of.isoformat()} · {len(comments)} comments, most-liked first. "
           "Skim these to find ideas the scorer missed or ranked low._", ""]
    for text, likes, author, video_id, vtitle in comments:
        head = f"**[{likes} likes] {author}**"
        if video_id:
            head += f" on {_video_link(video_id, vtitle)}"
        out += [head, "", _quote(text), ""]
    return "\n".join(out)


def write_all(db, out_dir: str, as_of: date | None = None):
    os.makedirs(out_dir, exist_ok=True)
    channels = [r[0] for r in db.execute(
        "SELECT DISTINCT channel FROM comments ORDER BY channel").fetchall()]
    paths = []
    for ch in channels:
        ideas_path = os.path.join(out_dir, f"{_safe(ch)} - Video Ideas.md")
        comments_path = os.path.join(out_dir, f"{_safe(ch)} - Comments.md")
        with open(ideas_path, "w", encoding="utf-8", newline="\n") as f:
            f.write(render_ideas(db, ch, as_of))
        with open(comments_path, "w", encoding="utf-8", newline="\n") as f:
            f.write(render_comments(db, ch, as_of))
        paths += [ideas_path, comments_path]
    return paths
