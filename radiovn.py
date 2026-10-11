#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Radio VN: giao diện và điều khiển cho mpv trên muOS.

Python lo toàn bộ phần giao diện (vẽ bằng osd-overlay của mpv qua socket IPC)
và tự đọc nút bấm của máy, nên không cần mpv có Lua hay gptokeyb.
"""

import json
import math
import os
import re
import select
import socket
import struct
import subprocess
import sys
import time

try:
    import fcntl
except ImportError:  # chạy thử trên Windows
    fcntl = None

APP = os.environ.get("RADIOVN_DIR") or os.path.dirname(os.path.abspath(__file__))
STATIONS_FILE = os.path.join(APP, "kenh.m3u")
STATE_FILE = os.path.join(APP, ".radiovn-state")
SCREEN_SCRIPT = os.path.join(APP, "screen.sh")
SOCK_PATH = "/tmp/radiovn-mpv.sock"
MPV_BIN = os.environ.get("RADIOVN_MPV", "mpv")

MAX_RETRY = 5
RETRY_DELAY = 3.0
SWITCH_GAP = 0.8  # số giây tối thiểu giữa 2 lần mở luồng
MAX_RESTART = 3
ROWS = 9
ROW_H = 38
LIST_Y = 80
ANIM_DT = 0.12
REPEAT_DELAY = 0.35
REPEAT_DT = 0.11

# Màu dạng BGR của ASS
C = {
    "bg": "1F140E",
    "bar": "2B1D15",
    "card": "37271B",
    "card2": "4A3524",
    "sel": "634631",
    "accent": "2EA8FF",
    "text": "FFFFFF",
    "sub": "C8B8A6",
    "faint": "8A7666",
    "green": "7ADB4C",
    "yellow": "3CC8FF",
    "red": "6464FF",
    "black": "000000",
}
FONT = "Be Vietnam Pro"
FONT_B = "Be Vietnam Pro SemiBold"

_log_file = None


def log(*parts):
    global _log_file
    try:
        if _log_file is None:
            _log_file = open(os.path.join(APP, "radiovn-ui.log"), "w", encoding="utf-8")
        _log_file.write(time.strftime("%H:%M:%S ") + " ".join(str(p) for p in parts) + "\n")
        _log_file.flush()
    except OSError:
        pass


def now():
    return time.monotonic()


###########################################################################
# Tiện ích chữ


def ass_escape(s):
    s = s.replace("\\", "\\⁠")
    return s.replace("{", "\\{").replace("}", "\\}")


def est(s, size, caps=False):
    return len(s) * size * (0.66 if caps else 0.55)


def fit(s, size, width, caps=False):
    maxc = max(3, int(width / (size * (0.66 if caps else 0.55))))
    if len(s) <= maxc:
        return s
    return s[: maxc - 1].rstrip() + "…"


def split_name(name):
    m = re.match(r"^(.*?)\s+-\s+(.+)$", name)
    if m:
        return m.group(1), m.group(2)
    return name, None


def read_line(path):
    try:
        with open(path, "r") as f:
            return f.readline().strip()
    except OSError:
        return None


###########################################################################
# Vẽ: toạ độ nhân 4 với \p3 cho nét mịn


def P(x, y):
    return "%d %d" % (round(x * 4), round(y * 4))


def rect_path(x0, y0, x1, y1):
    return "m %s l %s %s %s" % (P(x0, y0), P(x1, y0), P(x1, y1), P(x0, y1))


def rrect_path(x0, y0, x1, y1, rad):
    rad = min(rad, (x1 - x0) / 2, (y1 - y0) / 2)
    k = rad * 0.4477
    return (
        "m %s l %s b %s %s %s l %s b %s %s %s l %s b %s %s %s l %s b %s %s %s"
        % (
            P(x0 + rad, y0),
            P(x1 - rad, y0),
            P(x1 - k, y0), P(x1, y0 + k), P(x1, y0 + rad),
            P(x1, y1 - rad),
            P(x1, y1 - k), P(x1 - k, y1), P(x1 - rad, y1),
            P(x0 + rad, y1),
            P(x0 + k, y1), P(x0, y1 - k), P(x0, y1 - rad),
            P(x0, y0 + rad),
            P(x0, y0 + k), P(x0 + k, y0), P(x0 + rad, y0),
        )
    )


def circle_path(cx, cy, rad):
    return rrect_path(cx - rad, cy - rad, cx + rad, cy + rad, rad)


def arc_path(cx, cy, R, w, a0, a1):
    """Cung tròn dày w; góc tính bằng độ, 0 = hướng lên, chiều kim đồng hồ."""
    steps = max(6, int(abs(a1 - a0) / 7))
    ro, ri = R + w / 2, R - w / 2
    pts = []
    for s in range(steps + 1):
        a = math.radians(a0 + (a1 - a0) * s / steps)
        pts.append(P(cx + ro * math.sin(a), cy - ro * math.cos(a)))
    for s in range(steps, -1, -1):
        a = math.radians(a0 + (a1 - a0) * s / steps)
        pts.append(P(cx + ri * math.sin(a), cy - ri * math.cos(a)))
    return "m %s l %s" % (pts[0], " ".join(pts[1:]))


def tri_path(x0, y0, x1, y1, x2, y2):
    return "m %s l %s %s" % (P(x0, y0), P(x1, y1), P(x2, y2))


class Canvas:
    """Gom các lệnh vẽ thành ASS cho osd-overlay."""

    def __init__(self):
        self.ev = []

    def shape(self, color, path, alpha="00"):
        self.ev.append(
            "{\\an7\\pos(0,0)\\bord0\\shad0\\blur0\\1c&H%s&\\1a&H%s&\\p3}%s{\\p0}" % (color, alpha, path)
        )

    def text(self, x, y, s, size, color, an=4, font=FONT, alpha="00"):
        self.ev.append(
            "{\\an%d\\pos(%d,%d)\\fn%s\\fs%d\\bord0\\shad0\\blur0\\q2\\1c&H%s&\\1a&H%s&}%s"
            % (an, round(x), round(y), font, size, color, alpha, s)
        )

    def data(self):
        return "\n".join(self.ev)


###########################################################################
# Nút bấm: đọc thẳng tay cầm thật trong /dev/input
# Mã nút lấy từ app RGPad (đã thử trên RG40XXV), gán theo CHỮ IN trên máy.

EV_KEY, EV_ABS = 1, 3
KEY_MAX = 0x2FF
ABS_HAT0X, ABS_HAT0Y = 0x10, 0x11
EVENT_FMT = "llHHi"
EVENT_SIZE = struct.calcsize(EVENT_FMT)

KEY_CODES = {
    304: "a",
    305: "b",
    307: "x",
    306: "y",
    308: "leftshoulder",
    309: "rightshoulder",
    314: "lefttrigger",
    315: "righttrigger",
    310: "back",
    311: "start",
    312: "guide",
    354: "guide",
    313: "leftstick",
    316: "rightstick",
    544: "dpup",
    545: "dpdown",
    546: "dpleft",
    547: "dpright",
}


def _eviocgbit(ev, size):
    return (2 << 30) | (size << 16) | (ord("E") << 8) | (0x20 + ev)


def _has_key(fd, code):
    try:
        bits = fcntl.ioctl(fd, _eviocgbit(EV_KEY, KEY_MAX // 8 + 1), bytes(KEY_MAX // 8 + 1))
    except OSError:
        return False
    return bool(bits[code // 8] & (1 << (code % 8)))


def find_gamepad():
    """Thiết bị đầu tiên có nút 304/305 là tay cầm thật (giống RGPad)."""
    forced = os.environ.get("RADIOVN_DEVICE", "").strip()
    if forced:
        return forced
    try:
        names = [n for n in os.listdir("/dev/input") if re.match(r"^event\d+$", n)]
    except OSError:
        return None
    for n in sorted(names, key=lambda x: int(x[5:])):
        path = "/dev/input/" + n
        try:
            fd = os.open(path, os.O_RDONLY | os.O_NONBLOCK)
        except OSError:
            continue
        try:
            if _has_key(fd, 304) or _has_key(fd, 305):
                return path
        finally:
            os.close(fd)
    return None


class Gamepad:
    def __init__(self):
        self.fd = None
        self.hat = [0, 0]
        self.held = set()
        if fcntl is None:
            return
        path = find_gamepad()
        log("tay cầm:", path)
        if not path:
            return
        try:
            self.fd = os.open(path, os.O_RDONLY | os.O_NONBLOCK)
        except OSError as e:
            log("không mở được", path, e)
            self.fd = None

    def read(self):
        """Trả về danh sách (tên nút, True nếu nhấn / False nếu nhả)."""
        out = []
        try:
            data = os.read(self.fd, EVENT_SIZE * 64)
        except OSError:
            return out
        for i in range(0, len(data) - EVENT_SIZE + 1, EVENT_SIZE):
            _, _, etype, code, value = struct.unpack(EVENT_FMT, data[i : i + EVENT_SIZE])
            if etype == EV_KEY and value in (0, 1):
                name = KEY_CODES.get(code)
                if name:
                    out.append((name, value == 1))
                elif value == 1:
                    log("nút chưa gán, mã", code)
            elif etype == EV_ABS and code in (ABS_HAT0X, ABS_HAT0Y):
                axis = 0 if code == ABS_HAT0X else 1
                old = self.hat[axis]
                new = (value > 0) - (value < 0)
                if old == new:
                    continue
                self.hat[axis] = new
                neg, pos = ("dpleft", "dpright") if axis == 0 else ("dpup", "dpdown")
                if old < 0:
                    out.append((neg, False))
                elif old > 0:
                    out.append((pos, False))
                if new < 0:
                    out.append((neg, True))
                elif new > 0:
                    out.append((pos, True))
        for name, down in out:
            if down:
                self.held.add(name)
            else:
                self.held.discard(name)
        return out


###########################################################################
# mpv qua socket IPC


def _die_with_parent():
    """Cho mpv tự tắt nếu radiovn.py bị muOS buộc thoát."""
    try:
        import ctypes

        ctypes.CDLL("libc.so.6").prctl(1, 9)  # PR_SET_PDEATHSIG = SIGKILL
    except Exception:
        pass


class Mpv:
    def __init__(self):
        self.proc = None
        self.sock = None
        self.buf = b""
        self.dead = True

    def start(self):
        try:
            os.unlink(SOCK_PATH)
        except OSError:
            pass
        args = [
            MPV_BIN,
            "--config-dir=" + os.path.join(APP, "mpv"),
            "--input-ipc-server=" + SOCK_PATH,
            "--idle=yes",
            "--force-window=yes",
            "--log-file=" + os.path.join(APP, "mpv.log"),
        ]
        log("chạy:", " ".join(args))
        try:
            err = open(os.path.join(APP, "mpv-stderr.log"), "w")
        except OSError:
            err = subprocess.DEVNULL
        self.proc = subprocess.Popen(
            args,
            stdin=subprocess.DEVNULL,
            stdout=err,
            stderr=err,
            preexec_fn=_die_with_parent if os.name == "posix" else None,
        )
        deadline = now() + 10
        while now() < deadline:
            if self.proc.poll() is not None:
                raise RuntimeError("mpv thoát ngay, mã %s" % self.proc.returncode)
            s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
            try:
                s.connect(SOCK_PATH)
            except OSError:
                s.close()
                time.sleep(0.1)
                continue
            s.settimeout(3.0)
            self.sock = s
            self.buf = b""
            self.dead = False
            return
        raise RuntimeError("không kết nối được tới mpv")

    def send(self, *cmd):
        self.send_obj({"command": list(cmd)})

    def send_obj(self, obj):
        if self.dead:
            return
        try:
            self.sock.sendall((json.dumps(obj) + "\n").encode("utf-8"))
        except OSError as e:
            log("gửi lỗi:", e)
            self.dead = True

    def read(self):
        try:
            chunk = self.sock.recv(65536)
        except socket.timeout:
            return []
        except OSError:
            chunk = b""
        if not chunk:
            self.dead = True
            return []
        self.buf += chunk
        out = []
        while b"\n" in self.buf:
            line, self.buf = self.buf.split(b"\n", 1)
            try:
                out.append(json.loads(line.decode("utf-8", "replace")))
            except ValueError:
                pass
        return out

    def alive(self):
        return not self.dead and self.proc is not None and self.proc.poll() is None

    def stop(self):
        if self.proc and self.proc.poll() is None:
            self.send("quit")
            try:
                self.proc.wait(timeout=3)
            except subprocess.TimeoutExpired:
                self.proc.kill()
        if self.sock:
            try:
                self.sock.close()
            except OSError:
                pass
        self.dead = True


###########################################################################
# Ứng dụng


class App:
    def __init__(self):
        self.stations = []
        self.cursor = 0
        self.top = 0
        self.target = None  # kênh người dùng chọn nghe (chỉ số từ 0)
        self.loaded = None  # kênh mpv đang mở thật sự
        self.want_play = False
        self.status = "idle"  # idle | connecting | buffering | playing | stopped | retry | error
        self.retries = 0
        self.retry_at = None
        self.load_at = None
        self.loaded_at = -100.0
        self.connect_started = 0.0
        self.song = None
        self.volume = 80.0
        self.screen_off = False
        self.clock = ""
        self.wifi_ok = None
        self.battery = None
        self.battery_path = None
        self.osd_w, self.osd_h = 640, 480
        self.dirty = True
        self.running = True
        self.restarts = 0
        self.next_tick = 0.0
        self.tick = 0
        self.next_anim = 0.0
        self.repeat_btn = None
        self.repeat_at = 0.0
        self.mpv = Mpv()
        self.pad = None
        self.failed = False

    # ---- dữ liệu ----

    def load_stations(self):
        try:
            with open(STATIONS_FILE, "r", encoding="utf-8-sig") as f:
                lines = f.read().splitlines()
        except OSError as e:
            log("không đọc được kenh.m3u:", e)
            return
        title = None
        for line in lines:
            line = line.strip()
            if line.startswith("#EXTINF"):
                title = line.split(",", 1)[1].strip() if "," in line else None
            elif line and not line.startswith("#"):
                name = title or line
                main, desc = split_name(name)
                self.stations.append({"name": name, "main": main, "desc": desc, "url": line})
                title = None

    def load_state(self):
        last = None
        try:
            with open(STATE_FILE, "r") as f:
                for line in f:
                    k, _, v = line.strip().partition("=")
                    if k == "kenh" and v.isdigit():
                        last = int(v) - 1
                    elif k == "amluong":
                        try:
                            self.volume = float(v)
                        except ValueError:
                            pass
        except OSError:
            pass
        return last

    def save_state(self):
        try:
            with open(STATE_FILE, "w") as f:
                idx = self.target if self.target is not None else self.cursor
                f.write("kenh=%d\namluong=%d\n" % (idx + 1, round(self.volume)))
        except OSError:
            pass

    def check_wifi(self):
        for n in ("wlan0", "wlan1", "wlan2"):
            if read_line("/sys/class/net/%s/operstate" % n) in ("up", "dormant"):
                return True
        return False

    def check_battery(self):
        if self.battery_path is None:
            self.battery_path = False
            base = "/sys/class/power_supply"
            try:
                for d in sorted(os.listdir(base)):
                    p = os.path.join(base, d, "capacity")
                    if "usb" not in d.lower() and os.path.exists(p):
                        self.battery_path = p
                        break
            except OSError:
                pass
        if self.battery_path:
            v = read_line(self.battery_path)
            if v and v.isdigit():
                return int(v)
        return None

    # ---- vẽ ----

    def broadcast_icon(self, c, cx, cy, s, color):
        c.shape(color, circle_path(cx, cy, 4 * s))
        c.shape(color, arc_path(cx, cy, 10 * s, 3 * s, 45, 135) + " " + arc_path(cx, cy, 10 * s, 3 * s, 225, 315))
        c.shape(color, arc_path(cx, cy, 17 * s, 3 * s, 50, 130) + " " + arc_path(cx, cy, 17 * s, 3 * s, 230, 310))

    def spinner(self, c, cx, cy, R, w, t, color):
        a = (t * 300) % 360
        c.shape(color, arc_path(cx, cy, R, w, a, a + 100))

    def eq_bars(self, c, cx, cy, n, bw, gap, hmin, hmax, t, color):
        total = n * bw + (n - 1) * gap
        x = cx - total / 2
        paths = []
        for i in range(1, n + 1):
            v = abs(math.sin(t * (2.1 + i * 0.7) + i * 1.3))
            h = hmin + (hmax - hmin) * v
            paths.append(rrect_path(x, cy - h / 2, x + bw, cy + h / 2, bw / 2))
            x += bw + gap
        c.shape(color, " ".join(paths))

    def pill(self, c, cx, cy, label, color):
        w = est(label, 12, True) + 28
        c.shape(color, rrect_path(cx - w / 2, cy - 13, cx + w / 2, cy + 13, 13), "C0")
        c.text(cx, cy, label, 12, color, an=5, font=FONT_B)

    def draw_header(self, c, w):
        c.shape(C["bar"], rect_path(0, 0, w, 52))
        c.shape(C["accent"], circle_path(30, 26, 18))
        self.broadcast_icon(c, 30, 26, 0.72, C["bar"])
        c.text(58, 19, "Radio VN", 22, C["text"], font=FONT_B)
        c.text(58, 39, "Đài phát thanh Việt Nam", 12, C["sub"])

        bx = w - 44
        if self.battery is not None:
            b = self.battery
            bc = C["red"] if b <= 15 else (C["yellow"] if b <= 30 else C["green"])
            c.shape(C["sub"], rrect_path(bx, 19, bx + 26, 33, 3))
            c.shape(C["bar"], rrect_path(bx + 2, 21, bx + 24, 31, 2))
            c.shape(C["sub"], rect_path(bx + 26, 23, bx + 29, 29))
            fw = 20 * max(0, min(100, b)) / 100
            if fw > 0.5:
                c.shape(bc, rect_path(bx + 3, 22, bx + 3 + fw, 30))
            c.text(bx - 6, 26, "%d%%" % b, 14, C["sub"], an=6)
            bx = bx - 6 - est("%d%%" % b, 14) - 16
        c.text(bx, 26, self.clock, 17, C["text"], an=6, font=FONT_B)
        bx = bx - est(self.clock, 17) - 18
        wc = C["green"] if self.wifi_ok else C["faint"]
        for i in range(4):
            h = 4 + i * 3
            c.shape(wc, rrect_path(bx - 24 + i * 6, 33 - h, bx - 20 + i * 6, 33, 1))
        if self.wifi_ok is False:
            c.shape(C["red"], tri_path(bx - 27, 18, bx - 25, 18, bx - 1, 36) + " " + tri_path(bx - 27, 18, bx - 1, 36, bx - 3, 36))

    def row_indicator(self, c, x, y, t):
        st = self.status
        if st == "playing":
            self.eq_bars(c, x, y, 3, 3, 3, 4, 15, t, C["green"])
        elif st in ("connecting", "buffering", "retry"):
            self.spinner(c, x, y, 7, 2.5, t, C["accent"])
        elif st == "error":
            c.shape(C["red"], circle_path(x, y, 5))
        else:
            c.shape(C["faint"], rect_path(x - 5, y - 6, x - 2, y + 6) + " " + rect_path(x + 2, y - 6, x + 5, y + 6))

    def draw_list(self, c, t):
        x0, x1 = 12, 372
        c.text(x0 + 4, 66, "DANH SÁCH KÊNH", 11, C["faint"], font=FONT_B)
        c.text(x1 - 2, 66, "%d kênh" % len(self.stations), 11, C["faint"], an=6)
        if not self.stations:
            c.text(x0 + 4, LIST_Y + 24, "Không đọc được file kenh.m3u", 16, C["red"])
            return

        for i in range(self.top, min(len(self.stations), self.top + ROWS)):
            s = self.stations[i]
            y = LIST_Y + (i - self.top) * ROW_H
            cy = y + ROW_H / 2
            is_cur = i == self.cursor
            is_on = i == self.target and (self.want_play or self.status == "error")
            err = self.status == "error"

            if is_cur:
                c.shape(C["sel"], rrect_path(x0, y + 2, x1, y + ROW_H - 2, 9))
            elif is_on:
                c.shape(C["card"], rrect_path(x0, y + 2, x1, y + ROW_H - 2, 9))
            if is_on:
                c.shape(C["red"] if err else C["green"], rrect_path(x0, y + 8, x0 + 4, y + ROW_H - 8, 2))

            c.text(x0 + 24, cy, "%02d" % (i + 1), 13, C["sub"] if is_cur else C["faint"], an=5, font=FONT_B)

            if is_on:
                color = C["red"] if err else C["green"]
            else:
                color = C["text"] if is_cur else C["sub"]
            width = 220 if is_on else 250
            main = fit(s["main"], 17, width)
            line = ass_escape(main)
            if s["desc"]:
                room = width - est(main, 17) - 10
                if room > 40:
                    line += "{\\fs13\\1c&H%s&\\fn%s}  %s" % (C["faint"], FONT, ass_escape(fit(s["desc"], 13, room)))
            c.text(x0 + 44, cy, line, 17, color, font=FONT_B if (is_cur or is_on) else FONT)

            if is_on:
                self.row_indicator(c, x1 - 22, cy, t)

        if len(self.stations) > ROWS:
            y0, y1 = LIST_Y + 4, LIST_Y + ROWS * ROW_H - 4
            ln = y1 - y0
            th = max(24, ln * ROWS / len(self.stations))
            pos = y0 + (ln - th) * self.top / (len(self.stations) - ROWS)
            c.shape(C["card"], rrect_path(x1 + 3, y0, x1 + 6, y1, 1.5))
            c.shape(C["faint"], rrect_path(x1 + 3, pos, x1 + 6, pos + th, 1.5))

    def status_info(self, t):
        st = self.status
        if self.target is None:
            return "CHƯA CHỌN KÊNH", C["faint"], "Chọn kênh rồi bấm A để nghe"
        if st == "connecting":
            return "ĐANG KẾT NỐI  %ds" % int(t - self.connect_started), C["yellow"], "Vui lòng chờ một chút..."
        if st == "buffering":
            return "ĐANG TẢI", C["yellow"], "Mạng chậm, đang tải thêm..."
        if st == "playing":
            return "ĐANG PHÁT", C["green"], self.song
        if st == "stopped":
            return "ĐÃ DỪNG", C["faint"], "Bấm X để nghe tiếp"
        if st == "retry":
            why = "MẤT WIFI" if self.wifi_ok is False else "MẤT KẾT NỐI"
            return "%s · THỬ LẠI %d/%d" % (why, self.retries, MAX_RETRY), C["yellow"], "Đang kết nối lại..."
        if st == "error":
            if self.wifi_ok is False:
                return "CHƯA CÓ WIFI", C["red"], "Kết nối WiFi rồi bấm A"
            return "KHÔNG PHÁT ĐƯỢC", C["red"], "Bấm A để thử lại"
        return "", C["faint"], None

    def draw_card(self, c, w, t):
        x0, x1, y0, y1 = 384, w - 12, 60, 422
        cx = (x0 + x1) / 2
        c.shape(C["card"], rrect_path(x0, y0, x1, y1, 16))

        dy, R = 156, 60
        st = self.status
        loading = st in ("connecting", "buffering", "retry")
        if st == "playing":
            for k in (0, 1):
                p = (t * 0.55 + k * 0.5) % 1
                a = 0x50 + int(p * 0xAF)
                c.shape(C["green"], arc_path(cx, dy, R + 6 + p * 18, 2, 0, 360), "%02X" % a)
        c.shape(C["card2"], circle_path(cx, dy, R))
        ring = C["faint"]
        if st == "playing":
            ring = C["green"]
        elif st == "error":
            ring = C["red"]
        elif loading:
            ring = C["card2"]
        c.shape(ring, arc_path(cx, dy, R - 3, 5, 0, 360), "00" if loading else "40")
        if loading:
            self.spinner(c, cx, dy, R - 3, 5, t, C["accent"])
        if st == "playing":
            self.eq_bars(c, cx, dy, 5, 8, 6, 10, 46, t, C["green"])
        else:
            self.broadcast_icon(c, cx, dy, 1.5, C["text"] if self.target is not None else C["faint"])

        s = self.stations[self.target] if self.target is not None else None
        main = s["main"] if s else "Radio VN"
        desc = (s["desc"] or "") if s else "Chưa chọn kênh"
        c.text(cx, 248, ass_escape(fit(main, 22, x1 - x0 - 24)), 22, C["text"], an=5, font=FONT_B)
        if desc:
            c.text(cx, 274, ass_escape(fit(desc, 14, x1 - x0 - 24)), 14, C["sub"], an=5)
        label, color, extra = self.status_info(t)
        if label:
            self.pill(c, cx, 308, label, color)
        if extra:
            c.text(cx, 340, ass_escape(fit(extra, 13, x1 - x0 - 28)), 13, C["sub"], an=5)

        vy, sx = 396, x0 + 18
        c.shape(
            C["sub"],
            rect_path(sx, vy - 3, sx + 10, vy + 3) + " " + tri_path(sx + 4, vy - 3, sx + 10, vy - 8, sx + 10, vy + 8)
            + " " + tri_path(sx + 4, vy + 3, sx + 10, vy - 8, sx + 10, vy + 8),
        )
        bx0, bx1 = sx + 18, x1 - 52
        c.shape(C["card2"], rrect_path(bx0, vy - 3, bx1, vy + 3, 3))
        fw = (bx1 - bx0) * max(0, min(100, self.volume)) / 100
        if fw > 3:
            c.shape(C["accent"], rrect_path(bx0, vy - 3, bx0 + fw, vy + 3, 3))
        c.text(x1 - 16, vy, "%d%%" % round(self.volume), 13, C["sub"], an=6, font=FONT_B)

    def draw_footer(self, c, w, h):
        c.shape(C["bar"], rect_path(0, 430, w, h))
        items = [("A", "Nghe"), ("X", "Dừng/Phát"), ("LR", "Âm lượng"), ("Y", "Tắt màn"), ("MENU + START", "Thoát")]
        gap = 18
        sizes = []
        for key, label in items:
            bw = 32 if key == "LR" else max(22, est(key, 11, True) + 12)
            sizes.append((bw, bw + 6 + est(label, 14)))
        total = sum(s[1] for s in sizes) + gap * (len(items) - 1)
        x, y = (w - total) / 2, 455
        for (key, label), (bw, iw) in zip(items, sizes):
            c.shape(C["card2"], rrect_path(x, y - 11, x + bw, y + 11, 11))
            if key == "LR":
                m = x + bw / 2
                c.shape(C["text"], tri_path(m - 3, y - 5, m - 3, y + 5, m - 10, y) + " " + tri_path(m + 3, y - 5, m + 10, y, m + 3, y + 5))
            else:
                c.text(x + bw / 2, y, key, 11, C["text"], an=5, font=FONT_B)
            c.text(x + bw + 6, y, label, 14, C["sub"])
            x += iw + gap

    def draw(self, c, t):
        w = int(round(480 * self.osd_w / self.osd_h)) if self.osd_h > 0 else 640
        h = 480
        if self.screen_off:
            c.shape(C["black"], rect_path(0, 0, w, h))
        else:
            c.shape(C["bg"], rect_path(0, 0, w, h))
            self.draw_header(c, w)
            self.draw_list(c, t)
            self.draw_card(c, w, t)
            self.draw_footer(c, w, h)
        return w, h

    def render(self):
        c = Canvas()
        try:
            w, h = self.draw(c, now())
        except Exception as e:  # không để lỗi vẽ làm sập app
            log("lỗi vẽ:", repr(e))
            return
        self.mpv.send_obj(
            {"command": {"name": "osd-overlay", "id": 1, "format": "ass-events", "data": c.data(), "res_x": w, "res_y": h, "z": 0}}
        )
        self.dirty = False

    # ---- phát ----

    def anim_needed(self):
        return not self.screen_off and self.want_play and self.status not in ("error", "stopped")

    def ensure_visible(self):
        if self.cursor < self.top:
            self.top = self.cursor
        elif self.cursor > self.top + ROWS - 1:
            self.top = self.cursor - ROWS + 1
        self.top = max(0, min(self.top, max(0, len(self.stations) - ROWS)))

    def do_load(self):
        self.load_at = None
        if not self.want_play or self.target is None:
            return
        self.loaded = self.target
        self.loaded_at = now()
        log("mở kênh", self.target + 1, self.stations[self.target]["url"])
        self.mpv.send("loadfile", self.stations[self.target]["url"], "replace")

    def schedule_load(self):
        """Mở luồng nhưng không quá 1 lần mỗi SWITCH_GAP giây; lần chờ luôn lấy kênh mới nhất."""
        if self.load_at is not None:
            return
        wait = SWITCH_GAP - (now() - self.loaded_at)
        if wait <= 0:
            self.do_load()
        else:
            self.load_at = now() + wait

    def play(self, i):
        if i is None or not (0 <= i < len(self.stations)):
            return
        if i == self.target and self.want_play and self.status != "error":
            return  # đang phát hoặc đang kết nối kênh này rồi
        self.retry_at = None
        self.target = i
        self.want_play = True
        self.retries = 0
        self.song = None
        self.status = "connecting"
        self.connect_started = now()
        self.schedule_load()
        self.save_state()
        self.dirty = True

    def stop(self):
        self.retry_at = None
        self.load_at = None
        self.want_play = False
        self.status = "stopped"
        self.song = None
        self.loaded = None
        self.mpv.send("stop")
        self.dirty = True

    def toggle(self):
        if self.want_play:
            self.stop()
        else:
            self.play(self.target if self.target is not None else self.cursor)

    def move(self, d):
        if self.stations:
            self.cursor = (self.cursor + d) % len(self.stations)
            self.ensure_visible()
            self.dirty = True

    def page(self, d):
        if self.stations:
            self.cursor = max(0, min(len(self.stations) - 1, self.cursor + d * ROWS))
            self.ensure_visible()
            self.dirty = True

    def goto_playing(self):
        if self.target is not None:
            self.cursor = self.target
            self.ensure_visible()
            self.dirty = True

    def change_volume(self, d):
        self.mpv.send("add", "volume", d)

    def set_screen(self, on):
        self.screen_off = not on
        try:
            subprocess.call(["sh", SCREEN_SCRIPT, "on" if on else "off"])
        except OSError:
            pass
        self.dirty = True

    def quit(self):
        self.running = False

    def schedule_retry(self):
        if not self.want_play:
            return
        if self.retries >= MAX_RETRY:
            self.status = "error"
            self.want_play = False
            self.dirty = True
            return
        self.retries += 1
        self.status = "retry"
        self.retry_at = now() + RETRY_DELAY
        self.dirty = True

    # ---- sự kiện mpv ----

    def mpv_init(self):
        self.mpv.send("set_property", "osd-msg1", "")
        self.mpv.send("set_property", "loop-playlist", "no")
        self.mpv.send("set_property", "volume", self.volume)
        self.mpv.send("observe_property", 1, "volume")
        self.mpv.send("observe_property", 2, "metadata")
        self.mpv.send("observe_property", 3, "paused-for-cache")
        self.mpv.send("observe_property", 4, "osd-dimensions")

    def on_mpv(self, ev):
        name = ev.get("event")
        if name == "playback-restart":
            if self.want_play and self.loaded == self.target:
                self.status = "playing"
                self.retries = 0
                self.dirty = True
        elif name == "end-file":
            reason = ev.get("reason", "")
            log("end-file", reason, ev.get("file_error", ""))
            if not self.want_play or self.loaded != self.target or self.load_at is not None:
                return
            if reason in ("stop", "quit", "redirect"):
                return
            self.schedule_retry()
        elif name == "property-change":
            prop, data = ev.get("name"), ev.get("data")
            if prop == "volume" and isinstance(data, (int, float)):
                self.volume = float(data)
            elif prop == "metadata":
                song = None
                if isinstance(data, dict):
                    for k, v in data.items():
                        if str(k).lower() in ("icy-title", "streamtitle"):
                            song = str(v).strip() or None
                self.song = song
            elif prop == "paused-for-cache":
                if self.want_play and self.loaded == self.target:
                    if data and self.status == "playing":
                        self.status = "buffering"
                    elif not data and self.status == "buffering":
                        self.status = "playing"
            elif prop == "osd-dimensions" and isinstance(data, dict):
                if data.get("w") and data.get("h"):
                    self.osd_w, self.osd_h = data["w"], data["h"]
            self.dirty = True

    # ---- nút bấm ----

    REPEATABLE = ("dpup", "dpdown", "dpleft", "dpright", "leftshoulder", "rightshoulder")

    def on_button(self, name, held):
        if name == "start" and "guide" in held:
            self.quit()
            return
        if self.screen_off and name not in ("dpleft", "dpright"):
            self.set_screen(True)
            return
        action = {
            "dpup": lambda: self.move(-1),
            "dpdown": lambda: self.move(1),
            "leftshoulder": lambda: self.page(-1),
            "rightshoulder": lambda: self.page(1),
            "a": lambda: self.play(self.cursor),
            "b": self.goto_playing,
            "x": self.toggle,
            "y": lambda: self.set_screen(False),
            "dpleft": lambda: self.change_volume(-5),
            "dpright": lambda: self.change_volume(5),
        }.get(name)
        if action:
            action()

    # ---- vòng lặp chính ----

    def refresh_status(self, force=False):
        clk = time.strftime("%H:%M")
        if clk != self.clock:
            self.clock = clk
            self.dirty = True
        if force or self.tick % 3 == 0:
            w = self.check_wifi()
            if w != self.wifi_ok:
                self.wifi_ok = w
                self.dirty = True
        if force or self.tick % 30 == 0:
            b = self.check_battery()
            if b != self.battery:
                self.battery = b
                self.dirty = True
        if self.status == "connecting":
            self.dirty = True
        self.tick += 1

    def start_mpv(self):
        self.mpv.start()
        self.mpv_init()
        self.dirty = True
        if self.want_play and self.target is not None:
            self.loaded_at = -100.0
            self.load_at = None
            self.status = "connecting"
            self.connect_started = now()
            self.schedule_load()

    def run(self):
        self.load_stations()
        last = self.load_state()
        try:
            self.pad = Gamepad()
        except Exception as e:  # lỗi đọc nút không được làm sập app
            log("lỗi khởi tạo nút bấm:", repr(e))
            self.pad = None
        self.start_mpv()
        self.refresh_status(True)
        if last is not None and 0 <= last < len(self.stations):
            self.cursor = last
            self.ensure_visible()
            self.play(last)

        while self.running:
            t = now()
            deadlines = [self.next_tick]
            if self.anim_needed():
                deadlines.append(self.next_anim)
            for d in (self.load_at, self.retry_at):
                if d is not None:
                    deadlines.append(d)
            if self.repeat_btn:
                deadlines.append(self.repeat_at)
            timeout = 0 if self.dirty else max(0.0, min(deadlines) - t)

            fds = [self.mpv.sock]
            if self.pad and self.pad.fd is not None:
                fds.append(self.pad.fd)
            try:
                ready, _, _ = select.select(fds, [], [], timeout)
            except (OSError, ValueError):
                ready = []

            if self.mpv.sock in ready:
                for ev in self.mpv.read():
                    self.on_mpv(ev)
            if self.pad and self.pad.fd in ready:
                for name, down in self.pad.read():
                    if down:
                        self.on_button(name, self.pad.held)
                        if name in self.REPEATABLE:
                            self.repeat_btn = name
                            self.repeat_at = now() + REPEAT_DELAY
                    elif name == self.repeat_btn:
                        self.repeat_btn = None

            t = now()
            if self.repeat_btn and t >= self.repeat_at:
                if self.repeat_btn in self.pad.held:
                    self.on_button(self.repeat_btn, self.pad.held)
                    self.repeat_at = t + REPEAT_DT
                else:
                    self.repeat_btn = None
            if self.load_at is not None and t >= self.load_at:
                self.do_load()
            if self.retry_at is not None and t >= self.retry_at:
                self.retry_at = None
                if self.want_play:
                    self.status = "connecting"
                    self.connect_started = t
                    self.schedule_load()
                    self.dirty = True
            if t >= self.next_tick:
                self.refresh_status()
                self.next_tick = t + 1.0
            if self.anim_needed() and t >= self.next_anim:
                self.dirty = True
                self.next_anim = t + ANIM_DT

            if not self.running:
                break

            if not self.mpv.alive():
                code = self.mpv.proc.poll() if self.mpv.proc else None
                log("mpv dừng bất thường, mã", code)
                self.restarts += 1
                if self.restarts > MAX_RESTART:
                    log("mpv lỗi quá nhiều lần, thoát")
                    self.failed = True
                    break
                time.sleep(1)
                try:
                    self.mpv.stop()
                    self.start_mpv()
                except RuntimeError as e:
                    log("mở lại mpv lỗi:", e)
                    self.failed = True
                    break
                continue

            if self.dirty:
                self.render()

        self.save_state()
        if self.screen_off:
            self.set_screen(True)
        self.mpv.stop()


def main():
    log("python", sys.version.split()[0], "| APP =", APP, "| mpv =", MPV_BIN)
    app = App()
    try:
        app.run()
    except Exception as e:
        log("lỗi:", repr(e))
        import traceback

        log(traceback.format_exc())
        try:
            app.mpv.stop()
        except Exception:
            pass
        return 1
    return 2 if app.failed else 0


if __name__ == "__main__":
    sys.exit(main())
