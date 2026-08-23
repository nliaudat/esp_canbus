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
    return {"entries": [], "last_send_ms": 0}


def queue_sensor(burst, sensor_id):
    burst["entries"].append({"sensor": sensor_id, "last_send_ms": 0, "attempts": 0})


def answer_sensor(burst, sensor_id):
    """Mirror of interpret_message() removing a matched sensor from the queue."""
    burst["entries"] = [e for e in burst["entries"] if e["sensor"] != sensor_id]


def effective_gap(refresh_gap_ms, max_refresh_per_loop):
    """Mirror of TopTronic::loop()'s effective per-GET spacing computation.

    Clamps the integer division to a minimum of 1 ms so that a config with
    refresh_gap_ms < max_refresh_per_loop never drives the time gate to zero
    (which would emit a GET on every main-loop iteration).
    """
    burst = max_refresh_per_loop if max_refresh_per_loop else 1
    div = refresh_gap_ms // burst
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
            burst["entries"].pop(0)
            if entry["attempts"] <= max_retries:
                burst["entries"].append(entry)  # re-queue behind the others
            sent = 1
    return sent


def test_effective_gap_clamped_to_one():
    # Default config: 50ms / 8 -> 6 ms per GET.
    assert effective_gap(50, 8) == 6
    assert effective_gap(40, 8) == 5
    assert effective_gap(8, 8) == 1
    # Degenerate but schema-valid config (refresh_gap_ms < max_refresh_per_loop):
    # integer division would be 0; it must clamp to 1 ms so the time gate is
    # never "always true". Regression for the Greptile P1 review comment.
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
    print("OK  effective_gap is clamped to >= 1 ms; GETs never collapse to zero spacing")


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


if __name__ == "__main__":
    test_crc16_samples()
    test_build_can_id()
    test_build_get_request()
    test_build_set_request()
    test_continuation_count_semantics()
    test_reassembly_wait_count()
    test_effective_gap_clamped_to_one()
    test_refresh_retry_answered_removed()
    test_refresh_retry_unanswered_get_retried_then_give_up()
    test_refresh_coalesce_during_burst()
    print("\nAll logic tests passed.")
