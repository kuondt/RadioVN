#!/bin/sh
# HELP: Nghe radio Việt Nam (VOV, VOH...) qua WiFi
# ICON: radiovn
# GRID: Radio VN

. /opt/muos/script/var/func.sh

# Tìm thư mục app (muOS truyền vào $1, phòng hờ thì tự dò)
APP_DIR="${1:-}"
[ -f "$APP_DIR/kenh.m3u" ] || APP_DIR="$(cd "$(dirname "$0")" && pwd)"
[ -f "$APP_DIR/kenh.m3u" ] || APP_DIR="${MUOS_STORE_DIR:-/run/muos/storage}/application/RadioVN"
[ -f "$APP_DIR/kenh.m3u" ] || APP_DIR="/mnt/mmc/MUOS/application/RadioVN"

LOG="$APP_DIR/radiovn.log"
echo "Radio VN - $(date)" >"$LOG"
echo "APP_DIR=$APP_DIR" >>"$LOG"

MPV_BIN="$(command -v mpv 2>/dev/null)"
if [ -z "$MPV_BIN" ]; then
	echo "LỖI: không tìm thấy mpv trong muOS" >>"$LOG"
	exit 1
fi
PY_BIN="$(command -v python3 2>/dev/null || command -v python 2>/dev/null)"
echo "MPV=$MPV_BIN PYTHON=$PY_BIN" >>"$LOG"

# Môi trường chuẩn của muOS (bản mới có SETUP_APP, bản cũ thì tự làm)
FG_NAME="mpv"
[ -n "$PY_BIN" ] && FG_NAME="${PY_BIN##*/}"
if command -v SETUP_APP >/dev/null 2>&1; then
	SETUP_STAGE_OVERLAY
	SETUP_APP "$FG_NAME" ""
else
	echo app >/tmp/act_go
	command -v SETUP_SDL_ENVIRONMENT >/dev/null 2>&1 && SETUP_SDL_ENVIRONMENT
	SET_VAR "system" "foreground_process" "$FG_NAME"
fi

# Không cho máy tự ngủ / tự tắt tiếng khi đang nghe
command -v CAFFEINE >/dev/null 2>&1 && CAFFEINE on

# Font tiếng Việt cho giao diện
FC_FILE="/tmp/radiovn-fonts.conf"
cat >"$FC_FILE" <<EOF
<?xml version="1.0"?>
<!DOCTYPE fontconfig SYSTEM "fonts.dtd">
<fontconfig>
	<dir>$APP_DIR/mpv/fonts</dir>
	<cachedir>/tmp/radiovn-fontcache</cachedir>
	<include ignore_missing="yes">/etc/fonts/fonts.conf</include>
</fontconfig>
EOF
FONTCONFIG_FILE="$FC_FILE"
export FONTCONFIG_FILE

RADIOVN_DIR="$APP_DIR"
RADIOVN_MPV="$MPV_BIN"
export RADIOVN_DIR RADIOVN_MPV

cd "$APP_DIR" || exit 1

# Chế độ đơn giản: mpv tự phát danh sách kênh, gptokeyb nhận nút
RUN_SIMPLE() {
	echo "Chạy chế độ đơn giản: $1" >>"$LOG"
	ROM_MOUNT="$(GET_VAR "device" "storage/rom/mount" 2>/dev/null)"
	GPTK_BIN=""
	for G in \
		"$ROM_MOUNT/MUOS/PortMaster/gptokeyb2" \
		"/mnt/mmc/MUOS/PortMaster/gptokeyb2" \
		"/mnt/sdcard/MUOS/PortMaster/gptokeyb2" \
		"/opt/muos/share/emulator/gptokeyb/gptokeyb2"; do
		if [ -f "$G" ]; then
			GPTK_BIN="$G"
			break
		fi
	done
	GPTK_PID=""
	if [ -n "$GPTK_BIN" ]; then
		killall -q gptokeyb2 gptokeyb >/dev/null 2>&1
		"$GPTK_BIN" "mpv" -c "$APP_DIR/radiovn.gptk" >/dev/null 2>&1 &
		GPTK_PID=$!
	fi
	"$MPV_BIN" --config-dir="$APP_DIR/mpv" --log-file="$APP_DIR/mpv-simple.log" \
		--loop-playlist=inf --osd-msg1="$1"'  |  ${playlist-pos-1}/${playlist-count}  ${media-title}' \
		"$APP_DIR/kenh.m3u" >>"$LOG" 2>&1
	echo "mpv (đơn giản) thoát với mã $?" >>"$LOG"
	[ -n "$GPTK_PID" ] && kill "$GPTK_PID" >/dev/null 2>&1
}

if [ -n "$PY_BIN" ]; then
	# Giao diện đầy đủ: radiovn.py vẽ giao diện, đọc nút bấm và điều khiển mpv
	"$PY_BIN" "$APP_DIR/radiovn.py" >>"$LOG" 2>&1
	CODE=$?
	echo "radiovn.py thoát với mã $CODE" >>"$LOG"
	# Giao diện bị lỗi thì vẫn cho nghe radio ở chế độ đơn giản
	[ "$CODE" -ne 0 ] && RUN_SIMPLE "Giao diện lỗi (xem radiovn-ui.log)"
else
	RUN_SIMPLE "Không có Python"
fi

# Dọn dẹp
sh "$APP_DIR/screen.sh" on
command -v CAFFEINE >/dev/null 2>&1 && CAFFEINE off
