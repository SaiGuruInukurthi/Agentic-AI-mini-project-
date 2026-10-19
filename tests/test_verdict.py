import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.state import Finding
from app.verdict import compute_score, compute_verdict, format_findings_for_llm


def f(stance: str, credibility: float, confidence: float) -> Finding:
    return {
        "url": f"https://example{credibility}.com",
        "title": f"t{stance}{credibility}{confidence}",
        "credibility": credibility,
        "credibility_reason": "test",
        "passages": ["p"],
        "stance": stance,
        "confidence": confidence,
        "quote": "q",
        "critique_note": "n",
    }


class TestComputeVerdict:
    def test_all_support_gives_true(self):
        findings = [f("supports", 0.9, 0.9), f("supports", 0.8, 0.8), f("supports", 0.7, 0.9)]
        verdict, score = compute_verdict(findings)
        assert verdict == "True"
        assert score == 1.0

    def test_all_contradict_gives_false(self):
        findings = [f("contradicts", 0.9, 0.9), f("contradicts", 0.8, 0.8)]
        verdict, score = compute_verdict(findings)
        assert verdict == "False"
        assert score == -1.0

    def test_split_gives_mixed(self):
        findings = [f("supports", 0.9, 0.9), f("contradicts", 0.9, 0.9)]
        verdict, score = compute_verdict(findings)
        assert verdict == "Mixed"
        assert score == 0.0

    def test_fewer_than_two_clear_gives_unverifiable(self):
        findings = [f("supports", 0.9, 0.9), f("unclear", 0.8, 0.8)]
        assert compute_verdict(findings)[0] == "Unverifiable"

    def test_no_findings_unverifiable(self):
        assert compute_verdict([])[0] == "Unverifiable"

    def test_credibility_weighting_flips_verdict(self):
        weak_support = [f("supports", 0.3, 0.3), f("supports", 0.3, 0.3)]
        strong_contra = [f("contradicts", 0.95, 0.95), f("contradicts", 0.9, 0.9)]
        verdict, score = compute_verdict(weak_support + strong_contra)
        assert verdict == "False"
        assert score < -0.4

    def test_mixed_with_both_sides(self):
        findings = [f("supports", 0.9, 0.9), f("supports", 0.5, 0.5), f("contradicts", 0.9, 0.9)]
        assert compute_verdict(findings)[0] == "Mixed"

    def test_two_clear_but_zero_weight_unclear_leaning(self):
        findings = [f("supports", 0.9, 0.0), f("contradicts", 0.9, 0.0), f("supports", 0.9, 0.9)]
        verdict, score = compute_verdict(findings)
        assert verdict == "True"
        assert score == 1.0

    def test_score_bounded(self):
        findings = [f("supports", 1.0, 1.0), f("contradicts", 0.1, 0.1)]
        score = compute_score(findings)
        assert -1.0 <= score <= 1.0

    def test_unclear_does_not_dilute(self):
        findings = [
            f("contradicts", 0.8, 0.95),
            f("contradicts", 0.5, 0.95),
            f("supports", 0.5, 0.95),
            f("unclear", 0.8, 0.9),
            f("unclear", 0.5, 0.9),
        ]
        verdict, score = compute_verdict(findings)
        assert verdict == "False"
        assert abs(score - (-0.76 / 1.71)) < 1e-9

    def test_unclear_only_gives_zero_score(self):
        findings = [f("unclear", 0.8, 0.9), f("unclear", 0.5, 0.9)]
        verdict, score = compute_verdict(findings)
        assert verdict == "Unverifiable"
        assert score == 0.0


class TestFormat:
    def test_format_lists_findings(self):
        text = format_findings_for_llm([f("supports", 0.8, 0.9)])
        assert "[1]" in text and "supports" in text and "https://example0.8.com" in text

    def test_format_empty(self):
        assert format_findings_for_llm([]) == "No usable findings."
