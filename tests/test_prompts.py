import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.prompts import CRITIQUE_PROMPT, EXTRACT_PROMPT, SUMMARIZER_PROMPT


def test_extract_prompt_has_disputed_figure_rule():
    assert "disputes a figure" in EXTRACT_PROMPT
    assert "not six million" in EXTRACT_PROMPT
    assert "Never reduce a disputed figure" in EXTRACT_PROMPT


def test_critique_prompt_has_figure_mismatch_rule():
    assert 'not "supports"' in CRITIQUE_PROMPT
    assert '"contradicts"' in CRITIQUE_PROMPT


def test_summarizer_prompt_has_counts_strongest_and_unclear_rule():
    assert "{counts}" in SUMMARIZER_PROMPT
    assert "{strongest}" in SUMMARIZER_PROMPT
    assert "strongest source on each side" in SUMMARIZER_PROMPT
    assert "not disagreement" in SUMMARIZER_PROMPT
