#!/usr/bin/env python3
"""Interactive single-servo limit calibration.

Workflow for M6:
1) Capture current position as zero/start.
2) Manually jog to max-left with keyboard, press 's' to save.
3) Return to zero/start automatically.
4) Manually jog to max-right with keyboard, press 's' to save.
5) Save zero/max_left/max_right to JSON.
"""

import argparse
import json
import os
import sys
import time
from datetime import datetime, timezone
from typing import Dict, Tuple

from sts3215_test import ADDR_PRESENT_POSITION_L, STSSerial, move_test, u16le


def read_position(bus: STSSerial, sid: int, fallback: int) -> int:
    raw = bus.read(sid, ADDR_PRESENT_POSITION_L, 2)
    if raw is None:
        return fallback
    return u16le(raw)


def getch() -> str:
    if os.name == "nt":
        import msvcrt

        ch = msvcrt.getch()
        if ch in (b"\x00", b"\xe0"):
            ch2 = msvcrt.getch()
            if ch2 == b"K":
                return "LEFT"
            if ch2 == b"M":
                return "RIGHT"
            return ""
        return ch.decode(errors="ignore")

    import termios
    import tty

    fd = sys.stdin.fileno()
    old_settings = termios.tcgetattr(fd)
    try:
        tty.setraw(fd)
        ch = sys.stdin.read(1)
        if ch == "\x1b":
            ch2 = sys.stdin.read(1)
            ch3 = sys.stdin.read(1)
            if ch2 == "[" and ch3 == "D":
                return "LEFT"
            if ch2 == "[" and ch3 == "C":
                return "RIGHT"
            return ""
        return ch
    finally:
        termios.tcsetattr(fd, termios.TCSADRAIN, old_settings)


def jog_until_save(
    bus: STSSerial,
    sid: int,
    start_pos: int,
    move_time_ms: int,
    speed: int,
) -> int:
    pos = start_pos
    step = 20

    print("Controls: LEFT/RIGHT to move, '+'/'-' step, 's' save, 'q' quit")
    print(f"Start pos={pos}, step={step}")

    while True:
        key = getch()
        if key in ("q", "Q"):
            raise KeyboardInterrupt("Calibration cancelled by user.")
        if key in ("s", "S"):
            print(f"\nSaved position: {pos}")
            return pos
        if key in ("+", "="):
            step = min(512, step * 2)
            print(f"\rStep={step:<4} Pos={pos:<4}", end="", flush=True)
            continue
        if key in ("-", "_"):
            step = max(1, step // 2)
            print(f"\rStep={step:<4} Pos={pos:<4}", end="", flush=True)
            continue

        moved = False
        if key in ("LEFT", "a", "A", "h", "H"):
            pos = max(0, pos - step)
            moved = True
        elif key in ("RIGHT", "d", "D", "l", "L"):
            pos = min(4095, pos + step)
            moved = True

        if moved:
            move_test(bus, sid, pos, move_time_ms, speed)
            time.sleep(max(0.03, move_time_ms / 1000.0 * 0.35))
            pos = read_position(bus, sid, pos)
            print(f"\rStep={step:<4} Pos={pos:<4}", end="", flush=True)


def write_calibration(
    output_path: str,
    servo_name: str,
    servo_id: int,
    zero_pos: int,
    max_left: int,
    max_right: int,
) -> None:
    data: Dict[str, dict] = {}
    if os.path.exists(output_path):
        try:
            with open(output_path, "r", encoding="utf-8") as f:
                loaded = json.load(f)
            if isinstance(loaded, dict):
                data = loaded
        except Exception:
            data = {}

    data[servo_name] = {
        "servo_id": servo_id,
        "zero_position": zero_pos,
        "max_left": max_left,
        "max_right": max_right,
        "updated_at_utc": datetime.now(timezone.utc).isoformat(),
    }

    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, sort_keys=True)
        f.write("\n")


def main() -> int:
    p = argparse.ArgumentParser(description="Interactive servo limit calibration")
    p.add_argument("--port", default="/dev/ttyAMA0", help="Serial port")
    p.add_argument("--baud", type=int, default=1_000_000, help="Baudrate")
    p.add_argument("--servo-id", type=int, default=6, help="Servo ID (M6 default)")
    p.add_argument("--servo-name", default="M6", help="Logical servo name")
    p.add_argument("--move-time", type=int, default=220, help="Jog move time (ms)")
    p.add_argument("--speed", type=int, default=0, help="Servo speed (0=max/default)")
    p.add_argument("--return-time", type=int, default=700, help="Return-to-zero time (ms)")
    p.add_argument(
        "--output",
        default="servo_calibration.json",
        help="Calibration JSON output path",
    )
    args = p.parse_args()

    try:
        bus = STSSerial(args.port, args.baud)
    except Exception as exc:
        print(f"Failed to open {args.port}: {exc}")
        return 2

    try:
        if not bus.ping(args.servo_id):
            print(f"Servo ID {args.servo_id} not responding on {args.port} @ {args.baud}")
            return 1

        zero_pos = read_position(bus, args.servo_id, 2048)
        print(f"Connected to {args.servo_name} (ID {args.servo_id})")
        print(f"Captured zero/start position: {zero_pos}")
        print("Press ENTER to start LEFT limit calibration...")
        input()

        print("\nMove to MAX LEFT and press 's' to save.")
        max_left = jog_until_save(bus, args.servo_id, zero_pos, args.move_time, args.speed)

        print(f"Returning to zero/start ({zero_pos})...")
        move_test(bus, args.servo_id, zero_pos, args.return_time, args.speed)
        time.sleep(max(0.3, args.return_time / 1000.0 + 0.1))

        print("\nPress ENTER to start RIGHT limit calibration...")
        input()

        print("Move to MAX RIGHT and press 's' to save.")
        max_right = jog_until_save(bus, args.servo_id, zero_pos, args.move_time, args.speed)

        print(f"\nReturning to zero/start ({zero_pos})...")
        move_test(bus, args.servo_id, zero_pos, args.return_time, args.speed)
        time.sleep(max(0.3, args.return_time / 1000.0 + 0.1))

        write_calibration(
            output_path=args.output,
            servo_name=args.servo_name,
            servo_id=args.servo_id,
            zero_pos=zero_pos,
            max_left=max_left,
            max_right=max_right,
        )

        print("\nCalibration saved:")
        print(f"  Servo: {args.servo_name} (ID {args.servo_id})")
        print(f"  zero_position: {zero_pos}")
        print(f"  max_left:      {max_left}")
        print(f"  max_right:     {max_right}")
        print(f"  file:          {args.output}")
        return 0
    except KeyboardInterrupt:
        print("\nStopped.")
        return 130
    finally:
        bus.close()


if __name__ == "__main__":
    raise SystemExit(main())
