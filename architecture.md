# Architecture

All diagrams are Mermaid and reflect the code as built (M1–M6). The LangGraph structure and its retry cycle are in [Section 5](#5-langgraph-structure--cycle-the-core).

## 1. System context (who talks to what)

```mermaid
flowchart LR
    U["User<br/>(browser)"] -->|"paste claim / watch progress"| APP["Fact-Checker web app<br/>(localhost:8000)"]
    APP -->|"verdict + cited sources"| U
    APP -->|"LLM calls (~13/run)"| GROQ["Groq API<br/>openai/gpt-oss-20b"]
    APP -->|"search / fetch pages"| WEB["The internet<br/>(DuckDuckGo backends, websites)"]
```

## 2. Container / deployment view (processes on the laptop)

Everything runs locally; only outbound HTTPS leaves the machine.

```mermaid
flowchart TB
    subgraph L["Laptop (no deployment)"]
        B["Browser tab<br/>static/index.html<br/>vanilla JS"]
        API["Python process<br/>uvicorn + FastAPI (app/main.py)<br/>LangGraph pipeline (app/graph.py)"]
        S["subprocess<br/>mcp_servers/search_server.py<br/>FastMCP + ddgs"]
        F["subprocess<br/>uvx mcp-server-fetch"]
        E["subprocess<br/>mcp_servers/evidence_server.py<br/>FastMCP"]
    end
    B <-->|"HTTP: GET / · POST /check (SSE)"| API
    API <-->|"stdio (MCP protocol)"| S
    API <-->|"stdio (MCP protocol)"| F
    API <-->|"stdio (MCP protocol)"| E
    S -->|"HTTPS"| DDG["DuckDuckGo backends"]
    F -->|"HTTPS"| PAGES["Websites"]
    E -.->|"no network"| E
    API -->|"HTTPS + GROQ_API"| GROQ["Groq cloud"]
```

MCP servers start once at app startup (lifespan in `app/main.py`), not per request.

## 3. Component view (code modules)

```mermaid
flowchart TB
    subgraph UI["static/"]
        HTML["index.html"]
    end
    subgraph APP["app/"]
        MAIN["main.py<br/>FastAPI, SSE mapping, 3-min budget"]
        GRAPH["graph.py<br/>nodes, Send fan-out, retry routing"]
        NODES["nodes.py<br/>extract · search · read · critique · rewrite"]
        VERDICT["verdict.py<br/>pure scoring formula"]
        LLM["llm.py<br/>the ONLY Groq access point"]
        MCP["mcp_client.py<br/>MCPManager (AsyncExitStack)"]
        STATE["state.py<br/>State / Finding / Source"]
        PROMPTS["prompts.py"]
    end
    subgraph MCPs["mcp_servers/"]
        SESS["search_server.py"]
        EVID["evidence_server.py + evidence_core.py"]
    end
    HTML -->|SSE| MAIN
    MAIN --> GRAPH --> NODES
    NODES --> LLM
    NODES --> MCP
    NODES --> PROMPTS
    GRAPH --> VERDICT
    GRAPH --> STATE
    MCP --> SESS
    MCP --> EVID
    LLM -->|"JSON mode + backoff"| GROQ["Groq"]
```

## 4. Layered view

```mermaid
flowchart TB
    subgraph L1["Presentation (no build step)"]
        UIx["index.html + vanilla JS<br/>SSE parser, verdict badges, credibility bars"]
    end
    subgraph L2["API"]
        APX["FastAPI routes, SSE event mapping,<br/>claim-extractor loop (≤3 claims), timeout guard"]
    end
    subgraph L3["Orchestration"]
        GRX["LangGraph: fan-out, reducers, retry cycle"]
        VDX["verdict.py: deterministic scoring"]
    end
    subgraph L4["Agents"]
        NDX["prompt-driven LLM nodes (read, critique, extract, rewrite)"]
    end
    subgraph L5["Tools / determinism"]
        MCX["MCP: search, fetch, evidence<br/>(passage extraction + credibility are pure Python)"]
    end
    subgraph L6["External"]
        EXT["Groq · DuckDuckGo · websites"]
    end
    UIx --> APX --> GRX --> NDX --> MCX --> EXT
    VDX -.->|"verdict never from LLM"| GRX
```

## 5. LangGraph structure & cycle (the core)

Compiled by `build_graph(mcp, client)` in `app/graph.py`. State flows through typed channels; `findings` uses the `operator.add` reducer so parallel branches append.

```mermaid
flowchart TD
    START(("start")) --> EC["extract_claims<br/>passthrough claim"]
    EC --> SE["search<br/>search_agent: query → ≤5 domain-deduped sources<br/>(uses search_query after a retry)"]

    SE -->|"sources ≥ 2"| FAN{{"fan-out<br/>Send per source (max 5)"}}
    SE -->|"sources < 2"| SUM

    FAN -->|"branch per source"| B["branch<br/>read_agent: fetch page → evidence MCP<br/>(passages ≤1200 tok, credibility ±recency/keyword caps)<br/>→ critique_agent: stance+confidence+quote<br/>(independent: sees ONLY claim+passages)<br/>quote check fails → force unclear"]
    B -->|"findings += [finding]<br/>(operator.add)"| SUM

    SUM["summarize<br/>verdict = verdict.py formula (never LLM)<br/>explanation = LLM (3–5 sentences, cites)"]
    SUM --> RT{"route_after_summarize"}
    RT -->|"Unverifiable, or Mixed with <2 credible (≥0.6)<br/>AND retries < 1"| PR["prep_retry<br/>LLM rewrites query<br/>retries += 1"]
    PR -->|"⟲ THE CYCLE (max 1)"| SE
    RT -->|"verdict solid, or retries exhausted"| DONE(("end<br/>verdict · score · explanation · findings"))
```

Runtime lifecycle of one claim run:

```mermaid
stateDiagram-v2
    [*] --> Extracting
    Extracting --> Searching: claim ready
    Searching --> Branching: sources ≥ 2
    Searching --> Summarizing: sources < 2 (skip fan-out)
    Branching --> Summarizing: all branches joined
    Summarizing --> Retrying: thin/conflicting evidence AND retries < 1
    Retrying --> Searching: refined query, old findings kept
    Summarizing --> Done: verdict solid or retries used
    Done --> [*]
```

## 6. Request lifecycle (sequence)

```mermaid
sequenceDiagram
    autonumber
    participant UI as Browser (index.html)
    participant API as FastAPI (main.py)
    participant X as Claim extractor (LLM)
    participant G as LangGraph (graph.py)
    participant M as MCP servers (stdio)
    participant L as Groq API

    UI->>API: POST /check {text}
    API->>X: extract_claims_llm(text)
    X-->>API: ≤3 claims (+notice if capped)
    loop per claim
        API->>G: astream({claim, retries:0})
        G->>M: search(query)
        M-->>G: ≤5 candidate URLs
        par per source (Send)
            G->>M: fetch(url) → evidence.extract_passages → source_credibility → extract_date
            G->>L: read (JSON, ≤600 tok)
            G->>L: critique (JSON, ≤600 tok)
        end
        G->>L: summarize (explanation only)
        G-->>API: SSE: progress / finding per branch
        alt thin evidence and retries < 1
            G->>L: rewrite query (prep_retry)
            Note over G: ⟲ back to search, findings accumulate
        end
        G-->>API: final state
    end
    API-->>UI: SSE result {verdict, score, explanation, retries}
```

## 7. Data flow (DFD-style)

```mermaid
flowchart LR
    T["Pasted text"] -->|P1| EXT["Extract claims"]
    EXT -->|claims ≤3| SE["Search"]
    SE -->|urls+snippets| FE["Fetch pages"]
    FE -->|page text| EP["evidence: extract_passages<br/>(~600-char chunks, keyword-scored)"]
    EP -->|passages ≤1200 tok| RD["Read agent (LLM)"]
    EP --> CD["evidence: extract_date"]
    FE --> CR["evidence: source_credibility(url)<br/>0.3–0.9 rule tiers"]
    CR --> ADJ["adjustments:<br/>+0.05 if <2y old · cap 0.3 if claim terms absent"]
    RD -->|summary| CRQ["Critique agent (LLM)"]
    CRQ -->|stance·conf·quote| QC["quote_in_passages check<br/>(normalized substring / fuzzy ≥0.9)"]
    QC -->|finding| VF["verdict.py:<br/>score = Σ(±cred·conf)/Σ(cred·conf)"]
    VF -->|True ≥0.4 · False ≤−0.4 · else Mixed · <2 clear Unverifiable| SUMX["Summarizer (LLM)"]
    SUMX -->|explanation| OUT["Result + citations"]
```

## 8. Data model (class view)

```mermaid
classDiagram
    class Source {
        +str url
        +str title
        +str snippet
    }
    class Finding {
        +str url
        +str title
        +float credibility
        +str credibility_reason
        +list~str~ passages
        +str stance (supports/contradicts/unclear)
        +float confidence
        +str quote
        +str critique_note
    }
    class State {
        +str claim
        +str search_query
        +list~Source~ sources
        +list~Finding~ findings (operator.add)
        +int retries
        +str verdict (True/False/Mixed/Unverifiable)
        +float score
        +str explanation
    }
    class Critique {
        <<Pydantic>>
        +str stance
        +float confidence 0..1
        +str quote
        +str note
    }
    class ReadSummary {
        <<Pydantic>>
        +str summary
    }
    class ExtractedClaims {
        <<Pydantic>>
        +list~str~ claims ≤3
        +str notice
    }
    class QueryRewrite {
        <<Pydantic>>
        +str query
    }
    State o-- Source : sources
    State o-- Finding : findings (appended per branch)
    State ..> Critique : validated LLM output
    State ..> ReadSummary : validated LLM output
    State ..> ExtractedClaims : validated LLM output
    State ..> QueryRewrite : validated LLM output
```

## 9. Logical data relationships (ER view)

```mermaid
erDiagram
    STATE ||--o{ FINDING : "findings (operator.add)"
    STATE ||--o{ SOURCE : "sources"
    FINDING }o--|| SOURCE : "about (url)"
    FINDING ||--o{ PASSAGE : "evidence ≤1200 tokens"
    SOURCE ||--|| CREDIBILITY : "0.0–1.0 + reason"

    STATE {
        string claim
        string search_query
        int retries
        string verdict
        float score
        string explanation
    }
    SOURCE {
        string url
        string title
        string snippet
    }
    FINDING {
        string stance
        float confidence
        string quote
    }
```

## 10. SSE event protocol (message flow)

```mermaid
flowchart LR
    A["POST /check {text}"] --> B{"text empty?"}
    B -->|yes| E1["error event"]
    B -->|no| C["extract_claims progress"]
    C --> N["notice event (if >3 claims)"]
    N --> D["Claim k/n progress"]
    D --> S["search progress (incl. retry round)"]
    S --> F["per branch: progress + finding event"]
    F --> R["result event: verdict·score·explanation·retries"]
    R -->|next claim| D
    R --> Z["stream ends"]
    S -.->|"timeout >180s / exception"| E2["error event (partial results kept)"]
```

Event shapes (spec Section 11):

| type | payload |
|---|---|
| `progress` | `{node, detail}` |
| `finding` | `{finding: Finding}` |
| `notice` | `{message}` (claim cap) |
| `result` | `{claim, verdict, score, explanation, findings, retries}` |
| `error` | `{message}` |

## 11. Build history (git)

```mermaid
gitGraph
    commit id: "init: spec + AGENTS.md"
    commit id: "setup: deps + smoke tests"
    commit id: "M1: CLI chain"
    commit id: "M2: evidence MCP"
    commit id: "M3: Send fan-out"
    commit id: "M4: verdict + summarizer"
    commit id: "M5: FastAPI + SSE + UI"
    commit id: "M6: retry + multi-claim"
    commit id: "final report"
    commit id: "startup.md"
```

## 12. Reliability architecture (cross-cutting)

| Concern | Mechanism | Where |
|---|---|---|
| Runaway LLM spend | semaphore(2), remaining-tokens pause, 429 retry-after backoff (max 3), per-run usage log | `app/llm.py` |
| Invented evidence | quote-in-passages check → force `unclear`, confidence 0 | `app/nodes.py` + `evidence_core.py` |
| Verdict integrity | formula in plain Python; LLM only writes prose | `app/verdict.py` |
| Dead sources | fetch failure → branch returns `unclear` finding, run never crashes | `app/graph.py`, `app/nodes.py` |
| Bad JSON | 1 stricter-JSON retry, then `unclear` fallback | `app/llm.py` |
| Flaky search | 3-attempt capped retry inside search tool | `mcp_servers/search_server.py` |
| Runaway runtime | 180s budget → error event with partial results | `app/main.py` |
| Missing key | fail fast at startup | `app/main.py` lifespan |
