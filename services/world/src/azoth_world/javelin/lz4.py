"""Minimal LZ4 block decompressor (stdlib only).

Implements the LZ4 block format (no frame header): token nibbles for
literal/match lengths, 255-extended lengths, 2-byte LE offsets, minimum
match length 4. Enough for the Javelin 0x81 compressed datagrams.
"""


def decompress_lz4_block(data: bytes) -> bytes:
    out = bytearray()
    i = 0
    n = len(data)
    while i < n:
        tok = data[i]
        i += 1
        litlen = tok >> 4
        if litlen == 15:
            while True:
                if i >= n:
                    raise ValueError("lz4: truncated literal length")
                b = data[i]
                i += 1
                litlen += b
                if b != 255:
                    break
        if i + litlen > n:
            raise ValueError("lz4: truncated literals")
        out += data[i : i + litlen]
        i += litlen
        if i >= n:
            break  # last literals, no match follows
        if i + 2 > n:
            raise ValueError("lz4: truncated offset")
        offset = data[i] | (data[i + 1] << 8)
        i += 2
        if offset == 0 or offset > len(out):
            raise ValueError(f"lz4: bad offset {offset}")
        matchlen = (tok & 0xF) + 4
        if (tok & 0xF) == 15:
            while True:
                if i >= n:
                    raise ValueError("lz4: truncated match length")
                b = data[i]
                i += 1
                matchlen += b
                if b != 255:
                    break
        for _ in range(matchlen):
            out.append(out[len(out) - offset])
    return bytes(out)
