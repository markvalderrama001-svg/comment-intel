"""Transform: pre-filter comments, then score them into ranked ideas with Claude.

The scorer is an interface (`score(channel, comments) -> list[dict]`) so the
pipeline can swap the live Claude scorer for the deterministic offline scorer
in `demo.py` without any other change.
"""
import json
import re

SYSTEM = """You are a YouTube content strategist. You read viewer comments and \
extract high-potential video ideas. You are ruthless: most comments are NOT video \
ideas. Only surface an idea when a comment reveals a genuine question, pain point, \
curiosity gap, or repeated theme that could carry a whole video."""

PROMPT = """Here are viewer comments from the channel "{channel}".

For EACH comment that contains a viable video idea, output an object with:
- "comment_index": the [number] of the comment it came from
- "title": a compelling, specific video title (not a topic, an actual title)
- "source_comment": the exact comment text it came from
- "score": 1-10, how strong this idea is (audience demand + specificity + rewatchability)
- "category": one of ["how-to","question","pain-point","curiosity","comparison","story"]
- "rationale": one sentence on WHY this is a strong idea

Skip comments with no real idea. Return ONLY a JSON array (possibly empty).

COMMENTS:
{comments}"""

CATEGORIES = {"how-to", "question", "pain-point", "curiosity", "comparison", "story"}


def is_high_signal(text: str, likes: int, cfg) -> bool:
    """Free pre-filter: drop junk before spending money on the LLM."""
    t = (text or "").strip()
    if likes >= cfg["min_likes"]:      # the crowd upvoted it
        return True
    if "?" in t and len(t) >= 15:      # it's a real question
        return True
    if len(t) >= cfg["min_length"]:    # it's substantive
        return True
    return False


def build_prompt(channel: str, comments) -> str:
    numbered = "\n".join(
        f'[{i}] (likes:{c["likes"]}) {c["text"]}' for i, c in enumerate(comments))
    return PROMPT.format(channel=channel, comments=numbered)


def parse_ideas(text: str) -> list:
    """Extract the JSON array from a model reply. Malformed output -> []."""
    start, end = text.find("["), text.rfind("]") + 1
    if start < 0 or end <= start:
        return []
    try:
        data = json.loads(text[start:end])
    except json.JSONDecodeError:
        return []
    return [d for d in data if isinstance(d, dict)] if isinstance(data, list) else []


def clean_idea(raw: dict, comments) -> dict | None:
    """Validate one idea and attach lineage (author, video) from its source comment."""
    title = re.sub(r"\s+", " ", str(raw.get("title") or "")).strip()
    if not title:
        return None
    try:
        score = max(1, min(10, int(raw.get("score", 0))))
    except (TypeError, ValueError):
        return None
    cat = str(raw.get("category") or "").strip().lower()
    idea = {
        "title": title[:200],
        "score": score,
        "category": cat if cat in CATEGORIES else "curiosity",
        "rationale": str(raw.get("rationale") or "").strip(),
        "source_comment": str(raw.get("source_comment") or "").strip(),
    }
    idx = raw.get("comment_index")
    if isinstance(idx, int) and 0 <= idx < len(comments):
        src = comments[idx]
        idea["comment_id"] = src.get("comment_id")
        idea["author"] = src.get("author")
        idea["video_id"] = src.get("video_id")
        idea["source_comment"] = idea["source_comment"] or src["text"]
    return idea


class ClaudeScorer:
    """Live scorer: one Messages API call per batch of comments."""
    name = "claude"

    def __init__(self, model: str, client=None, max_tokens: int = 2000):
        if client is None:
            import anthropic  # lazy: not needed for demo/tests
            client = anthropic.Anthropic()  # reads ANTHROPIC_API_KEY from the env
        self.client, self.model, self.max_tokens = client, model, max_tokens
        self.name = f"claude:{model}"

    def score(self, channel: str, comments) -> list:
        msg = self.client.messages.create(
            model=self.model, max_tokens=self.max_tokens, system=SYSTEM,
            messages=[{"role": "user", "content": build_prompt(channel, comments)}],
        )
        text = "".join(b.text for b in msg.content if getattr(b, "type", "") == "text")
        return [i for i in (clean_idea(r, comments) for r in parse_ideas(text)) if i]
