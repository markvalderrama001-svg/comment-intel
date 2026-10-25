"""Demo support: bundled synthetic fixtures + a deterministic offline scorer.

`HeuristicScorer` mimics the shape of the Claude scorer's output using simple,
repeatable rules, so the whole pipeline (dedup, thresholds, reports, audit log)
can be exercised with no network and no API key. Same input -> same output.
"""
import json
import re

from .intelligence import clean_idea

REQUEST_PHRASES = ("please make", "can you do", "can you make", "video on", "would love",
                   "tutorial", "explain", "walk through", "walkthrough", "show us",
                   "how do", "how to", "what's the difference", "difference between",
                   " vs ", "struggle", "confused", "nightmare")
PAIN_WORDS = ("struggle", "confused", "nightmare", "mess", "stuck", "keeps breaking", "hate")
HOWTO_WORDS = ("how do", "how to", "tutorial", "walk through", "walkthrough", "show us")
COMPARE_WORDS = (" vs ", "difference between", "what's the difference", "better than")

# Request phrasing is stripped so the title states the topic, not the ask.
LEADS = (("please make a video on ", ""), ("can you make a video on ", ""),
         ("can you do one on ", ""), ("would love a tutorial on ", ""),
         ("would love a video on ", ""), ("show us how to ", "how to "),
         ("how do you ", "how to "), ("how do i ", "how to "), ("explain ", "explained: "))


def make_title(topic: str, category: str) -> str:
    low = topic.lower()
    for lead, repl in LEADS:
        if low.startswith(lead):
            topic = repl + topic[len(lead):]
            break
    if len(topic) > 80:  # cut on a word boundary
        topic = topic[:80].rsplit(" ", 1)[0]
    if category == "pain-point" and not topic.lower().startswith("explained"):
        topic = "Fixing it: " + topic
    topic = topic.strip(" ,;:-")
    return topic[0].upper() + topic[1:]


def load_fixtures(path: str) -> dict:
    with open(path, encoding="utf-8") as f:
        return json.load(f)


class FixtureSource:
    """Stands in for the YouTube client: same comment dict shape, read from JSON."""

    def __init__(self, fixtures: dict):
        self.channels = {c["name"]: c for c in fixtures["channels"]}

    def videos(self, channel_name: str):
        return self.channels.get(channel_name, {}).get("videos", [])

    def comments(self, channel_name: str):
        yield from self.channels.get(channel_name, {}).get("comments", [])


def _first_sentence(text: str) -> str:
    t = re.sub(r"\s+", " ", text).strip()
    q = t.find("?")
    if q != -1:  # the question is usually the idea
        start = max(t.rfind(". ", 0, q), t.rfind("! ", 0, q))
        return t[start + 2 if start != -1 else 0:q].strip()
    m = re.split(r"(?<=[.!])\s", t, maxsplit=1)
    return m[0].rstrip(".!").strip()


def _categorize(t: str, is_question: bool) -> str:
    if any(w in t for w in COMPARE_WORDS):
        return "comparison"
    if any(w in t for w in HOWTO_WORDS):
        return "how-to"
    if any(w in t for w in PAIN_WORDS):
        return "pain-point"
    return "question" if is_question else "curiosity"


class HeuristicScorer:
    """Deterministic stand-in for the LLM scorer (used when no API key is set)."""
    name = "offline-heuristic"

    def score(self, channel: str, comments) -> list:
        ideas = []
        for idx, c in enumerate(comments):
            text = c["text"] or ""
            t = f" {text.lower()} "
            is_q = "?" in text
            request = any(p in t for p in REQUEST_PHRASES)
            if not (is_q or request):
                continue  # not an idea, same as the LLM skipping it
            score = 4 + (2 if request else 0) + (1 if is_q else 0) + min(3, int(c["likes"]) // 10)
            category = _categorize(t, is_q)
            topic = _first_sentence(text).strip(" ,;:-")
            if len(topic) < 8:
                continue
            title = make_title(topic, category)
            signals = [s for s, on in (("question", is_q), ("explicit request", request)) if on]
            ideas.append({
                "comment_index": idx,
                "title": title,
                "source_comment": text,
                "score": min(10, score),
                "category": category,
                "rationale": (f"Offline heuristic: {' + '.join(signals)}, "
                              f"{c['likes']} likes."),
            })
        return [i for i in (clean_idea(r, comments) for r in ideas) if i]
