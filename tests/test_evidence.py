import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pytest

from mcp_servers.evidence_core import (
    extract_date,
    extract_passages,
    is_recent,
    quote_in_passages,
    source_credibility,
)


class TestSourceCredibility:
    def test_gov_domain(self):
        assert source_credibility("https://www.nasa.gov/image-article/great-wall/")["score"] == 0.9

    def test_edu_domain(self):
        assert source_credibility("https://web.mit.edu/")["score"] == 0.9

    def test_trusted_reference(self):
        result = source_credibility("https://en.wikipedia.org/wiki/Boiling_point")
        assert result["score"] == 0.8
        assert "trusted" in result["reason"]

    def test_fact_checker(self):
        assert source_credibility("https://www.snopes.com/fact-check/x/")["score"] == 0.85

    def test_fact_checker_beats_trusted(self):
        assert source_credibility("https://www.politifact.com/article/")["score"] == 0.85

    def test_blog_platform(self):
        assert source_credibility("https://someone.blogspot.com/post")["score"] == 0.3

    def test_social_media(self):
        assert source_credibility("https://www.reddit.com/r/science/")["score"] == 0.3

    def test_unknown_https(self):
        assert source_credibility("https://random-news-example.com/page")["score"] == 0.5

    def test_unknown_no_https(self):
        assert source_credibility("http://random-news-example.com/page")["score"] == 0.4

    def test_invalid_url(self):
        assert source_credibility("not a url")["score"] == 0.0


class TestExtractPassages:
    TEXT = (
        "The boiling point of water depends on pressure. " * 3
        + "At sea level water boils at 100 degrees Celsius. " * 3
        + "Penguins live in the southern hemisphere. " * 5
        + "The boiling point drops at altitude. " * 3
    )

    def test_returns_limited_passages(self):
        out = extract_passages(self.TEXT, "Water boils at 100 degrees Celsius at sea level", max_passages=4)
        assert 0 < len(out) <= 4

    def test_relevant_passages_rank_first(self):
        out = extract_passages(self.TEXT, "Water boils at 100 degrees Celsius at sea level", max_passages=2)
        assert "boiling" in out[0].lower() or "boils" in out[0].lower()

    def test_chunk_size_bounded(self):
        out = extract_passages("word " * 3000, "water", max_passages=4)
        assert all(len(p) <= 700 for p in out)

    def test_empty_text(self):
        assert extract_passages("", "claim") == []

    def test_unrelated_claim_still_returns_chunks(self):
        out = extract_passages(self.TEXT, "quantum entanglement in superconductors")
        assert len(out) >= 1


class TestExtractDate:
    def test_iso(self):
        assert extract_date("published 2024-06-15 in the archive") == "2024-06-15"

    def test_us_format(self):
        assert extract_date("Posted on June 15, 2024 by admin") == "2024-06-15"

    def test_eu_format(self):
        assert extract_date("15 June 2024") == "2024-06-15"

    def test_slash_format(self):
        assert extract_date("updated 15/06/2024 today") == "2024-06-15"

    def test_meta_tag(self):
        html = '<meta property="article:published_time" content="2023-02-01T10:00:00Z">'
        assert extract_date(html) == "2023-02-01"

    def test_none(self):
        assert extract_date("no dates here at all") is None


class TestIsRecent:
    def test_recent(self):
        assert is_recent("2025-06-01")

    def test_old(self):
        assert not is_recent("2001-01-01")

    def test_invalid(self):
        assert not is_recent("garbage")
        assert not is_recent(None)


class TestQuoteInPassages:
    P = ["The Great Wall is visible from the lower part of low Earth orbit, but only under very favorable conditions."]

    def test_exact_substring(self):
        assert quote_in_passages("visible from the lower part of low Earth orbit", self.P)

    def test_case_and_whitespace_normalized(self):
        assert quote_in_passages("VISIBLE   from the LOWER part of low earth orbit", self.P)

    def test_invented_quote_rejected(self):
        assert not quote_in_passages("The wall is clearly visible from the Moon", self.P)

    def test_fuzzy_accepts_small_edits(self):
        assert quote_in_passages("visible from the lower part of low Earth orbit, but only under very favorable", self.P)

    def test_short_quote_rejected(self):
        assert not quote_in_passages("wall", self.P)

    def test_empty(self):
        assert not quote_in_passages("", self.P)
        assert not quote_in_passages("some quote long enough", [])


def test_trim_passages_caps_budget():
    from app.nodes import MAX_PASSAGES_CHARS, _trim_passages

    out = _trim_passages(["x" * 3000, "y" * 3000, "z" * 3000])
    assert sum(len(p) for p in out) <= MAX_PASSAGES_CHARS + 3000
    assert len(out) == 2
