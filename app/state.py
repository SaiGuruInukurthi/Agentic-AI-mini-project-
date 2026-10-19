from typing import Annotated, Literal, TypedDict
import operator


class Source(TypedDict):
    url: str
    title: str
    snippet: str


class Finding(TypedDict):
    url: str
    title: str
    credibility: float
    credibility_reason: str
    passages: list[str]
    stance: Literal["supports", "contradicts", "unclear"]
    confidence: float
    quote: str
    critique_note: str


class State(TypedDict):
    claim: str
    search_query: str
    sources: list[Source]
    findings: Annotated[list[Finding], operator.add]
    retries: int
    verdict: Literal["True", "False", "Mixed", "Unverifiable"]
    score: float
    explanation: str
