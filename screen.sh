#!/bin/sh
# Tắt/bật đèn màn hình: sh screen.sh off | on

SAVE="/tmp/radiovn-brightness"

case "$1" in
	off)
		for DIR in /sys/class/backlight/*; do
			[ -f "$DIR/brightness" ] || continue
			NAME="${DIR##*/}"
			[ -f "$SAVE.$NAME" ] || cat "$DIR/brightness" >"$SAVE.$NAME"
			echo 0 >"$DIR/brightness"
		done
		;;
	on)
		for DIR in /sys/class/backlight/*; do
			NAME="${DIR##*/}"
			[ -f "$SAVE.$NAME" ] || continue
			cat "$SAVE.$NAME" >"$DIR/brightness"
			rm -f "$SAVE.$NAME"
		done
		;;
esac
