"""
CRC reverse-engineer using XOR-difference trick.

KEY INSIGHT: CRC_init(m1) XOR CRC_init(m2) = CRC_0(m1 XOR m2)
So the polynomial can be found independently of init/xorout.

E1 = CRC(7400...) XOR CRC(7401...) = 0x71E5 XOR 0xF05A = 0x81BF
This means: CRC_poly_0_0( [0,0x01,0,0,0,0,0,0,0] ) = 0x81BF  for the correct poly.

Step 1: find all polys where CRC_0_0 of the error message = 0x81BF
Step 2: for each candidate poly, find the init value that makes CRC_poly_init(7400...) = 0x71E5
"""

def reflect(val, width):
    out = 0
    for _ in range(width):
        out = (out << 1) | (val & 1)
        val >>= 1
    return out

def crc16(data, poly, init, refin, refout, xorout):
    crc = init & 0xFFFF
    for byte in data:
        if refin: byte = reflect(byte, 8)
        for i in range(7, -1, -1):
            bit = (byte >> i) & 1
            top = (crc >> 15) & 1
            crc = ((crc << 1) ^ (poly if top ^ bit else 0)) & 0xFFFF
    if refout: crc = reflect(crc, 16)
    return (crc ^ xorout) & 0xFFFF

# XOR difference between sample0 and sample1 (differ only in byte[1]: 0x00 vs 0x01)
# E1 = CRC(s0) XOR CRC(s1) = 0x71E5 XOR 0xF05A = 0x81BF
E1 = 0x71E5 ^ 0xF05A
E2 = 0x71E5 ^ 0x7A8A   # byte[1] 0x00 vs 0x02
print(f"E1 (bit0 flip at byte[1]) = 0x{E1:04X}")
print(f"E2 (bit1 flip at byte[1]) = 0x{E2:04X}")

# Error message: 9 bytes, only byte[1] = 0x01
error_msg = bytes([0, 0x01, 0, 0, 0, 0, 0, 0, 0])

# Step 1: Find all (poly, refin, refout) where CRC_0_0(error_msg) == E1
print("\nStep 1: Finding candidate polynomials (this takes a moment)...")
candidates = []
for poly in range(1, 0x10000):
    for refin in (True, False):
        for refout in (True, False):
            val = crc16(error_msg, poly, 0, refin, refout, 0)
            if val == E1:
                # Quick sanity: also check E2 constraint
                e2_msg = bytes([0, 0x02, 0, 0, 0, 0, 0, 0, 0])
                val2 = crc16(e2_msg, poly, 0, refin, refout, 0)
                if val2 == E2:
                    candidates.append((poly, refin, refout))

print(f"Found {len(candidates)} candidate polynomial(s) matching XOR constraints")
for c in candidates[:20]:
    print(f"  poly=0x{c[0]:04X} refin={c[1]} refout={c[2]}")

if not candidates:
    print("\nNO polynomial found satisfying the linear CRC constraints!")
    print("This means EITHER:")
    print("  (a) The CRC input is NOT just the payload bytes captured")
    print("  (b) The algorithm is not a polynomial CRC-16 at all")
    print("  (c) The CRC bytes are not at the end of the message")
    print("\nTrying other data arrangements...")
    # Try: payload reversed
    error_rev = bytes(reversed(error_msg))
    for poly in range(1, 0x10000):
        for refin in (True, False):
            for refout in (True, False):
                val = crc16(error_rev, poly, 0, refin, refout, 0)
                if val == E1:
                    e2_msg_rev = bytes(reversed(bytes([0, 0x02, 0, 0, 0, 0, 0, 0, 0])))
                    val2 = crc16(e2_msg_rev, poly, 0, refin, refout, 0)
                    if val2 == E2:
                        print(f"  REVERSED payload match: poly=0x{poly:04X} refin={refin} refout={refout}")
else:
    # Step 2: For each candidate poly, find init
    all_samples = [
        # 9-byte patterns (vary only in byte[1]: 0x00-0x04)
        ('7400ff00000000ffff', 0x71E5),
        ('7401ff00000000ffff', 0xF05A),
        ('7402ff00000000ffff', 0x7A8A),
        ('7403ff00000000ffff', 0xFB35),
        ('7404ff00000000ffff', 0x673B),
        # 9-byte pattern with different structure
        ('740008000000003200', 0x5406),
        # 9-byte pattern: cleaning count value
        ('420000a28d0000000e', 0x3481),
        # 9-byte: maint counter
        ('4200004e4500000000', 0x7F4F),
        # 8-byte patterns (fan speed register responses)
        ('56320092e8700064',   0x00A4),
        ('56320092eb700064',   0x2569),
        # 13-byte: GET response with ASCII "Constant"
        ('42320001f9436f6e7374616e74', 0x7BD2),
        # 14-byte: cleaning count extended
        ('560000a28d800000000000000034', 0x10B3),
        # 14-byte: maint counter extended
        ('5600004e45800000000000000034', 0xD57C),
        # 21-byte: large GET response (0x7172 register)
        ('42000071720800ff01080232000000e06300000000', 0x279B),
    ]
    parsed = [(bytes.fromhex(h), v) for h, v in all_samples]

    print("\nStep 2: Searching for init/xorout for each candidate...")
    found = []
    for poly, refin, refout in candidates:
        for xorout in range(0x10000):
            # Compute init from sample0: init = CRC_0_xorout(s0) XOR 0x71E5 XOR ...
            # Actually just compute CRC_0_xorout(s0), then init_contribution = 0x71E5 XOR that
            # For a CRC: CRC_init_xorout(m) = CRC_0_xorout(m) XOR init_contribution(poly, refin, refout, init)
            # init_contribution = CRC of an all-zero message with given init
            # So: find init such that CRC_poly_init_xorout(s0) = 0x71E5
            # = CRC_0_0(s0) XOR [CRC_0_0(zeros) XOR init XOR xorout effects] = complex
            # Simpler: just brute over init for the first sample
            pass
    
    # Smarter: compute CRC_0_xorout(s0) then derive what init value we need
    for poly, refin, refout in candidates:
        # CRC_init_xorout(m) = CRC_0_0(m) XOR init_residue XOR xorout
        # where init_residue = CRC of a length-len(m) all-zero msg with init=init, xorout=0
        # = init shifted through len(m)*8 zero bits
        s0 = bytes.fromhex('7400ff00000000ffff')
        crc_0_0_s0 = crc16(s0, poly, 0, refin, refout, 0)
        # For each xorout, the "adjustment" needed = 0x71E5 XOR crc_0_0_s0 XOR xorout
        # This adjustment = init "drifted" through the message
        # = init shifted through 9*8=72 zero-bit steps
        for xorout in (0x0000, 0xFFFF):
            needed = 0x71E5 ^ xorout ^ crc_0_0_s0
            # needed = "drift" of init through 72 zero bits
            # To invert: we need to find init such that shift_72(init, poly, refin, refout) = needed
            # Brute force init
            for init in range(0x10000):
                if crc16(bytes(9), poly, init, refin, refout, 0) == needed:
                    # Verify against all samples
                    if all(crc16(d, poly, init, refin, refout, xorout) == e for d, e in parsed):
                        found.append((poly, init, refin, refout, xorout))
                        print(f"  FULL MATCH: poly=0x{poly:04X} init=0x{init:04X} refin={refin} refout={refout} xorout=0x{xorout:04X}")
    
    if not found:
        print("\nPolynomial found but no init/xorout matched all samples.")
        print("Candidates poly list (check these against crccalc.com):")
        for poly, refin, refout in candidates[:10]:
            print(f"  poly=0x{poly:04X} refin={refin} refout={refout}")
