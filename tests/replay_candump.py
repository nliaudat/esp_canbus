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

--hubs takes ``<device_type>:<device_addr>`` pairs and resolves each to the CAN
node id actually seen on the wire (``device_type | device_addr``), e.g. WEZ:1 ->
1, HV:8 -> 520, BM:8 -> 1032.

The candump format is the one produced by the "candump debug" switch, e.g.
    [12:00:00.000][I][candump:026]: 0x1FD047FF : 01 42 32 00 9E EE 1E
"""

import argparse
import os
import re
import sys

# NOTE: PyYAML is imported lazily inside load_presets() so the parser mirror
# below can be imported (and unit-tested) without PyYAML installed.

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

# Firmware frame-accounting record, emitted while candump is ON (every 10 s) and
# once when it turns OFF:
#   [STATS] candump off: rx=N logged=N throttled=N | parsed=N unowned=N paused=N
STATS_RE = re.compile(
    r"\[STATS\]\s+(?P<ctx>[^:]+):\s+rx=(?P<rx>\d+)\s+logged=(?P<logged>\d+)\s+throttled=(?P<throttled>\d+)"
    r"(?:\s+tx=(?P<tx>\d+))?"
    r"\s+\|\s+parsed=(?P<parsed>\d+)\s+unowned=(?P<unowned>\d+)\s+paused=(?P<paused>\d+)"
    r"(?:\s+\|\s+capture=(?P<capture>OK|LOSSY)\s+parse=(?P<parse>OK|GAP))?"
)

STATS_KEYS = ("rx", "logged", "throttled", "parsed", "unowned", "paused")


def parse_stats_line(line):
    """Parse a firmware ``[STATS]`` record; return a dict or None.

    Optional fields (``None`` when absent): ``tx`` (TX frames exported to the log,
    present only in newer firmware) and the ``capture``/``parse`` verdict (present
    only on the record emitted when candump turns OFF — the authoritative one).
    """
    match = STATS_RE.search(line)
    if not match:
        return None
    return {
        key: value if key in ("ctx", "capture", "parse") else (int(value) if value is not None else None)
        for key, value in match.groupdict().items()
    }


def stats_verdict(stats):
    """Return ``(capture_ok, parse_ok)``.

    Prefers the firmware's own verdict (present on the ``candump off`` record);
    otherwise computes it — a running snapshot can be off by one because `parsed`
    is counted in the receive callback while `rx`/`logged` are counted later.
    """
    if stats.get("capture") is not None and stats.get("parse") is not None:
        return stats["capture"] == "OK", stats["parse"] == "OK"
    return (stats["rx"] == stats["logged"] + stats["throttled"],
            stats["parsed"] + stats["unowned"] + stats["paused"] == stats["rx"])


def stats_are_complete(stats):
    """True when the accounting proves nothing was lost and every frame examined."""
    return all(stats_verdict(stats))


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
    try:
        import yaml
    except ImportError:  # pragma: no cover - PyYAML ships with ESPHome
        raise SystemExit("PyYAML is required to load presets (pip install pyyaml)")

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
        self.stats = None                # latest firmware [STATS] record
        self.final_stats = None          # latest [STATS] record with a verdict (candump off)
        self.frame_lines = 0             # candump frame lines read from the file

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
        self.dispatches.append(
            (ts, device_id, preset_dir, key, name, type_name, raw,
             raw * multiply, single))

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
# Device-type bit values (mirror of the component's DeviceType enum). The CAN node
# id used on the wire is ``device_type | device_addr``, e.g. WEZ@1 -> 1,
# HV@8 -> 520 (512|8), BM@8 -> 1032 (1024|8). BM/BD and HK/HKW are aliases.
DEVICE_TYPE_IDS = {
    "WEZ": 0,
    "SOL": 64,
    "PS": 128,
    "FW": 192,
    "HK": 256,
    "HKW": 256,
    "MWA": 384,
    "GLT": 448,
    "HV": 512,
    "BM": 1024,
    "BD": 1024,
    "GW": 1153,
}

# Preset directory aliases (the on-wire type name differs from the dir name).
_PRESET_ALIAS = {"HKW": "HK", "BD": "BM"}


def parse_hubs(spec, presets):
    """Map ``<preset_dir>:<device_addr>`` pairs to CAN node ids.

    Frames are matched on the encoded node id ``device_type | device_addr``
    (e.g. HV@8 -> 520), never the bare address, so using the address alone would
    match no frame and silently drop that hub's traffic. Returns ``(hubs,
    errors)`` — the caller exits non-zero on any error rather than producing
    incomplete diagnostics.
    """
    hubs = {}
    errors = []
    for item in spec.split(","):
        item = item.strip()
        if not item:
            continue
        type_name, _, addr = item.partition(":")
        type_name = type_name.upper()
        if type_name not in DEVICE_TYPE_IDS:
            errors.append("unknown device type %r in --hubs" % type_name)
            continue
        preset_dir = _PRESET_ALIAS.get(type_name, type_name)
        if preset_dir not in presets:
            errors.append("no presets found for %r" % preset_dir)
            continue
        try:
            node = DEVICE_TYPE_IDS[type_name] | int(addr)
        except ValueError:
            errors.append("bad address %r for %s" % (addr, type_name))
            continue
        if node in hubs:
            errors.append("node 0x%03X mapped twice (%s and %s)"
                          % (node, hubs[node], preset_dir))
            continue
        hubs[node] = preset_dir
    return hubs, errors


def replay(path, hubs, presets):
    replayer = Replayer(hubs, presets)
    with open(path, "r", encoding="utf-8", errors="replace") as handle:
        for line in handle:
            stats = parse_stats_line(line)
            if stats is not None:
                replayer.stats = stats           # keep the latest record
                if stats.get("capture") is not None:
                    replayer.final_stats = stats  # ...and the authoritative one (candump off)
                continue
            match = FRAME_RE.search(line)
            if not match:
                continue
            replayer.frame_lines += 1
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

    # --- capture completeness, from the firmware's own [STATS] accounting ---
    print("\n-- capture completeness (firmware [STATS]) --")
    if replayer.stats is None:
        print("  no [STATS] record found in this log:")
        print("    - firmware older than the frame-accounting change, or")
        print("    - candump was not used (the record is emitted while candump is ON / on OFF).")
    else:
        s = replayer.final_stats or replayer.stats
        print("  source: %s" % ("[STATS] candump off (authoritative)"
                                if replayer.final_stats is not None else
                                "[STATS] running snapshot (may be off by one - turn candump off for the final record)"))
        print("  %s: rx=%d logged=%d throttled=%d | parsed=%d unowned=%d paused=%d"
              % (s["ctx"], s["rx"], s["logged"], s["throttled"], s["parsed"],
                 s["unowned"], s["paused"]))
        capture_ok, parse_ok = stats_verdict(s)
        print("  capture: rx == logged + throttled        -> %s"
              % ("OK (complete)" if capture_ok else "FAIL (capture is LOSSY)"))
        print("  parsing: parsed + unowned + paused == rx -> %s"
              % ("OK (every frame accounted for)" if parse_ok else "FAIL (frames unaccounted)"))
        if s["throttled"]:
            print("  WARNING: %d frames were throttled OUT of the capture." % s["throttled"])
        if s["unowned"]:
            print("  NOTE: %d frames came from nodes no hub owns (see [SKIP] lines at DEBUG)."
                  % s["unowned"])
        if s.get("tx") is not None:
            expected = s["logged"] + s["tx"]
            print("  candump lines in this file: %d (firmware logged %d RX + %d TX = %d)"
                  % (replayer.frame_lines, s["logged"], s["tx"], expected))
            if replayer.frame_lines < expected:
                print("  WARNING: %d candump line(s) are MISSING from this file" % (expected - replayer.frame_lines))
                print("           -> lost while COPYING the log (logger buffer/socket), not by the firmware.")
            elif replayer.frame_lines > expected:
                print("  NOTE: %d extra line(s) in this file (candump lines from outside this capture)."
                      % (replayer.frame_lines - expected))
            else:
                print("  -> the file matches the firmware exactly: nothing was lost to the log sink.")
        elif replayer.frame_lines < s["logged"]:
            print("  WARNING: this file holds %d candump lines but the firmware logged %d RX frames"
                  % (replayer.frame_lines, s["logged"]))
            print("           -> lines were lost while COPYING the log (logger buffer/socket), not by the firmware.")
        else:
            print("  candump lines in this file: %d (RX frames logged: %d; TX lines add to the file count)"
                  % (replayer.frame_lines, s["logged"]))

    if timeline:
        for (ts, device_id, preset_dir, _key, name, type_name, raw, value,
             single) in replayer.dispatches:
            print("  %s node=0x%03X %-4s %-34s %-4s raw=%-12d value=%s%s"
                  % (ts, device_id, preset_dir, name[:34], type_name, raw, value,
                     "" if single else " (multi)"))

    # Group dispatches per (hub node id, datapoint): two hubs of the same device
    # type at different addresses are distinct datapoints and must not be merged.
    per_key = {}
    for (ts, device_id, preset_dir, key, name, _type_name, _raw, value_scaled,
         _single) in replayer.dispatches:
        stat = per_key.setdefault(
            (device_id, key),
            {"dir": preset_dir, "name": name, "n": 0, "last": value_scaled, "ts": ts})
        stat["n"] += 1
        stat["last"] = value_scaled
        stat["ts"] = ts

    print("\n-- decoded datapoints (%d dispatches, %d distinct) --"
          % (len(replayer.dispatches), len(per_key)))
    for (device_id, (fg, fn, dp)) in sorted(per_key):
        stat = per_key[(device_id, (fg, fn, dp))]
        print("  node=0x%03X %-4s fg=%-3d fn=%-3d dp=%-6d %-34s n=%-4d last=%s (@%s)"
              % (device_id, stat["dir"], fg, fn, dp, stat["name"][:34], stat["n"],
                 stat["last"], stat["ts"]))

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

    print("\n-- registered datapoints that NEVER decoded (per hub) --")
    decoded = set(per_key)
    missing = []
    for device_id, preset_dir in sorted(replayer.hubs.items()):
        entities = replayer.presets.get(preset_dir, {})
        for key, (name, type_name, _mult) in entities.items():
            if (device_id, key) not in decoded:
                missing.append((device_id, preset_dir, key[0], key[1], key[2],
                                name, type_name))
    for device_id, preset_dir, fg, fn, dp, name, type_name in sorted(missing)[:60]:
        print("  node=0x%03X %-4s fg=%-3d fn=%-3d dp=%-6d %-34s %s"
              % (device_id, preset_dir, fg, fn, dp, name[:34], type_name))
    if len(missing) > 60:
        print("  ... %d more" % (len(missing) - 60))
    print("  total: %d" % len(missing))
    print("\nNOTE: 'registered datapoints that NEVER decoded' is the issue-#41")
    print("      shortlist -- these entities never received a value during the")
    print("      capture, so they hold whatever they had before (usually 0).")
    print("      ('multiply' filters are applied; lambda/clamp filters are not, so")
    print("       the device's 0x8000 'invalid' sentinel shows as -3276.8.)")


def main(argv=None):
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("log", help="candump log file")
    parser.add_argument("--hubs", default="WEZ:1,HV:8,BM:8",
                        help="hub map as TYPE:ADDR (node id = device_type|addr), "
                             "e.g. WEZ:1,HV:8,BM:8 (default)")
    parser.add_argument("--language", default="de",
                        help="preset language: de/en/fr/it (default de)")
    parser.add_argument("--timeline", action="store_true",
                        help="print every decoded dispatch in capture order")
    args = parser.parse_args(argv)

    presets = load_presets(args.language)
    if not presets:
        print("error: no presets found under %s" % PRESETS_DIR, file=sys.stderr)
        return 2
    hubs, errors = parse_hubs(args.hubs, presets)
    for message in errors:
        print("error: %s" % message, file=sys.stderr)
    if errors:
        print("error: fix --hubs (e.g. WEZ:1,HV:8,BM:8) and retry", file=sys.stderr)
        return 2
    replayer = replay(args.log, hubs, presets)
    report(replayer, args.timeline)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
