"""Verdict scoring: pure Python, unit tested. The verdict comes from this formula, never the LLM."""
from .state import Finding

THRESHOLD = 0.4

SIGN = {"supports": 1.0, "contradicts": -1.0, "unclear": 0.0}


def compute_score(findings: list[Finding]) -> float:
    num = 0.0
    den = 0.0
    for f in findings:
        if f["stance"] == "unclear":
            continue
        weight = f["credibility"] * f["confidence"]
        if weight <= 0:
            continue
        num += SIGN[f["stance"]] * weight
        den += weight
    if den == 0:
        return 0.0
    return num / den


def compute_verdict(findings: list[Finding]) -> tuple[str, float]:
    clear = [f for f in findings if f["stance"] != "unclear"]
    score = compute_score(findings)
    if len(clear) < 2:
        return "Unverifiable", score
    if score >= THRESHOLD:
        return "True", score
    if score <= -THRESHOLD:
        return "False", score
    return "Mixed", score


def format_findings_for_llm(findings: list[Finding]) -> str:
    lines = []
    for i, f in enumerate(findings, 1):
        lines.append(
            f"[{i}] {f['title']} ({f['url']}) - credibility {f['credibility']}, "
            f"stance {f['stance']}, confidence {f['confidence']}. Quote: \"{f['quote']}\". {f['critique_note']}"
        )
    return "\n".join(lines) if lines else "No usable findings."


def stance_counts(findings: list[Finding]) -> str:
    counts = {"supports": 0, "contradicts": 0, "unclear": 0}
    for f in findings:
        counts[f["stance"]] += 1
    return f"supports {counts['supports']}, contradicts {counts['contradicts']}, unclear {counts['unclear']}"


def strongest_findings(findings: list[Finding]) -> str:
    best: dict[str, tuple[int, float, Finding]] = {}
    for i, f in enumerate(findings, 1):
        if f["stance"] == "unclear":
            continue
        weight = f["credibility"] * f["confidence"]
        if f["stance"] not in best or weight > best[f["stance"]][1]:
            best[f["stance"]] = (i, weight, f)
    lines = []
    for stance in ("supports", "contradicts"):
        if stance in best:
            i, _, f = best[stance]
            lines.append(
                f"[{i}] {f['title']} ({f['url']}) - stance {stance}, credibility {f['credibility']}, "
                f"confidence {f['confidence']}. Quote: \"{f['quote']}\""
            )
    return "\n".join(lines) if lines else "None."
