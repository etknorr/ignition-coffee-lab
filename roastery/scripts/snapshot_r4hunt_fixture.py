#!/usr/bin/env python3
"""Snapshot fixture batch 9919 from the DB into the shape
verify_roastery_r4hunt_c.py restore_fixture() expects:
{'batch': {batch_number, roast_start, roast_end,
bean_name, drop_temp_f, data}, 'series': [{t, bt, ror,
fan, heat}]}. Written after part A saves the fixture
and before part B deletes it. The file lives in the lab
dir (persistent across VM replacements), with a copy in
/tmp for the fallback path.

Round 8 (HUNT-58): thin wrapper over r4hunt_fixture.
snapshot_fixture(), which part A now also calls right
after the live save, so the snapshot is fresh after every
A run instead of a one-off file that can go stale.
"""
import sys

sys.path.insert(0, '/home/hatch/workspace/ignition-lab')
import r4hunt_fixture as RF


def main():
    RF.snapshot_fixture()


if __name__ == '__main__':
    main()
