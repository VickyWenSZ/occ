import struct, zlib, math, os, pathlib

def _create_png(size):
    cx = cy = size / 2.0
    scale = size / 32.0
    r_outer = 9.0 * scale
    r_inner = (9.0 - 2.5) * scale
    r_dot   = 3.0 * scale
    bg    = (9,  9,  11,  255)
    green = (34, 197, 94, 255)

    def blend(a, b, t):
        return tuple(int(a[i] * (1 - t) + b[i] * t) for i in range(4))

    rows = []
    for y in range(size):
        row = bytearray()
        for x in range(size):
            dx = x - cx + 0.5
            dy = y - cy + 0.5
            d = math.sqrt(dx * dx + dy * dy)
            if d <= r_dot + 0.7:
                t = max(0.0, min(1.0, (r_dot + 0.7 - d) / 0.7))
                row.extend(blend(bg, green, t))
            elif d >= r_inner - 0.7 and d <= r_outer + 0.7:
                if d < r_inner + 0.7:
                    t = max(0.0, min(1.0, (d - (r_inner - 0.7)) / 1.4))
                else:
                    t = max(0.0, min(1.0, ((r_outer + 0.7) - d) / 0.7))
                row.extend(blend(bg, green, t))
            else:
                row.extend(bg)
        rows.append(bytes(row))

    def chunk(tag, data):
        body = tag + data
        return struct.pack('>I', len(data)) + body + struct.pack('>I', zlib.crc32(body) & 0xFFFFFFFF)

    ihdr = struct.pack('>II', size, size) + bytes([8, 6, 0, 0, 0])
    raw  = b''.join(b'\x00' + r for r in rows)
    return (
        b'\x89PNG\r\n\x1a\n'
        + chunk(b'IHDR', ihdr)
        + chunk(b'IDAT', zlib.compress(raw, 9))
        + chunk(b'IEND', b'')
    )

def _create_ico():
    sizes  = [16, 32, 48, 256]
    pngs   = [_create_png(s) for s in sizes]
    count  = len(pngs)
    header = struct.pack('<HHH', 0, 1, count)
    offset = 6 + 16 * count
    entries = b''
    for s, png in zip(sizes, pngs):
        w = s if s < 256 else 0
        h = s if s < 256 else 0
        entries += struct.pack('<BBBBHHII', w, h, 0, 0, 1, 32, len(png), offset)
        offset += len(png)
    return header + entries + b''.join(pngs)

if __name__ == '__main__':
    out = pathlib.Path(__file__).parent / 'node' / 'apps' / 'gui' / 'static'
    (out / 'occ.png').write_bytes(_create_png(256))
    (out / 'occ.ico').write_bytes(_create_ico())
    print(' [OK] Icons generated.')
