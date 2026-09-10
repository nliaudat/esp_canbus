#!/usr/bin/env python3
"""Offline replay of a TopTronic candump against the component's parser.

Issue #41 ("Some sensors have wrong value 0 most of the time") can only be
diagnosed from raw bus traffic: the candump log shows the frames, but not the
decisions the firmware takes on them. This tool feeds the raw CAN frames of a
candump log (see docs/candump.md) through a faithful reimplementation of
``TopTronic::parse_frame()`` / ``TopTronic::interpret_message_()``
(esphome/components/toptronic/toptronic.cpp) and reports, per datapoint:

  * every response the parser decoded (name, raw bytes, value),
  * every response it dropped (truncated value / bad CRC / unknown key),
  * every multi-frame message that was *started but never completed* -- the
    signature of issue #41: a sensor whose value only ever arrives inside an
    extended (0x56) multi-frame response keeps its stale/zero value until a
    plain single-frame (0x42) response for the same datapoint shows up.

It also cross-checks each uncompleted start frame against the continuation
frames actually present in the capture (exact header, header +/- 1), which
distinguishes "continuation lost/never sent" from "continuation carries a
different header than the parser expects".

Usage:
    python tests/replay_candump.py <candump.log> [--hubs WEZ:1,HV:8,BM:8]
                                   [--language de] [--timeline]

The candump format is the one produced by the "candump debug" switch, e.g.
    [12:00:00.000][I][candump:026]: 0x1FD047FF : 01 42 32 00 9E EE 1E
"""

import argparse
import os
import re
import sys

try:
    import yaml
except ImportError:  # pragma: no cover - PyYAML ships with ESPHome
    print("PyYAML is required (pip install pyyaml)", file=sys.stderr)
    raise SystemExit(2)

# ---------------------------------------------------------------------------
# Protocol constants (mirror toptronic.cpp)
# ---------------------------------------------------------------------------
START_OF_MESSAGE_ID = 0x1F
RESPONSE = 0x42
RESPONSE_EXT = 0x56
GET_REQ = 0x40
SET_REQ = 0x46
TOP_TRONIC_COMMANDS = (GET_REQ, SET_REQ, RESPONSE, RESPONSE_EXT)

MIN_MESSAGE_LEN = 5
MAX_FRAMES_PER_MESSAGE = 8

# TypeName -> (byte width, signed)
TYPE_WIDTH = {
    "U8": (1, False),
    "U16": (2, False),
    "U32": (4, False),
    "S8": (1, True),
    "S16": (2, True),
    "S32": (4, True),
    "S64": (8, True),
}

PRESETS_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "esphome", "components", "toptronic", "presets",
)

FRAME_RE = re.compile(r"candump:\d+\]:\s*(0x[0-9A-Fa-f]+)\s*:\s*([0-9A-Fa-f ]+?)\s*$")


# ---------------------------------------------------------------------------
# CRC-16 (exact mirror of compute_crc16() in toptronic.cpp)
# ---------------------------------------------------------------------------
def reflect(val, width):
    out = 0
    for _ in range(width):
        out = (out << 1) | (val & 1)
        val >>= 1
    return out


def compute_crc16(data):
    crc = 0xB006
    for byte in data:
        byte = reflect(byte, 8)
        for b in range(7, -1, -1):
            bit = (byte >> b) & 1
            top = (crc >> 15) & 1
            crc = ((crc << 1) ^ (0x1021 if top ^ bit else 0)) & 0xFFFF
    return reflect(crc, 16)


# ---------------------------------------------------------------------------
# Preset loading: (preset_dir, fg, fn, dp) -> (name, type, multiply)
# ---------------------------------------------------------------------------
def _as_list(value):
    if value is None:
        return []
    return value if isinstance(value, list) else [value]


def _multiply_of(entry):
    for filt in _as_list(entry.get("filters")):
        if isinstance(filt, dict) and "multiply" in filt:
            try:
                return float(filt["multiply"])
            except (TypeError, ValueError):
                return 1.0
    return 1.0


def load_presets(language):
    """Return {preset_dir: {(fg, fn, dp): (name, type, multiply)}}."""
    table = {}
    if not os.path.isdir(PRESETS_DIR):
        return table
    for preset_dir in sorted(os.listdir(PRESETS_DIR)):
        entities = {}
        dir_path = os.path.join(PRESETS_DIR, preset_dir)
        if not os.path.isdir(dir_path):
            continue
        for filename in ("sensors_%s.yaml" % language, "inputs_%s.yaml" % language):
            path = os.path.join(dir_path, filename)
            if not os.path.isfile(path):
                continue
            with open(path, "r", encoding="utf-8") as handle:
                doc = yaml.safe_load(handle) or {}
            for value in doc.values():
                for entry in _as_list(value):
                    if not isinstance(entry, dict) or "datapoint" not in entry:
                        continue
                    key = (
                        int(entry["function_group"]),
                        int(entry["function_number"]),
                        int(entry["datapoint"]),
                    )
                    # setdefault: a datapoint may appear both as a read sensor
                    # (sensors_*.yaml) and as a writable number (inputs_*.yaml);
                    # the read sensor's decoding (type + multiply) wins.
                    entities.setdefault(key, (
                        entry.get("name", "?"),
                        entry.get("type", ""),
                        _multiply_of(entry),
                    ))
        if entities:
            table[preset_dir] = entities
    return table


# ---------------------------------------------------------------------------
# Parser mirror
# ---------------------------------------------------------------------------
class Replayer:
    """Mirrors TopTronic::parse_frame() + interpret_message_()."""

    def __init__(self, hubs, presets):
        self.hubs = hubs                 # {device_id: preset_dir}
        self.presets = presets
        self.pending = {}                # (device_id << 8) | header -> state
        self.continuation_headers = set()  # (device_id, first payload byte)
        self.dispatches = []             # (ts, key, name, type, raw, value, single)
        self.drops = []                  # (ts, reason, detail)
        self.uncompleted = {}            # work_key -> report dict

    def hub_of(self, device_id):
        return self.hubs.get(device_id)

    # --- interpret_message_() ------------------------------------------------
    def interpret(self, data, can_id, ts, single):
        if len(data) < MIN_MESSAGE_LEN:
            self.drops.append((ts, "too_short", "%d bytes" % len(data)))
            return
        if data[0] in (GET_REQ, SET_REQ):
            return  # echoed GET/SET frames never publish
        if data[0] not in (RESPONSE, RESPONSE_EXT):
            self.drops.append((ts, "unknown_cmd", "cmd=0x%02X" % data[0]))
            return
        value_off = 7 if data[0] == RESPONSE_EXT else 5
        if len(data) < value_off:
            self.drops.append((ts, "no_value", "len=%d" % len(data)))
            return

        device_id = (can_id >> 11) & 0x7FF
        preset_dir = self.hub_of(device_id)
        fg, fn = data[1], data[2]
        datapoint = data[4] + (data[3] << 8)
        key = (fg, fn, datapoint)

        entry = self.presets.get(preset_dir, {}).get(key) if preset_dir else None
        if entry is None:
            self.drops.append(
                (ts, "no_sensor", "node=0x%03X fg=%d fn=%d dp=%d cmd=0x%02X"
                 % (device_id, fg, fn, datapoint, data[0])))
            return

        name, type_name, multiply = entry
        width, signed = TYPE_WIDTH.get(type_name, (1, False))
        value_len = len(data) - value_off
        if value_len < width:
            self.drops.append(
                (ts, "truncated", "%s (%d of %d value bytes)"
                 % (name, value_len, width)))
            return

        raw = int.from_bytes(data[value_off:value_off + width], "big", signed=signed)
        self.dispatches.append((ts, key, name, type_name, raw, raw * multiply, single))

    # --- parse_frame() -------------------------------------------------------
    def feed(self, can_id, data, ts):
        device_id = (can_id >> 11) & 0x7FF
        if self.hub_of(device_id) is None:
            return
        msg_id = can_id >> 24

        if msg_id == START_OF_MESSAGE_ID:
            if len(data) < 2:
                self.drops.append((ts, "bad_start", "%d bytes" % len(data)))
                return
            num_remaining = data[0] >> 3
            if num_remaining > MAX_FRAMES_PER_MESSAGE:
                self.drops.append((ts, "bad_start", "frames=%d" % num_remaining))
                return
            if num_remaining == 1:
                self.drops.append((ts, "bad_start", "total=1"))
                return
            if num_remaining == 0:
                self.interpret(data[1:], can_id, ts, True)
                return
            if len(data) >= 3 and data[2] not in TOP_TRONIC_COMMANDS:
                # Not a TopTronic datapoint response (e.g. the 0x70/0x74
                # register-block broadcasts). Rejecting it keeps it out of the
                # pending map so it cannot evict a real in-progress response.
                self.drops.append((ts, "non_toptronic_start", "cmd=0x%02X" % data[2]))
                return
            header = data[1]
            work_key = (device_id << 8) | header
            self.pending[work_key] = {
                "data": bytearray(data[2:]),
                "remaining": num_remaining - 1,
                "ts": ts,
                "device_id": device_id,
                "header": header,
            }
            return

        # Continuation frame.
        if len(data) < 2:
            self.drops.append((ts, "bad_cont", "%d bytes" % len(data)))
            return
        header = data[0]
        self.continuation_headers.add((device_id, header))
        work_key = (device_id << 8) | header
        entry = self.pending.get(work_key)
        if entry is None:
            return  # continuation for an unknown/expired message
        if entry["remaining"] == 0:
            del self.pending[work_key]
            return
        entry["data"] += data[1:]
        entry["remaining"] -= 1
        if entry["remaining"] != 0:
            return
        msg = bytes(entry["data"])
        del self.pending[work_key]
        if len(msg) < MIN_MESSAGE_LEN + 2:
            self.drops.append((ts, "short_reassembly", "%d bytes" % len(msg)))
            return
        received_crc = (msg[-2] << 8) | msg[-1]
        computed_crc = compute_crc16(msg[:-2])
        if received_crc != computed_crc:
            self.drops.append((ts, "crc_fail", "recv=0x%04X comp=0x%04X"
                               % (received_crc, computed_crc)))
            return
        self.interpret(msg[:-2], can_id, ts, False)

    def finish(self):
        """Record everything still waiting for continuations."""
        for work_key, entry in self.pending.items():
            device_id, header = entry["device_id"], entry["header"]
            self.uncompleted[work_key] = {
                "ts": entry["ts"],
                "device_id": device_id,
                "header": header,
                "remaining": entry["remaining"],
                "len": len(entry["data"]),
                "exact": (device_id, header) in self.continuation_headers,
                "plus1": (device_id, (header + 1) & 0xFF) in self.continuation_headers,
                "minus1": (device_id, (header - 1) & 0xFF) in self.continuation_headers,
            }


# ---------------------------------------------------------------------------
# Log parsing + reporting
# ---------------------------------------------------------------------------
def parse_hubs(spec, presets):
    hubs = {}
    for item in spec.split(","):
        item = item.strip()
        if not item:
            continue
        preset_dir, _, addr = item.partition(":")
        if preset_dir not in presets:
            print("warning: no presets found for %r" % preset_dir, file=sys.stderr)
        hubs[int(addr)] = preset_dir
    return hubs


def replay(path, hubs, presets):
    replayer = Replayer(hubs, presets)
    with open(path, "r", encoding="utf-8", errors="replace") as handle:
        for line in handle:
            match = FRAME_RE.search(line)
            if not match:
                continue
            ts = line[1:13] if line.startswith("[") else "?"
            can_id = int(match.group(1), 16)
            data = bytearray(int(tok, 16) for tok in match.group(2).split())
            replayer.feed(can_id, data, ts)
    replayer.finish()
    return replayer


def report(replayer, timeline):
    print("=" * 78)
    print("TopTronic candump replay (parser mirror)")
    print("=" * 78)

    if timeline:
        for ts, _key, name, type_name, raw, value, single in replayer.dispatches:
            print("  %s %-40s %-4s raw=%-12d value=%s%s"
                  % (ts, name[:40], type_name, raw, value, "" if single else " (multi)"))

    # Group dispatches per datapoint: how often decoded, last value.
    per_key = {}
    for ts, _key, name, _type_name, value, value_scaled, _single in replayer.dispatches:
        stat = per_key.setdefault((name,), {"n": 0, "last": value_scaled, "ts": ts})
        stat["n"] += 1
        stat["last"] = value_scaled
        stat["ts"] = ts

    print("\n-- decoded datapoints (%d dispatches, %d distinct) --"
          % (len(replayer.dispatches), len(per_key)))
    for (name,) in sorted(per_key):
        stat = per_key[(name,)]
        print("  %-44s n=%-4d last=%s (@%s)"
              % (name[:44], stat["n"], stat["last"], stat["ts"]))

    print("\n-- drops (%d) --" % len(replayer.drops))
    reasons = {}
    for ts, reason, detail in replayer.drops:
        reasons.setdefault(reason, []).append((ts, detail))
    for reason in sorted(reasons):
        items = reasons[reason]
        print("  %-22s %d" % (reason, len(items)))
        for ts, detail in items[:5]:
            print("      %s %s" % (ts, detail))
        if len(items) > 5:
            print("      ... %d more" % (len(items) - 5))

    print("\n-- multi-frame messages started but NEVER completed (%d) --"
          % len(replayer.uncompleted))
    if replayer.uncompleted:
        print("  (a sensor fed only by these stays stale/0 until a single-frame")
        print("   0x42 response for the same datapoint happens to arrive)")
        for _, entry in sorted(replayer.uncompleted.items()):
            hint = []
            if entry["exact"]:
                hint.append("exact header seen")
            if entry["plus1"]:
                hint.append("header+1 continuation seen!")
            if entry["minus1"]:
                hint.append("header-1 continuation seen")
            print("  %s node=0x%03X header=0x%02X remaining=%d buffered=%dB  %s"
                  % (entry["ts"], entry["device_id"], entry["header"],
                     entry["remaining"], entry["len"], "; ".join(hint)))

    print("\n-- registered datapoints that NEVER decoded --")
    decoded_names = {name for (name,) in per_key}
    missing = []
    for preset_dir, entities in replayer.presets.items():
        if preset_dir not in set(replayer.hubs.values()):
            continue
        for _key, (name, type_name, _mult) in entities.items():
            if name not in decoded_names:
                missing.append((preset_dir, name, type_name))
    for preset_dir, name, type_name in sorted(missing)[:60]:
        print("  %-4s %-44s %s" % (preset_dir, name[:44], type_name))
    if len(missing) > 60:
        print("  ... %d more" % (len(missing) - 60))
    print("  total: %d" % len(missing))
    print("\nNOTE: 'registered datapoints that NEVER decoded' is the issue-#41")
    print("      shortlist -- these entities never received a value during the")
    print("      capture, so they hold whatever they had before (usually 0).")


def main(argv=None):
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("log", help="candump log file")
    parser.add_argument("--hubs", default="WEZ:1,HV:8,BM:8",
                        help="device node map, e.g. WEZ:1,HV:8,BM:8 (default)")
    parser.add_argument("--language", default="de",
                        help="preset language: de/en/fr/it (default de)")
    parser.add_argument("--timeline", action="store_true",
                        help="print every decoded dispatch in capture order")
    args = parser.parse_args(argv)

    presets = load_presets(args.language)
    if not presets:
        print("error: no presets found under %s" % PRESETS_DIR, file=sys.stderr)
        return 2
    hubs = parse_hubs(args.hubs, presets)
    replayer = replay(args.log, hubs, presets)
    report(replayer, args.timeline)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
