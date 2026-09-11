#!/usr/bin/env python3
"""Known-answer tests for the TopTronic protocol logic.

Mirrors the algorithms implemented in ``esphome/components/toptronic/toptronic.cpp``
(build_can_id, build_get_request/build_set_request, compute_crc16, and the
multi-frame continuation-count arithmetic) and validates them against captured
bus samples. Run with:  python tests/toptronic_logic_test.py
"""

import math

# ---------------------------------------------------------------------------
# Algorithm mirrors (kept byte-for-byte equivalent to toptronic.cpp)
# ---------------------------------------------------------------------------


def reflect(val, width):
    out = 0
    for _ in range(width):
        out = (out << 1) | (val & 1)
        val >>= 1
    return out


def compute_crc16(data):
    """CRC-16/ARC-family with init=0xB006 (see docs/hoval_canbus.md)."""
    crc = 0xB006
    for byte in data:
        byte = reflect(byte, 8)
        for b in range(7, -1, -1):
            bit = (byte >> b) & 1
            top = (crc >> 15) & 1
            crc = ((crc << 1) ^ (0x1021 if top ^ bit else 0)) & 0xFFFF
    return reflect(crc, 16)


GATEWAY_DEVICE_TYPE = 1153  # GW


def build_can_id(sender_id, receiver_mask):
    return (0x7F << 22) | (sender_id << 11) | receiver_mask


# Device-type bit values (mirror of the component's DeviceType enum). A hub's CAN
# node id is ``device_type | device_addr`` — e.g. WEZ@1 -> 1, HV@8 -> 520
# (512|8), BM@8 -> 1032 (1024|8). BM/BD and HK/HKW are aliases.
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


def resolve_hub_node_id(device_type, device_addr):
    """Node id a hub's frames carry: ``device_type | device_addr``."""
    return DEVICE_TYPE_IDS[device_type.upper()] | int(device_addr)


def resolve_entity_id_qualifier(device_type, device_addr, shares_addr, bus_id):
    """Qualifier prefixed to a *colliding* preset id (mirror of __init__.py).

    ``shares_addr`` is True when another hub uses the same device type **and**
    address (on a different CAN bus) — only then is the bus id needed, so the
    common same-type/different-address case keeps the short ``<TYPE>_<addr>``.
    """
    qualifier = "%s_%s" % (device_type.upper(), device_addr)
    if shares_addr:
        qualifier = "%s_%s" % (qualifier, bus_id)
    return qualifier


GET_REQ = 0x40
SET_REQ = 0x46


def build_get_request(function_group, function_number, datapoint):
    return [
        0x01,
        GET_REQ,
        function_group,
        function_number,
        (datapoint >> 8) & 0xFF,
        datapoint & 0xFF,
    ]


def build_set_request(function_group, function_number, datapoint, value):
    return [
        0x01,
        SET_REQ,
        function_group,
        function_number,
        (datapoint >> 8) & 0xFF,
        datapoint & 0xFF,
    ] + list(value)


def num_continuation_frames(msg_len):
    """Number of continuation frames for a payload of this length."""
    first_chunk = min(6, msg_len)
    after_first = msg_len - first_chunk
    return math.ceil(after_first / 7)


def total_frame_count(msg_len):
    """TOTAL frame count written into the first-frame header (first + continuations).

    Verified against captured bus traffic: a 14-byte response carries header
    0x19 (3 total), a 9-byte response carries 0x11 (2 total).
    """
    return 1 + num_continuation_frames(msg_len)


# ---------------------------------------------------------------------------
# Captured reference samples (see docs/crc_find.py and docs/hoval_canbus.md)
# ---------------------------------------------------------------------------

CRC_SAMPLES = [
    ("7400ff00000000ffff", 0x71E5),
    ("7401ff00000000ffff", 0xF05A),
    ("7402ff00000000ffff", 0x7A8A),
    ("7403ff00000000ffff", 0xFB35),
    ("7404ff00000000ffff", 0x673B),
    ("740008000000003200", 0x5406),
    ("420000a28d0000000e", 0x3481),
    ("4200004e4500000000", 0x7F4F),
    ("56320092e8700064", 0x00A4),
    ("56320092eb700064", 0x2569),
    ("42320001f9436f6e7374616e74", 0x7BD2),
    ("560000a28d800000000000000034", 0x10B3),
    ("5600004e45800000000000000034", 0xD57C),
    ("42000071720800ff01080232000000e06300000000", 0x279B),
]


def compute_crc16_table(data):
    """Lookup-table realization of compute_crc16().

    The bit-wise algorithm reflects each input byte, runs a left-shifting
    (MSB-first) CRC-16/poly 0x1021 loop, then reflects the final CRC. The table
    form therefore uses an MSB-first table with pre-reflected bytes:
        crc = (crc << 8) ^ table[((crc >> 8) ^ reflect(byte)) & 0xFF]
    """
    table = []
    for i in range(256):
        v = i << 8
        for _ in range(8):
            v = ((v << 1) ^ 0x1021) if (v & 0x8000) else (v << 1)
        table.append(v & 0xFFFF)

    crc = 0xB006  # init
    for byte in data:
        crc = ((crc << 8) ^ table[((crc >> 8) ^ reflect(byte, 8)) & 0xFF]) & 0xFFFF
    return reflect(crc, 16)  # refout=true


def test_crc16_samples():
    for hex_msg, expected in CRC_SAMPLES:
        actual = compute_crc16(bytes.fromhex(hex_msg))
        assert actual == expected, f"CRC mismatch for {hex_msg}: got 0x{actual:04X}, want 0x{expected:04X}"
        # Table form must agree with the bit-wise form for the same bytes.
        assert compute_crc16_table(bytes.fromhex(hex_msg)) == expected, (
            f"table CRC mismatch for {hex_msg}: got 0x{compute_crc16_table(bytes.fromhex(hex_msg)):04X}"
        )
    print(f"OK  compute_crc16() + table form match all {len(CRC_SAMPLES)} captured samples")


def test_build_can_id():
    # (0x7F << 22) | (sender << 11) | receiver
    sender = GATEWAY_DEVICE_TYPE | 8  # 0x481 | 0x08
    receiver = (512 | 8)  # HV device, addr 8
    can_id = build_can_id(sender, receiver)
    assert can_id == (0x7F << 22) | (sender << 11) | receiver
    # msg_id = can_id >> 24 must be 0x1F for start frames
    assert (can_id >> 24) == 0x1F
    # device_id = (can_id >> 11) & 0x7FF must be the receiver (sender in idle use)
    assert ((can_id >> 11) & 0x7FF) == sender
    print("OK  build_can_id() layout (msg_id, sender, receiver)")


def test_build_get_request():
    expected = [0x01, 0x40, 50, 0, (40651 >> 8) & 0xFF, 40651 & 0xFF]
    assert build_get_request(50, 0, 40651) == expected
    assert expected[0] == 0x01  # single-frame flag
    assert expected[1] == GET_REQ
    print("OK  build_get_request() byte layout")


def test_build_set_request():
    value = [0xAA, 0xBB, 0xCC]
    req = build_set_request(50, 0, 40651, value)
    assert req[:2] == [0x01, SET_REQ]
    assert req[2:6] == [50, 0, (40651 >> 8) & 0xFF, 40651 & 0xFF]
    assert req[6:] == value
    print("OK  build_set_request() byte layout")


def test_continuation_count_semantics():
    # data[0]>>3 is the TOTAL frame count (first frame + continuations);
    # the reassembler must wait for num_remaining - 1 continuation frames.
    for msg_len in range(7, 60):
        total = total_frame_count(msg_len)
        assert num_continuation_frames(msg_len) == total - 1
        assert total == 1 + math.ceil(max(0, msg_len - 6) / 7)
        # first-frame byte 0 upper 5 bits == TOTAL frame count
        first_header = total << 3
        assert (first_header >> 3) == total
    # Spot checks (continuation counts stay the same)
    assert num_continuation_frames(7) == 1  # 6 in first frame, 1 left
    assert num_continuation_frames(13) == 1  # 7 left -> one 7-byte continuation
    assert num_continuation_frames(14) == 2  # 8 left -> two continuations
    print("OK  continuation-frame counting (header=total, wait=total-1)")


def test_reassembly_wait_count():
    # Regression: the first-frame header is the TOTAL frame count, so a message
    # declaring num_remaining (>0) dispatches after exactly num_remaining - 1
    # continuation frames.
    for num_remaining in (2, 3, 4, 6, 11):
        expected_wait = num_remaining - 1
        assert expected_wait == num_remaining - 1
    # 2-total message (1 continuation): 1 frame completes it.
    assert num_continuation_frames(9) == 1  # 9-byte response -> total 2
    # 3-total message (2 continuations): 2 frames complete it.
    assert num_continuation_frames(14) == 2  # 14-byte response -> total 3
    print("OK  reassembly completes after num_remaining - 1 continuation frames")


# ---------------------------------------------------------------------------
# Retry-based refresh burst (mirror of TopTronic::loop() + update_all()
# + interpret_message() in toptronic.cpp)
# ---------------------------------------------------------------------------

# State of the refresh burst drain. Mirrors TopTronic's pending_refresh_ deque
# (entry = RefreshEntry {sensor, last_send_ms, attempts}) plus the global
# last_refresh_send_ms_ timestamp that gates per-send spacing.
def new_burst():
    return {
        "entries": [],
        "last_send_ms": 0,
        "in_progress": False,
        "queued": 0,
        "answered": 0,
        "dropped": 0,
        "progress_ms": 0,
    }


def queue_sensor(burst, sensor_id):
    burst["entries"].append({"sensor": sensor_id, "last_send_ms": 0, "attempts": 0})


def answer_sensor(burst, sensor_id, now=0):
    """Mirror of interpret_message() removing a matched sensor from the queue.

    While a burst is in progress, an answered sensor also bumps the completion
    accounting (answered counter) and the stall-watchdog progress timestamp.
    """
    before = len(burst["entries"])
    burst["entries"] = [e for e in burst["entries"] if e["sensor"] != sensor_id]
    if len(burst["entries"]) < before and burst["in_progress"]:
        burst["answered"] += 1
        burst["progress_ms"] = now


def effective_gap(refresh_gap_ms, max_refresh_per_loop):
    """Mirror of TopTronic::loop()'s effective per-GET spacing computation.

    Uses ceiling division so a burst never emits more than max_refresh_per_loop
    GETs inside the refresh window (e.g. ceil(50/8)=7ms -> exactly 8 GETs at
    0..49ms, the 9th at 56ms being outside the 50ms window). A minimum of 1 ms
    is kept so a config with refresh_gap_ms < max_refresh_per_loop never drives
    the time gate to zero (which would emit a GET on every main-loop iteration).
    """
    burst = max_refresh_per_loop if max_refresh_per_loop else 1
    div = (refresh_gap_ms + burst - 1) // burst
    return div if div != 0 else 1


def drain_tick(burst, now, gap_ms, retry_interval_ms, max_retries):
    """Process one loop() tick of the refresh burst drain.

    Faithful mirror of TopTronic::loop()'s burst block:
      - only a send is attempted when gap time has elapsed since the last send
        (global last_refresh_send_ms_)
      - the front entry is sent when it is fresh (attempts==0) OR older than
        retry_interval_ms (so an in-flight response is not re-polled early)
      - after a send, the entry is re-queued unless attempts exceeded
        max_retries (then it is dropped; the normal 30 s poll is the backstop)
    Returns the number of GETs actually sent on this tick.
    """
    sent = 0
    if not burst["entries"]:
        return sent
    if now - burst["last_send_ms"] >= gap_ms:
        entry = burst["entries"][0]
        since_last = now - entry["last_send_ms"]
        if entry["attempts"] == 0 or since_last >= retry_interval_ms:
            entry["attempts"] += 1
            entry["last_send_ms"] = now
            burst["last_send_ms"] = now
            burst["progress_ms"] = now  # a GET was sent: burst made progress
            burst["entries"].pop(0)
            if entry["attempts"] <= max_retries:
                burst["entries"].append(entry)  # re-queue behind the others
            else:
                burst["dropped"] += 1
            sent = 1
    return sent


def stall_watchdog(burst, now, retry_interval_ms, stall_base_ms=5000):
    """Mirror of loop()'s burst stall watchdog.

    A draining burst must keep making progress (a GET sent, or a response
    erasing an entry) at roughly the retry cadence. If it has been idle for
    stall_base_ms + retry_interval_ms, the burst is wedged and is aborted: the
    remaining entries are counted as dropped, the burst is marked finished, and
    a later refresh can start fresh (the normal 30 s poll is the backstop).
    Returns the number of entries aborted, or 0 if the burst is healthy.
    """
    if not burst["in_progress"] or not burst["entries"]:
        return 0
    stall_timeout = stall_base_ms + retry_interval_ms
    if now - burst["progress_ms"] >= stall_timeout:
        abandoned = len(burst["entries"])
        burst["dropped"] += abandoned
        burst["entries"].clear()
        burst["in_progress"] = False
        return abandoned
    return 0


def test_effective_gap_ceiling_division():
    # ceil(50/8) = 7 ms -> exactly 8 GETs per 50 ms window (budget respected).
    # The old floor division (6 ms) would emit 9 GETs at 0..48 ms.
    assert effective_gap(50, 8) == 7
    assert effective_gap(40, 8) == 5
    assert effective_gap(8, 8) == 1
    # Degenerate but schema-valid config (refresh_gap_ms < max_refresh_per_loop):
    # still clamped to >= 1 ms so the time gate is never "always true".
    assert effective_gap(5, 8) == 1
    assert effective_gap(1, 1) == 1
    assert effective_gap(0, 0) == 1  # refresh_burst fallback to 1

    # With a 1 ms floor, the drain never sends two GETs in the same millisecond.
    gap, retry_interval, max_retries = effective_gap(5, 8), 200, 3
    burst = new_burst()
    for sensor in ("A", "B", "C"):
        queue_sensor(burst, sensor)
    assert drain_tick(burst, 30000, gap, retry_interval, max_retries) == 1
    # Same-tick retry of the front entry is gated by the 1 ms gap.
    assert drain_tick(burst, 30000, gap, retry_interval, max_retries) == 0
    # After 1 ms elapses, another GET may go out (still spaced).
    assert drain_tick(burst, 30001, gap, retry_interval, max_retries) == 1
    print("OK  effective_gap uses ceiling division (budget respected, >= 1 ms floor)")


def test_refresh_budget_not_exceeded_per_window():
    """A burst must never emit more than max_refresh_per_loop GETs in one window.

    Regression for the Greptile review: floor spacing (50/8 = 6 ms) put GETs at
    0..48 ms = 9 requests inside the 50 ms window configured for 8. Ceiling
    spacing (7 ms) keeps exactly 8 at 0..49 ms; the 9th would land at 56 ms.
    """
    refresh_gap_ms, budget = 50, 8
    gap = effective_gap(refresh_gap_ms, budget)  # 7
    retry_interval, max_retries = 200, 3

    # Queue 8 distinct sensors (each send hits a fresh attempts==0 entry, so no
    # early retry shortens the loop) and drain continuously over a window.
    burst = new_burst()
    for i in range(budget):
        queue_sensor(burst, f"S{i}")

    t0 = 30000
    now = t0
    sent_times = []
    while now - t0 < refresh_gap_ms and burst["entries"]:
        sent = drain_tick(burst, now, gap, retry_interval, max_retries)
        if sent:
            sent_times.append(now)
        now += 1  # walk tick by tick

    # 8 distinct sensors -> exactly 8 GETs in the window, never 9.
    assert len(sent_times) == budget, f"expected {budget} GETs, got {len(sent_times)}: {sent_times}"
    # And all within the window.
    assert all(t - t0 < refresh_gap_ms for t in sent_times), sent_times
    # Spacing is >= the effective gap.
    diffs = [sent_times[i + 1] - sent_times[i] for i in range(len(sent_times) - 1)]
    assert all(d >= gap for d in diffs), diffs
    print(f"OK  {budget} GETs in {refresh_gap_ms} ms window, spacing >= {gap} ms")


def test_refresh_retry_answered_removed():
    gap, retry_interval, max_retries = 50, 200, 3
    burst = new_burst()
    queue_sensor(burst, "BM_83_0_0")

    # now is the boot millis() at which the refresh fires (always large), so
    # the first gap is already elapsed -> fresh entry is sent immediately.
    assert drain_tick(burst, 30000, gap, retry_interval, max_retries) == 1
    assert len(burst["entries"]) == 1 and burst["entries"][0]["attempts"] == 1

    # Response arrives -> interpret_message() removes the matched entry, so it
    # is never re-polled.
    answer_sensor(burst, "BM_83_0_0")
    assert burst["entries"] == []

    # Empty burst is a no-op.
    assert drain_tick(burst, 30100, gap, retry_interval, max_retries) == 0
    print("OK  answered GET is removed from the refresh queue")


def test_refresh_retry_unanswered_get_retried_then_give_up():
    gap, retry_interval = 50, 200
    max_retries = 3  # total transmissions = 1 initial + 3 retries = 4, then give up

    burst = new_burst()
    queue_sensor(burst, "BM_83_0_0")

    sends = 0
    sends_by_attempt = []
    now = 0
    # Step far enough (>= retry_interval) each time so the front entry is due,
    # and collect the total number of GETs sent until the queue empties.
    while burst["entries"]:
        now += 250
        sends += drain_tick(burst, now, gap, retry_interval, max_retries)
        if burst["entries"]:
            sends_by_attempt.append(burst["entries"][0]["attempts"])

    # initial send (1) + 3 re-sends = 4 transmissions total. The entry is
    # re-queued with attempts 1,2,3; when attempts reaches 4 (> max_retries) it
    # is dropped (never sent a 5th time) — the normal 30 s poll is the backstop.
    assert sends == 4, f"expected 4 GETs total, got {sends}"
    assert sends_by_attempt == [1, 2, 3], sends_by_attempt
    print("OK  unanswered GET sent initially + max_refresh_retries times, then dropped")


def test_refresh_coalesce_during_burst():
    """A "Refresh all" press during a burst is deferred, not dropped.

    Mirrors update_all() setting refresh_pending_ when pending_refresh_ is
    non-empty, and loop() starting a fresh burst once the current one empties.
    """
    gap, retry_interval, max_retries = 50, 200, 3
    burst = new_burst()
    refresh_pending = False

    # First burst starts with one sensor.
    queue_sensor(burst, "HV_50_0_40651")
    assert drain_tick(burst, 30000, gap, retry_interval, max_retries) == 1

    # A "Refresh all" press arrives while the burst is still draining:
    # update_all() defers it (sets refresh_pending), it does NOT queue a duplicate.
    assert len(burst["entries"]) == 1
    refresh_pending = True  # update_all() when pending_refresh_ non-empty
    assert len(burst["entries"]) == 1

    # Drain the current burst fully (sensor answered).
    answer_sensor(burst, "HV_50_0_40651")
    assert burst["entries"] == []

    # loop() sees the pending request after the burst empties and starts a new one.
    if refresh_pending and not burst["entries"]:
        refresh_pending = False
        queue_sensor(burst, "BM_83_0_0")
    assert len(burst["entries"]) == 1
    assert refresh_pending is False
    # The deferred burst is now served.
    assert drain_tick(burst, 30100, gap, retry_interval, max_retries) == 1
    print("OK  refresh requested during a burst is coalesced and served afterward")


def test_refresh_burst_stall_aborted():
    """A burst that stops making progress is aborted by the loop() watchdog.

    Mirrors loop()'s stall watchdog: pending_refresh_ entries are dropped, the
    burst is marked finished (completion accounting stays honest), and a later
    refresh can start fresh instead of wedging the queue forever.
    """
    gap, retry_interval, max_retries = 50, 200, 1
    burst = new_burst()

    # update_all() queues a burst and arms the observability state.
    queue_sensor(burst, "BM_83_0_0")
    queue_sensor(burst, "HV_50_0_0")
    burst["in_progress"] = True
    burst["queued"] = 2
    burst["progress_ms"] = 30000

    # A healthy burst sends a GET well inside the stall window -> no abort.
    assert drain_tick(burst, 30000, gap, retry_interval, max_retries) == 1
    assert stall_watchdog(burst, 30000 + 3000, retry_interval) == 0
    assert len(burst["entries"]) == 2  # still draining normally

    # The queue then stops making progress (bus wedged / loop starved): after
    # 5 s + retry interval the watchdog aborts the burst and counts it dropped.
    assert stall_watchdog(burst, 30000 + 5000 + retry_interval, retry_interval) == 2
    assert burst["entries"] == []
    assert burst["in_progress"] is False
    assert burst["dropped"] == 2

    # A fresh refresh can start immediately (deferred run / next press / poll).
    queue_sensor(burst, "BM_83_0_0")
    burst["in_progress"] = True
    burst["progress_ms"] = 30000 + 6000
    assert drain_tick(burst, 30000 + 6000, gap, retry_interval, max_retries) == 1
    print("OK  stalled burst is aborted by the watchdog; a fresh refresh can start")


# ---------------------------------------------------------------------------
# Issue #41 — multi-frame reassembly / start-frame filtering
# ---------------------------------------------------------------------------
# Command bytes that may start a TopTronic message payload (mirror of
# is_toptronic_command() in toptronic.cpp).
TOP_TRONIC_COMMANDS = (GET_REQ, SET_REQ, 0x42, 0x56)


def is_toptronic_command(cmd):
    return cmd in TOP_TRONIC_COMMANDS


def reassemble(frames):
    """Mirror of parse_frame(): returns (dispatched_payloads, pending_keys).

    ``frames`` is a list of ``(can_id, data_bytes)``. Both single-frame
    dispatches and completed multi-frame reassemblies are returned as the
    payload bytes with the trailing 2 CRC bytes already stripped.
    """
    pending = {}   # (device_id, header) -> [bytearray, remaining]
    dropped = 0
    done = []
    for can_id, data in frames:
        msg_id = can_id >> 24
        device_id = (can_id >> 11) & 0x7FF
        if msg_id == 0x1F:
            if len(data) < 2:
                continue
            num_remaining = data[0] >> 3
            if num_remaining > 8 or num_remaining == 1:
                dropped += 1
                continue
            if num_remaining == 0:
                done.append(bytes(data[1:]))
                continue
            if len(data) < 3 or not is_toptronic_command(data[2]):
                dropped += 1
                continue
            pending[(device_id, data[1])] = [bytearray(data[2:]), num_remaining - 1]
        else:
            if len(data) < 2:
                continue
            key = (device_id, data[0])
            entry = pending.get(key)
            if entry is None:
                continue
            entry[0] += data[1:]
            entry[1] -= 1
            if entry[1] == 0:
                buf, _remaining = pending.pop(key)
                done.append(bytes(buf)[:-2])
    return done, pending, dropped


def test_start_frame_command_filter():
    """Non-TopTronic register-block broadcasts must not enter the pending map.

    The issue-#41 capture contains ~80 start frames whose payload begins with
    0x50/0x70/0x74 etc. (register blocks). They never send the continuations the
    reassembler waits for, so admitting them only fills pending_messages_ and
    evicts real in-progress datapoint responses.
    """
    for cmd in (GET_REQ, SET_REQ, 0x42, 0x56):
        assert is_toptronic_command(cmd), f"0x{cmd:02X} must be accepted"
    for cmd in (0x50, 0x70, 0x74, 0x61, 0x52, 0x08):
        assert not is_toptronic_command(cmd), f"0x{cmd:02X} must be rejected"

    # Real captures: keep the 0x42/0x56 datapoint responses, drop the rest.
    frames = [
        (0x1F400FFF, bytes.fromhex("19 23 56 02 00 13 BA 80".replace(" ", ""))),  # 0x56 ext resp
        (0x1F400FFF, bytes.fromhex("11 40 56 3C FE 00 2D F5".replace(" ", ""))),  # 0x56 ext resp
        (0x1F400FFF, bytes.fromhex("19 C5 70 A1 00 01 52 08".replace(" ", ""))),  # 0x70 block
        (0x1F400FFF, bytes.fromhex("11 5C 74 04 FF 00 00 00".replace(" ", ""))),  # 0x74 block
    ]
    _done, pending, dropped = reassemble(frames)
    assert dropped == 2, f"expected 2 dropped register blocks, got {dropped}"
    assert len(pending) == 2, f"expected 2 pending responses, got {len(pending)}"
    print("OK  register-block start frames are rejected before reassembly")


def test_reassembly_requires_matching_header():
    """A continuation only completes the message whose header it repeats.

    Reference sample (docs/candump_base.log §2): a 3-frame 0x56 response with
    header 0x5F reassembles to 52. The issue-#41 capture instead shows
    continuations whose header is start_header + 1, which the current matching
    rule (correctly, per the reference capture) refuses to complete: the
    datapoint then never publishes and the sensor keeps its stale/zero value.
    """
    start = 0x1F5047FF
    frames = [
        (start, bytes.fromhex("195F5600 00A28D80".replace(" ", ""))),
        (0x1E1047FF, bytes.fromhex("5F000000 00000000".replace(" ", ""))),
        (0x1D9047FF, bytes.fromhex("5F3410B3".replace(" ", ""))),
    ]
    done, pending, _dropped = reassemble(frames)
    assert len(done) == 1, f"expected 1 reassembly, got {len(done)}"
    assert done[0].hex() == "560000a28d800000000000000034", done[0].hex()
    assert compute_crc16(done[0]) == 0x10B3, "reassembled CRC must validate"

    # Same start frame, but the continuation carries header+1 (0x60): the
    # message must stay pending - this is the issue-#41 failure mode.
    frames = [
        (start, bytes.fromhex("195F5600 00A28D80".replace(" ", ""))),
        (0x1E1047FF, bytes.fromhex("60000000 00000000".replace(" ", ""))),
        (0x1D9047FF, bytes.fromhex("603410B3".replace(" ", ""))),
    ]
    done, pending, _dropped = reassemble(frames)
    assert done == [], "a mismatching header must not complete the message"
    # start can_id 0x1F5047FF -> sender node 0x208 (HV@8); header stays 0x5F.
    assert (0x208, 0x5F) in pending, "the 0x5F message must still be pending"
    print("OK  continuation must repeat the start frame header to complete")


def test_hub_node_id_resolution():
    """The documented --hubs defaults must resolve to the on-wire node ids.

    Frames are matched on ``device_type | device_addr`` (HV@8 -> 520), never the
    bare address, and two hubs must not collide on the same node id. This mirrors
    ``parse_hubs()`` in ``tests/replay_candump.py`` — kept as a mirror because
    that module imports PyYAML, which the CI logic-test job does not install.
    """
    # Documented default for the replay tool: "WEZ:1,HV:8,BM:8".
    resolved = {
        name: resolve_hub_node_id(name, addr)
        for name, addr in (("WEZ", 1), ("HV", 8), ("BM", 8))
    }
    assert resolved == {"WEZ": 1, "HV": 520, "BM": 1032}, resolved
    assert len(set(resolved.values())) == 3, "node ids must be distinct"

    # Aliases and reference values.
    assert resolve_hub_node_id("BD", 8) == 1032
    assert resolve_hub_node_id("HKW", 9) == (256 | 9)
    assert resolve_hub_node_id("GW", 12) == (1153 | 12)
    # A same-type pair keeps distinct node ids (different addresses).
    assert resolve_hub_node_id("HV", 8) != resolve_hub_node_id("HV", 9)
    print("OK  hub node ids use device_type | device_addr (defaults are distinct)")


def test_entity_id_qualifier_is_hub_unique():
    """Colliding preset ids must stay unique for every hub, including 3+ buses.

    Two hubs with the same device type and *different* addresses need no bus id;
    two or more sharing both the type and the address (only possible on
    different CAN buses) must include the bus id, otherwise the third hub would
    recreate an id already registered by the second and the build would fail.
    """
    assert resolve_entity_id_qualifier("HV", 8, False, "cbus") == "HV_8"
    assert resolve_entity_id_qualifier("HV", 9, False, "cbus") == "HV_9"

    qualifiers = {
        resolve_entity_id_qualifier("HV", 8, True, bus)
        for bus in ("cbus_a", "cbus_b", "cbus_c")
    }
    assert qualifiers == {"HV_8_cbus_a", "HV_8_cbus_b", "HV_8_cbus_c"}, qualifiers
    assert len(qualifiers) == 3, "three same-type+addr hubs must not collide"
    print("OK  colliding preset ids get a hub-unique qualifier (bus id when shared)")


def test_replay_keys_are_per_hub():
    """The replay tool must key results by hub node id, not by preset dir.

    Two hubs of the same device type at different addresses share one preset dir,
    so keying only on ``(preset_dir, datapoint)`` would merge their values and
    could hide a datapoint that never decoded on one of them.
    """
    import replay_candump as rc

    presets = {"HV": {(50, 0, 37602): ("Temperatur Abluft", "S16", 0.1)}}
    hubs, errors = rc.parse_hubs("HV:8,HV:9", presets)
    assert not errors, errors
    assert hubs == {520: "HV", 521: "HV"}, hubs

    replayer = rc.Replayer(hubs, presets)
    frame = bytes([0x01, 0x42, 50, 0, 0x92, 0xE2, 0x01, 0x18])  # (50,0,37602)=28.0
    for node in (520, 521):
        can_id = (0x1F << 24) | (node << 11) | 0x7FF
        replayer.feed(can_id, frame, "00:00:00.000")

    keys = {(d[1], d[3]) for d in replayer.dispatches}
    assert keys == {(520, (50, 0, 37602)), (521, (50, 0, 37602))}, keys
    print("OK  replay keys dispatches per hub node id (same-type hubs stay separate)")


def test_replay_stats_completeness():
    """The firmware [STATS] record is parsed and checked for completeness.

    Running records carry raw counters; the record emitted when candump turns OFF
    adds the authoritative ``| capture=OK parse=OK`` verdict. Both the verdict and
    the computed fallback must detect a lossy capture / a parsing gap.
    """
    import replay_candump as rc

    running = ("[12:00:00.000][I][toptronic:077]: [STATS] candump running: "
               "rx=100 logged=100 throttled=0 tx=12 | parsed=99 unowned=1 paused=0")
    stats = rc.parse_stats_line(running)
    assert stats == {"ctx": "candump running", "rx": 100, "logged": 100, "throttled": 0, "tx": 12,
                     "parsed": 99, "unowned": 1, "paused": 0, "capture": None, "parse": None}, stats
    assert rc.stats_verdict(stats) == (True, True)

    # Older firmware omits tx= and the verdict: both must stay optional.
    legacy = rc.parse_stats_line(
        "[12:00:00.000][I][toptronic:077]: [STATS] candump running: "
        "rx=100 logged=100 throttled=0 | parsed=99 unowned=1 paused=0")
    assert legacy["tx"] is None and legacy["capture"] is None, legacy
    assert rc.stats_verdict(legacy) == (True, True)

    final = running.replace("candump running", "candump off") + " | capture=OK parse=OK"
    stats = rc.parse_stats_line(final)
    assert (stats["capture"], stats["parse"]) == ("OK", "OK"), stats
    assert rc.stats_are_complete(stats) is True

    # A LOSSY capture: logged + throttled < rx. The verdict says so explicitly,
    # and the computed fallback (no verdict fields) must agree.
    lossy = rc.parse_stats_line(final.replace("capture=OK parse=OK", "capture=LOSSY parse=GAP")
                                .replace("logged=100", "logged=90"))
    assert rc.stats_verdict(lossy) == (False, False)
    assert rc.stats_are_complete(lossy) is False
    assert rc.stats_are_complete(dict(lossy, capture=None, parse=None)) is False

    # Frames not accounted for by parsed/unowned/paused -> parsing gap.
    assert rc.stats_are_complete(dict(stats, capture=None, parse=None, parsed=90,
                                      unowned=0, paused=0)) is False

    assert rc.parse_stats_line("no stats here") is None
    print("OK  replay [STATS] accounting parses and detects lossy captures")


def test_replay_sessions_are_scoped():
    """A multi-session log must check the SELECTED (last) capture, not the whole file.

    The firmware resets its frame counters every time candump is (re-)enabled, so
    one log can hold several captures. Counting every candump line in the file
    while comparing against only the last session's counters lets an earlier
    session offset a line missing from the selected one (or vice versa). See
    docs/candump.md (Completeness).
    """
    import os
    import tempfile
    import replay_candump as rc

    frame = "[12:00:00.000][I][candump:026]: 0x1FD047FF : 01 42 32 00 9E EE 1E"

    def off(rx, logged, tx=0):
        return ("[12:00:00.000][I][toptronic:077]: [STATS] candump off: "
                "rx=%d logged=%d throttled=0 tx=%d | parsed=%d unowned=0 paused=0 "
                "| capture=OK parse=OK" % (rx, logged, tx, rx))

    def running(rx, logged, tx=0):
        return ("[12:00:00.000][I][toptronic:077]: [STATS] candump running: "
                "rx=%d logged=%d throttled=0 tx=%d | parsed=%d unowned=0 paused=0"
                % (rx, logged, tx, rx))

    def replay_lines(all_lines):
        fd, path = tempfile.mkstemp(suffix=".log")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                handle.write("\n".join(all_lines) + "\n")
            # Empty hubs/presets: the frames are still counted as candump lines.
            return rc.replay(path, {}, {})
        finally:
            os.remove(path)

    # Session 1 (10 lines, complete) + session 2 (firmware logged 50, but only 40
    # lines reached the file -> 10 lost while copying). The whole-file count
    # (10 + 40 = 50) equals the selected session's expected 50, so a whole-file
    # check would WRONGLY report "nothing was lost".
    replayer = replay_lines([frame] * 10 + [off(10, 10)] + [frame] * 40 + [off(50, 50)])
    assert replayer.frame_lines == 50, replayer.frame_lines
    assert len(replayer.sessions) == 2, replayer.sessions
    selected = replayer.sessions[-1]
    assert selected["lines"] == 40, selected
    assert selected["stats"]["logged"] == 50, selected["stats"]

    # Session 2 still running (no 'candump off'): the running snapshot is selected
    # and only ITS lines are compared.
    replayer = replay_lines([frame] * 10 + [off(10, 10)] + [frame] * 45 + [running(50, 50)])
    assert len(replayer.sessions) == 2, replayer.sessions
    selected = replayer.sessions[-1]
    assert selected["lines"] == 45, selected
    assert selected["stats"]["ctx"] == "candump running", selected["stats"]
    assert selected["stats"]["capture"] is None, selected["stats"]

    # A single-session file is unchanged: every candump line belongs to it.
    replayer = replay_lines([frame] * 7 + [off(7, 7)])
    assert len(replayer.sessions) == 1, replayer.sessions
    assert replayer.sessions[-1]["lines"] == 7, replayer.sessions[-1]

    # Re-enable whose previous 'candump off' record is missing/trimmed: the
    # 'CANDUMP debug ENABLED' marker (logged where the counters reset) delimits the
    # new session, so its early frames are scoped correctly.
    enabled = ("[12:00:00.000][W][toptronic:077]: CANDUMP debug ENABLED "
               "- logging every CAN frame (auto-off in 120s, or turn off switch)")
    replayer = replay_lines(
        [enabled] + [frame] * 30 + [running(30, 30)]     # session 1 (no off record)
        + [enabled] + [frame] * 60 + [off(60, 60)])      # session 2 (complete)
    assert len(replayer.sessions) == 2, replayer.sessions
    selected = replayer.sessions[-1]
    assert selected["lines"] == 60, selected
    assert selected["reliable"] is True, selected

    # Re-enable whose off record AND enable marker are both missing: the boundary is
    # only visible as an rx reset at the first snapshot, so the frames before it
    # cannot be attributed to either session -> flagged unreliable, and the report
    # skips the check instead of reporting every such frame as missing.
    replayer = replay_lines([frame] * 100 + [running(100, 100)]
                            + [frame] * 4 + [running(4, 4)]
                            + [frame] * 56 + [off(60, 60)])
    assert len(replayer.sessions) == 2, replayer.sessions
    assert replayer.sessions[-1]["reliable"] is False, replayer.sessions[-1]
    assert replayer.sessions[-1]["lines"] == 56, replayer.sessions[-1]

    # Re-enable whose counters happen to MATCH the previous snapshot (snapshots are
    # every 10 s and the counters reset, so the new capture's first snapshot can be
    # equal): rx does NOT decrease, so the two captures merge into one session. The
    # merge is still caught because the file then holds more candump lines than the
    # session's logged + tx account for -> flagged unreliable, check skipped (rather
    # than wrongly reporting complete/lost).
    replayer = replay_lines([enabled] + [frame] * 30 + [running(30, 30)]
                            + [frame] * 30 + [running(30, 30)]
                            + [frame] * 30 + [off(60, 60)])
    assert len(replayer.sessions) == 1, replayer.sessions
    assert replayer.sessions[-1]["lines"] == 90, replayer.sessions[-1]
    assert replayer.sessions[-1]["reliable"] is False, replayer.sessions[-1]

    # Guard: a clean session (10 candump lines = 8 RX + 2 TX) keeps
    # lines == logged + tx and must stay reliable (no invariant false positive).
    replayer = replay_lines([enabled] + [frame] * 10 + [off(8, 8, tx=2)])
    assert replayer.sessions[-1]["reliable"] is True, replayer.sessions[-1]
    assert replayer.sessions[-1]["lines"] == 10, replayer.sessions[-1]
    print("OK  replay scopes the file-count check to the selected capture session")


if __name__ == "__main__":
    test_crc16_samples()
    test_build_can_id()
    test_build_get_request()
    test_build_set_request()
    test_continuation_count_semantics()
    test_reassembly_wait_count()
    test_effective_gap_ceiling_division()
    test_refresh_budget_not_exceeded_per_window()
    test_refresh_retry_answered_removed()
    test_refresh_retry_unanswered_get_retried_then_give_up()
    test_refresh_coalesce_during_burst()
    test_refresh_burst_stall_aborted()
    test_start_frame_command_filter()
    test_reassembly_requires_matching_header()
    test_hub_node_id_resolution()
    test_entity_id_qualifier_is_hub_unique()
    test_replay_keys_are_per_hub()
    test_replay_stats_completeness()
    test_replay_sessions_are_scoped()
    print("\nAll logic tests passed.")
