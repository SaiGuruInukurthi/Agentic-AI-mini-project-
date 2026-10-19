"""Live SSE probe: POST a claim to /check and print the event stream."""
import json
import sys

import httpx

CLAIM = "The Great Wall of China is visible from space"

with httpx.Client(timeout=240) as client:
    page = client.get("http://127.0.0.1:8000/")
    print(f"GET / -> {page.status_code}, has UI: {'Fact-Checker' in page.text}")

    with client.stream("POST", "http://127.0.0.1:8000/check", json={"text": CLAIM}) as resp:
        print(f"POST /check -> {resp.status_code}")
        counts = {"progress": 0, "finding": 0, "result": 0, "error": 0}
        for line in resp.iter_lines():
            if not line.startswith("data: "):
                continue
            ev = json.loads(line[6:])
            counts[ev["type"]] = counts.get(ev["type"], 0) + 1
            if ev["type"] == "progress":
                print("progress:", ev["detail"])
            elif ev["type"] == "finding":
                f = ev["finding"]
                print(f"finding: {f['url']} | cred {f['credibility']} | {f['stance']} ({f['confidence']})")
            elif ev["type"] == "result":
                print(f"RESULT: {ev['verdict']} (score {ev['score']}, retries {ev.get('retries', 0)})")
                print("explanation:", ev["explanation"][:300])
            elif ev["type"] == "error":
                print("ERROR:", ev["message"])
        print("event counts:", counts)
        sys.exit(0 if counts.get("result") else 1)
