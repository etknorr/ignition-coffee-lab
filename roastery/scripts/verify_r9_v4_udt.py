#!/usr/bin/env python3
"""Round 9 item 6 proof: setup_roastery_v4_tags.py (resynced) vs the
live Maker gateway UDT export. Same member norm as the lab
r7_udt_diff.py; the Sources folder entry inside v4 MEMBERS is excluded
from the scalar comparison exactly as r7 excludes it live. Read only:
it never imports or runs either setup script's main(), which would
delete and rebuild the tags. Exits 0 only on 0 differences.

Run with wsvenv python from ~/workspace/ignition-lab."""
import json, sys, importlib.util, os
sys.path.insert(0, "/home/hatch/workspace/ignition-lab")
sys.path.insert(0, "/home/hatch/workspace/ignition-coffee-lab/roastery/scripts")
from api27m import api
import setup_roastery_v4_tags as v4
spec = importlib.util.spec_from_file_location("r7diff", "/home/hatch/workspace/ignition-lab/r7_udt_diff.py")
r7 = importlib.util.module_from_spec(spec); spec.loader.exec_module(r7)
st, out = api("GET", "/tags/export", params={"provider":"default","type":"json","path":"_types_","recursive":"true","includeUdts":"true"})
assert st == 200, (st, out)
by_name = {t["name"]: t for t in out.get("tags", [])}
live_rb = by_name["RoastBatch"]; live_rs = by_name["RoasterSource"]
live_rb_members = [c for c in live_rb["tags"] if c["name"] != "Sources"]
v4_members = [c for c in v4.MEMBERS if c["name"] != "Sources"]
print(f"v4 scalar members: {len(v4_members)} (live {len(live_rb_members)}), v4 Sources folder present: {any(t['name']=='Sources' for t in v4.MEMBERS)}")
print(f"v4 RoasterSource members: {len(v4.SOURCE_TYPE['tags'])} (live {len(live_rs['tags'])})")
diffs = []
r7.diff_members(v4_members, live_rb_members, "RoastBatch-v4", diffs)
r7.diff_members(v4.SOURCE_TYPE["tags"], live_rs["tags"], "RoasterSource-v4", diffs)
print(f"V4 vs LIVE member diffs: {len(diffs)}")
for d in diffs: print("  -", d)
sys.exit(0 if not diffs else 1)
