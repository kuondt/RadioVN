# Xem trước giao diện Radio VN trên máy tính: xuất các trạng thái ra file SVG
# Chạy: python tools/preview.py  -> tạo tools/preview/*.svg
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
import radiovn  # noqa: E402

OUT = os.path.join(HERE, "preview")
FONTS = "/mpv/fonts"


def bgr(c):
    return "#" + c[4:6] + c[2:4] + c[0:2]


def opacity(a):
    return 1 - int(a, 16) / 255


def ass_path_to_svg(path):
    toks = path.split()
    out, i, cmd = [], 0, None
    while i < len(toks):
        t = toks[i]
        if t in ("m", "l", "b"):
            cmd = t
            out.append({"m": "M", "l": "L", "b": "C"}[t])
            i += 1
            continue
        x, y = int(toks[i]) / 4, int(toks[i + 1]) / 4
        out.append("%.2f %.2f" % (x, y))
        i += 2
    return " ".join(out)


class SvgCanvas:
    def __init__(self):
        self.ev = []

    def shape(self, color, path, alpha="00"):
        self.ev.append(
            '<path d="%s" fill="%s" fill-opacity="%.3f"/>' % (ass_path_to_svg(path), bgr(color), opacity(alpha))
        )

    def text(self, x, y, s, size, color, an=4, font=radiovn.FONT, alpha="00"):
        anchor = {1: "start", 4: "start", 7: "start", 2: "middle", 5: "middle", 8: "middle"}.get(an, "end")
        weight = "600" if "SemiBold" in font else "400"
        parts = re.split(r"(\{[^}]*\})", s)
        spans = []
        cur_size, cur_color, cur_weight = size, color, weight
        for p in parts:
            if p.startswith("{") and p.endswith("}"):
                m = re.search(r"\\fs(\d+)", p)
                if m:
                    cur_size = int(m.group(1))
                m = re.search(r"\\1c&H([0-9A-Fa-f]{6})&", p)
                if m:
                    cur_color = m.group(1)
                m = re.search(r"\\fn([^\\}]+)", p)
                if m:
                    cur_weight = "600" if "SemiBold" in m.group(1) else "400"
                continue
            if not p:
                continue
            p = p.replace("\u2060", "").replace("&", "&amp;").replace("<", "&lt;").replace("\\{", "{").replace("\\}", "}")
            spans.append(
                '<tspan font-size="%d" fill="%s" font-weight="%s">%s</tspan>' % (cur_size, bgr(cur_color), cur_weight, p)
            )
        self.ev.append(
            '<text x="%d" y="%d" text-anchor="%s" dominant-baseline="central" font-family="BVP" xml:space="preserve">%s</text>'
            % (round(x), round(y), anchor, "".join(spans))
        )

    def svg(self, w, h):
        return (
            '<svg xmlns="http://www.w3.org/2000/svg" width="%d" height="%d" viewBox="0 0 %d %d">'
            "<style>@font-face{font-family:BVP;src:url('%s/BeVietnamPro-Regular.ttf');font-weight:400}"
            "@font-face{font-family:BVP;src:url('%s/BeVietnamPro-SemiBold.ttf');font-weight:600}</style>%s</svg>"
            % (w, h, w, h, FONTS, FONTS, "".join(self.ev))
        )


def snapshot(app, name, t=12.3):
    c = SvgCanvas()
    w, h = app.draw(c, t)
    os.makedirs(OUT, exist_ok=True)
    with open(os.path.join(OUT, name + ".svg"), "w", encoding="utf-8") as f:
        f.write(c.svg(w, h))


def main():
    radiovn.log = lambda *a: None
    app = radiovn.App()
    radiovn.STATIONS_FILE = os.path.join(os.path.dirname(HERE), "kenh.m3u")
    app.load_stations()
    app.clock, app.wifi_ok, app.battery, app.volume = "21:05", True, 76, 80

    snapshot(app, "1-chua-chon")

    app.cursor, app.target, app.want_play, app.status = 2, 2, True, "connecting"
    app.connect_started = 10.0
    snapshot(app, "2-dang-ket-noi")

    app.status = "playing"
    app.cursor = 5
    snapshot(app, "3-dang-phat")

    app.target, app.cursor, app.status, app.want_play = 7, 11, "playing", True
    app.ensure_visible()
    app.song = "Bản tin thời sự 21h"
    snapshot(app, "4-cuon-danh-sach")

    app.status, app.want_play, app.wifi_ok = "error", False, False
    snapshot(app, "5-loi")
    print("Đã xuất vào", OUT)


if __name__ == "__main__":
    main()
