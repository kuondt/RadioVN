# Vẽ icon Radio VN (PNG) bằng Python thuần, không cần thư viện ngoài
import math, zlib, struct, sys, os

def png(path, w, h, px):
    raw = b''.join(b'\x00' + bytes(px[y*w*4:(y+1)*w*4]) for y in range(h))
    def chunk(t, d): return struct.pack('>I', len(d)) + t + d + struct.pack('>I', zlib.crc32(t+d) & 0xffffffff)
    data = b'\x89PNG\r\n\x1a\n' + chunk(b'IHDR', struct.pack('>IIBBBBB', w, h, 8, 6, 0, 0, 0)) \
        + chunk(b'IDAT', zlib.compress(raw, 9)) + chunk(b'IEND', b'')
    os.makedirs(os.path.dirname(path), exist_ok=True)
    open(path, 'wb').write(data)

# Hình học trong hệ toạ độ 0..100
def sd_rrect(x, y, x0, y0, x1, y1, r):
    cx, cy = (x0+x1)/2, (y0+y1)/2; hw, hh = (x1-x0)/2 - r, (y1-y0)/2 - r
    dx, dy = abs(x-cx)-hw, abs(y-cy)-hh
    return math.hypot(max(dx,0), max(dy,0)) + min(max(dx,dy),0) - r
def sd_circle(x, y, cx, cy, r): return math.hypot(x-cx, y-cy) - r
def sd_seg(x, y, ax, ay, bx, by, r):
    px, py, vx, vy = x-ax, y-ay, bx-ax, by-ay
    t = max(0, min(1, (px*vx+py*vy)/(vx*vx+vy*vy)))
    return math.hypot(px-vx*t, py-vy*t) - r
def sd_arc(x, y, cx, cy, R, w, a0, a1):
    # cung tròn dày w, góc a0..a1 (độ, 0 = hướng phải, ngược chiều kim đồng hồ, trục y hướng xuống)
    ang = math.degrees(math.atan2(-(y-cy), x-cx)) % 360
    if a0 <= ang <= a1: return abs(math.hypot(x-cx, y-cy) - R) - w/2
    best = 1e9
    for a in (a0, a1):
        ex, ey = cx + R*math.cos(math.radians(a)), cy - R*math.sin(math.radians(a))
        best = min(best, math.hypot(x-ex, y-ey) - w/2)
    return best

def radio_glyph(x, y):
    # biểu tượng: thân radio + ăng-ten + loa + sóng
    d = min(
        abs(sd_rrect(x, y, 12, 40, 88, 90, 10)) - 3.5,         # viền thân
        sd_seg(x, y, 26, 40, 66, 14, 3.2),                     # ăng-ten
        sd_circle(x, y, 66, 14, 5),                            # đầu ăng-ten
        abs(sd_circle(x, y, 34, 65, 13)) - 3.5,                # loa
        sd_circle(x, y, 34, 65, 4),
        sd_seg(x, y, 58, 56, 76, 56, 3), sd_seg(x, y, 58, 65, 76, 65, 3), sd_seg(x, y, 58, 74, 76, 74, 3),
    )
    return d

def render(size, fn, ss=4):
    px = bytearray(size*size*4)
    for j in range(size):
        for i in range(size):
            acc = [0.0, 0.0, 0.0, 0.0]
            for sj in range(ss):
                for si in range(ss):
                    x = (i + (si+0.5)/ss) * 100/size; y = (j + (sj+0.5)/ss) * 100/size
                    c = fn(x, y)
                    if c:
                        r, g, b, a = c
                        acc[0] += r*a; acc[1] += g*a; acc[2] += b*a; acc[3] += a
            n = ss*ss; a = acc[3]/n
            k = (j*size+i)*4
            if a > 0:
                px[k:k+4] = bytes([int(acc[0]/acc[3]+.5), int(acc[1]/acc[3]+.5), int(acc[2]/acc[3]+.5), int(a*255+.5)])
    return px

def white_glyph(x, y):
    return (255, 255, 255, 1.0) if radio_glyph(x, y) <= 0 else None

def tile(focused):
    def f(x, y):
        if sd_rrect(x, y, 2, 2, 98, 98, 22) > 0: return None
        t = (x + y) / 200   # gradient cam -> đỏ
        c1, c2 = ((255, 176, 46), (240, 84, 60)) if focused else ((236, 150, 40), (205, 70, 55))
        bg = tuple(c1[k]*(1-t) + c2[k]*t for k in range(3))
        gx, gy = 50 + (x-50)/0.72, 52 + (y-52)/0.72   # thu nhỏ glyph vào giữa ô
        if radio_glyph(gx, gy) <= 0: return (255, 255, 255, 1.0)
        return bg + (1.0,)
    return f

out = sys.argv[1]
for sz, sub in ((24, 'glyph/radiovn.png'), (24, 'glyph/640x480/radiovn.png')):
    png(os.path.join(out, sub), sz, sz, render(sz, white_glyph))
for sz, sub, foc in ((96, 'grid/radiovn.png', False), (96, 'grid/radiovn_focused.png', True),
                     (96, 'grid/640x480/radiovn.png', False), (96, 'grid/640x480/radiovn_focused.png', True)):
    png(os.path.join(out, sub), sz, sz, render(sz, tile(foc)))
png(os.path.join(out, 'preview-256.png'), 256, 256, render(256, tile(True), ss=2))
print('ok')
