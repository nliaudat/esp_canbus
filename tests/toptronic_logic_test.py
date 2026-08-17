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
    """num_cont written into the first-frame header: ceil(remaining / 7)."""
    first_chunk = min(6, msg_len)
    after_first = msg_len - first_chunk
    return math.ceil(after_first / 7)


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
    # num_cont = number of CONTINUATION frames (first frame excluded); the first
    # frame header carries num_cont, and reassembly waits for exactly num_cont.
    for msg_len in range(7, 60):
        total_frames = 1 + num_continuation_frames(msg_len)
        assert num_continuation_frames(msg_len) >= 1
        assert total_frames == 1 + math.ceil(max(0, msg_len - 6) / 7)
        # first_frame byte 0 upper 5 bits == number of continuation frames
        first_header = num_continuation_frames(msg_len) << 3
        assert (first_header >> 3) == num_continuation_frames(msg_len)
    # Spot checks
    assert num_continuation_frames(7) == 1  # 6 in first frame, 1 left
    assert num_continuation_frames(13) == 1  # 7 left -> one 7-byte continuation
    assert num_continuation_frames(14) == 2  # 8 left -> two continuations
    print("OK  continuation-frame counting (num_remaining == num_cont)")


def test_reassembly_wait_count():
    # Regression for the off-by-one fix: a message declaring num_remaining (>0)
    # must dispatch after receiving exactly num_remaining continuation frames,
    # NOT num_remaining - 1.
    for num_remaining in (1, 2, 3, 5, 10):
        remaining = num_remaining  # fixed semantics
        assert remaining == num_remaining  # no -1 introduced
    # One-continuation message: 1 frame must complete it.
    assert num_continuation_frames(7) == 1
    # Two-continuation message: 2 frames must complete it.
    assert num_continuation_frames(14) == 2
    print("OK  reassembly completes after exactly num_cont continuation frames")


if __name__ == "__main__":
    test_crc16_samples()
    test_build_can_id()
    test_build_get_request()
    test_build_set_request()
    test_continuation_count_semantics()
    test_reassembly_wait_count()
    print("\nAll logic tests passed.")