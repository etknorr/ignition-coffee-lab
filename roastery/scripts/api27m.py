#!/usr/bin/env python3
"""Helper for the Maker 2027 gateway REST API. Reads apitoken-2027-maker.txt.
Usage: api27m.py METHOD PATH [BODYFILE] -> prints status and body.
Importable: api(method, path, body=None, params=None) -> (status, parsed)."""
import json, sys, urllib.request, urllib.parse

BASE = "http://localhost:8088/data/api/v1"

def _token_file():
    import os
    candidates = [
        os.environ.get("APITOKEN_FILE"),
        os.path.join(os.path.dirname(os.path.abspath(__file__)), "apitoken-2027-maker.txt"),
        "/home/hatch/workspace/ignition-lab/apitoken-2027-maker.txt",
    ]
    for c in candidates:
        if c and os.path.exists(c):
            return c
    raise FileNotFoundError("apitoken-2027-maker.txt not found; set APITOKEN_FILE or place it next to this script")


def _token():
    lines = open(_token_file()).read().splitlines()
    name = lines[0].split(":", 1)[1].strip()
    secret = lines[1].split(":", 1)[1].strip()
    return f"{name}:{secret}"

def api(method, path, body=None, params=None, ctype="application/json"):
    url = BASE + path
    if params:
        url += "?" + urllib.parse.urlencode(params)
    data = None
    headers = {"X-Ignition-API-Token": _token()}
    if body is not None:
        data = body.encode() if isinstance(body, str) else body
        headers["Content-Type"] = ctype
    req = urllib.request.Request(url, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            raw = r.read().decode("utf-8", "replace")
            try:
                return r.status, json.loads(raw)
            except Exception:
                return r.status, raw
    except urllib.error.HTTPError as e:
        raw = e.read().decode("utf-8", "replace")
        try:
            return e.code, json.loads(raw)
        except Exception:
            return e.code, raw

if __name__ == "__main__":
    method, path = sys.argv[1], sys.argv[2]
    body = None
    if len(sys.argv) > 3:
        body = open(sys.argv[3], "rb").read()
    st, out = api(method, path, body=body)
    print("STATUS", st)
    print(json.dumps(out, indent=1)[:3000] if not isinstance(out, str) else out[:3000])
