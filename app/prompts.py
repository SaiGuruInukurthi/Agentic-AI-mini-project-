READ_PROMPT = """Given this claim and these passages, summarize only what the passages say that is relevant. Do not judge truth. If the passages are unrelated, say so.

Claim: {claim}

Passages:
{passages}

Respond with JSON: {{"summary": "3-4 sentence summary of what the passages say about the claim"}}"""

CRITIQUE_PROMPT = """You are an independent fact-checker. Using ONLY the passages, decide if they support, contradict, or are unclear about the claim. If you cannot find a supporting quote, stance must be "unclear". If the passages give a figure different from the claim's figure, that is "contradicts", not "supports".

Claim: {claim}

Passages:
{passages}

Respond with JSON: {{"stance": "supports" or "contradicts" or "unclear", "confidence": 0.0 to 1.0, "quote": "short quote under 25 words copied from the passages", "note": "one sentence reason"}}"""

QUERY_REWRITE_PROMPT = """Rewrite this search query to find fact-checking sources. Rephrase it plainly, add the words "fact check", and keep the key entities.

Original query: {query}

Respond with JSON: {{"query": "the rewritten query"}}"""

SUMMARIZER_PROMPT = """Write a 3 to 5 sentence explanation of the verdict below. Cite sources as [1], [2]. Cite the strongest source on each side. Sources with stance unclear are not disagreement; do not describe them as such. Do not change the verdict.

Claim: {claim}

Verdict: {verdict} (score {score})

Counts: {counts}

Strongest sources:
{strongest}

All findings:
{findings}

Respond with JSON: {{"explanation": "your explanation"}}"""

EXTRACT_PROMPT = """Extract up to 3 separate checkable factual claims from the text below. If the text is already one short claim, return it unchanged as the only claim. Ignore opinions, questions, and commands. If the text questions or disputes a figure, state the claim as the user asserts it, including the disputed figure and what it denies (for example: "Only about 200,000 Jews were killed in the Holocaust, not six million."). Never reduce a disputed figure to a bare number claim that the mainstream figure would imply.

Text: {text}

Respond with JSON: {{"claims": ["claim 1", "claim 2", "claim 3"], "notice": "empty string, or a short note if the text contained more claims than you kept"}}"""
