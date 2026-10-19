import json
import re
from datetime import date
from pathlib import Path
from urllib.parse import urlparse

DATA_DIR = Path(__file__).resolve().parent.parent

BLOG_PLATFORMS = {
    "blogspot.com", "wordpress.com", "medium.com", "tumblr.com", "substack.com",
    "blogger.com", "livejournal.com", "wixsite.com", "weebly.com",
}
FORUM_SOCIAL = {
    "reddit.com", "quora.com", "facebook.com", "twitter.com", "x.com",
    "instagram.com", "tiktok.com", "youtube.com", "linkedin.com", "pinterest.com",
    "forums.whirlpool.net.au", "stackexchange.com", "stackoverflow.com", "discord.com",
}

STOPWORDS = {
    "the", "a", "an", "is", "are", "was", "were", "be", "been", "being", "of", "in",
    "on", "at", "to", "for", "from", "with", "and", "or", "but", "not", "it", "its",
    "this", "that", "these", "those", "by", "as", "can", "could", "does", "do", "did",
    "has", "have", "had", "will", "would", "should", "than", "then", "there", "their",
}


def _load_json_list(name: str) -> set[str]:
    try:
        data = json.loads((DATA_DIR / name).read_text(encoding="utf-8"))
        return {d.lower() for d in data}
    except FileNotFoundError:
        return set()


def load_trusted() -> set[str]:
    return _load_json_list("trusted_domains.json")


def load_fact_checkers() -> set[str]:
    return _load_json_list("fact_checkers.json")


def _domain_of(url: str) -> str:
    host = urlparse(url).netloc.removeprefix("www.").lower()
    return host


def _matches(host: str, listed: set[str]) -> bool:
    return any(host == d or host.endswith("." + d) for d in listed)


def source_credibility(url: str) -> dict:
    host = _domain_of(url)
    if not host:
        return {"score": 0.0, "reason": "invalid or missing URL"}

    if _matches(host, load_fact_checkers()):
        return {"score": 0.85, "reason": "known fact-checking site"}
    if host.split(".")[-1] in {"gov", "mil"} or host.endswith(".gov.in") or host.endswith(".ac.in"):
        return {"score": 0.9, "reason": "government or academic domain"}
    if host.split(".")[-1] == "edu":
        return {"score": 0.9, "reason": "academic domain"}
    if _matches(host, load_trusted()):
        return {"score": 0.8, "reason": "trusted reference outlet"}

    blog_or_social = _matches(host, BLOG_PLATFORMS) or _matches(host, FORUM_SOCIAL)
    if blog_or_social:
        return {"score": 0.3, "reason": "blog, forum, or social media platform"}

    if url.lower().startswith("https://"):
        return {"score": 0.5, "reason": "unknown domain with HTTPS"}
    return {"score": 0.4, "reason": "unknown domain without HTTPS"}


def claim_keywords(claim: str) -> list[str]:
    words = re.findall(r"[a-z0-9']+", claim.lower())
    return [w for w in words if w not in STOPWORDS and len(w) > 1]


def _split_chunks(text: str, size: int = 600) -> list[str]:
    text = re.sub(r"\s+", " ", text).strip()
    if not text:
        return []
    sentences = re.split(r"(?<=[.!?])\s+", text)
    chunks, current = [], ""
    for s in sentences:
        while len(s) > size:
            if current:
                chunks.append(current.strip())
                current = ""
            chunks.append(s[:size].strip())
            s = s[size:]
        if len(current) + len(s) + 1 > size and current:
            chunks.append(current.strip())
            current = s
        else:
            current = f"{current} {s}".strip()
    if current:
        chunks.append(current.strip())
    return chunks


def _clean_page_text(text: str) -> str:
    # ponytail: line heuristics only; a real DOM parser if junk ever matters more than cost
    text = re.sub(r"<error>.*?</error>", " ", text, flags=re.DOTALL)
    text = re.sub(r"<error>.*\Z", " ", text, flags=re.DOTALL)
    kept = []
    for line in text.splitlines():
        s = line.strip()
        if not s:
            continue
        if s.count("http") >= 3:
            continue
        kept.append(s)
    return "\n".join(kept)


def extract_passages(text: str, claim: str, max_passages: int = 4) -> list[str]:
    chunks = _split_chunks(_clean_page_text(text))
    if not chunks:
        return []
    keywords = claim_keywords(claim)
    keyword_set = set(keywords)

    def score(chunk: str) -> float:
        words = re.findall(r"[a-z0-9']+", chunk.lower())
        if not words:
            return 0.0
        from collections import Counter

        counts = Counter(words)
        hits = sum(counts.get(k, 0) for k in keyword_set)
        coverage = len({k for k in keyword_set if counts.get(k, 0) > 0}) / max(len(keyword_set), 1)
        return hits + 2.0 * coverage

    ranked = sorted(chunks, key=score, reverse=True)
    top = [c for c in ranked if score(c) > 0][:max_passages]
    return top if top else ranked[:max_passages]


def extract_date(text: str) -> str | None:
    # Trust only explicit publish-time markers. Body dates (historical figures,
    # cited years) and site-clock widgets caused false recency bonuses.
    for pattern in (
        r'<meta[^>]+(?:property|name)=["\'](?:article:published_time|og:published_time|date|dc:date)["\'][^>]+content=["\'](\d{4}-\d{2}-\d{2})',
        r'<time[^>]+datetime=["\'](\d{4}-\d{2}-\d{2})',
    ):
        m = re.search(pattern, text, re.IGNORECASE)
        if m:
            return m.group(1)
    return None


def is_recent(iso_date: str | None, within_years: int = 2) -> bool:
    if not iso_date:
        return False
    try:
        y, mo, d = map(int, iso_date.split("-"))
        published = date(y, mo, d)
    except ValueError:
        return False
    today = date.today()
    years_old = (today - published).days / 365.25
    return 0 <= years_old <= within_years


def _normalize_ws(s: str) -> str:
    return re.sub(r"\s+", " ", s).strip().lower()


def quote_in_passages(quote: str, passages: list[str], fuzzy_threshold: float = 0.9) -> bool:
    from difflib import SequenceMatcher

    if not quote or not passages:
        return False
    q = _normalize_ws(quote)
    if len(q) < 10:
        return False
    for p in passages:
        norm = _normalize_ws(p)
        if q in norm:
            return True
        best = max(
            (SequenceMatcher(None, q, norm[i:i + len(q)]).ratio() for i in range(0, max(len(norm) - len(q), 0) + 1, 50)),
            default=0.0,
        )
        if best >= fuzzy_threshold:
            return True
    return False
