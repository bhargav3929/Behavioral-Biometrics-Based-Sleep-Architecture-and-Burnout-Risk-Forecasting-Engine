#!/usr/bin/env python3
"""Record the real output of each bundled sample into samples/results/<id>.json.

Start the app first (start.bat or start.sh) and make sure a Groq key is set, then run:
    python scripts/record_samples.py [http://127.0.0.1:8010]

Each sample is sent to the live /api/forecast route. The saved file is exactly what the route
returned (minus per-run bookkeeping), so the instant "saved result" buttons match a live run.
The invalid-log control is recorded too: its saved result is the 400 rejection.
"""
import json
import sys
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
BASE = (sys.argv[1] if len(sys.argv) > 1 else "http://127.0.0.1:8010").rstrip("/")


def call(method, path, body=None):
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(BASE + path, data=data, method=method, headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=180) as r:
            return r.status, json.load(r)
    except urllib.error.HTTPError as e:
        return e.code, json.load(e)


def main() -> int:
    status, info = call("GET", "/api/info")
    if status != 200:
        print("The app is not reachable at", BASE)
        return 1
    if info["mode"] != "local" or not info["ai"]["ready"]:
        print("Run the app in local mode with a Groq key set (API Keys button or .env) first.")
        return 1
    out_dir = ROOT / "samples" / "results"
    out_dir.mkdir(parents=True, exist_ok=True)
    bad = 0
    for csv in sorted((ROOT / "samples").glob("*.csv")):
        text = csv.read_text(encoding="utf-8")
        status, body = call("POST", "/api/forecast", {"log_text": text})
        if status == 200:
            for k in ("history_id", "limits"):
                body.pop(k, None)
            print(f"{csv.stem}: score {body['burnout']['score']} ({body['burnout']['label']}) via {body['model']}")
        elif status == 400:
            body = {"http_status": 400, **body}
            print(f"{csv.stem}: rejected with 400 BAD_INPUT, as expected for a control")
        else:
            print(f"{csv.stem}: FAILED {status} {body.get('code')} {body.get('error')}")
            bad += 1
            continue
        (out_dir / f"{csv.stem}.json").write_text(json.dumps(body, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
