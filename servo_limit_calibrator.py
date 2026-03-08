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
from contextlib import contextmanager
from datetime import datetime, timezone
from typing import Dict, Iterator, Optional, Tuple

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


@contextmanager
def raw_stdin() -> Iterator[None]:
    if os.name == "nt":
        yield
        return

    import termios
    import tty

    fd = sys.stdin.fileno()
    old_settings = termios.tcgetattr(fd)
    try:
        tty.setcbreak(fd)
        yield
    finally:
        termios.tcsetattr(fd, termios.TCSADRAIN, old_settings)


def poll_key(timeout_s: float = 0.0) -> Optional[str]:
    if os.name == "nt":
        import msvcrt

        end = time.time() + timeout_s
        while time.time() < end:
            if msvcrt.kbhit():
                return getch()
            time.sleep(0.002)
        return getch() if msvcrt.kbhit() else None

    import select

    rlist, _, _ = select.select([sys.stdin], [], [], timeout_s)
    if rlist:
        return getch()
    return None


def jog_until_mark(
    bus: STSSerial,
    sid: int,
    start_pos: int,
    move_time_ms: int,
    speed: int,
    mark_key: str,
    mark_label: str,
) -> int:
    pos = start_pos
    step = 20

    print(f"Controls: LEFT/RIGHT to move, '+'/'-' step, '{mark_key}' mark {mark_label}, 'q' quit")
    print(f"Start pos={pos}, step={step}")

    while True:
        key = getch()
        if key in ("q", "Q"):
            raise KeyboardInterrupt("Calibration cancelled by user.")
        if key in (mark_key.lower(), mark_key.upper()):
            print(f"\nMarked {mark_label}: {pos}")
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


def autosweep_until_save(
    bus: STSSerial,
    sid: int,
    start_pos: int,
    move_time_ms: int,
    speed: int,
    direction: str,
    step: int,
    stall_delta: int,
    stall_cycles: int,
) -> int:
    if direction not in ("left", "right"):
        raise ValueError("direction must be 'left' or 'right'")

    pos = start_pos
    delta = -abs(step) if direction == "left" else abs(step)
    print(f"Auto-sweeping {direction.upper()}... press 's' to save end, 'q' to quit")
    stuck_count = 0

    with raw_stdin():
        while True:
            key = poll_key(0.01)
            if key in ("q", "Q"):
                raise KeyboardInterrupt("Calibration cancelled by user.")
            if key in ("s", "S"):
                pos = read_position(bus, sid, pos)
                print(f"\nSaved position: {pos}")
                return pos

            next_pos = max(0, min(4095, pos + delta))
            move_test(bus, sid, next_pos, move_time_ms, speed)
            time.sleep(max(0.03, move_time_ms / 1000.0 * 0.45))
            prev_pos = pos
            pos = read_position(bus, sid, next_pos)

            if abs(pos - prev_pos) <= stall_delta:
                stuck_count += 1
            else:
                stuck_count = 0

            if stuck_count >= stall_cycles:
                print(f"\nAuto-detected {direction.upper()} end at: {pos}")
                return pos

            print(f"\rPos={pos:<4}", end="", flush=True)


def run_auto_test(
    bus: STSSerial,
    sid: int,
    zero_pos: int,
    max_left: int,
    max_right: int,
    move_time_ms: int,
    speed: int,
    settle_s: float,
) -> None:
    sequence = [
        ("zero", zero_pos),
        ("max_left", max_left),
        ("max_right", max_right),
        ("zero", zero_pos),
    ]
    print("\nAuto-test (1 cycle):")
    for label, target in sequence:
        print(f"  Move -> {label:9s} target={target}")
        move_test(bus, sid, target, move_time_ms, speed)
        time.sleep(max(0.2, settle_s))
        pos = read_position(bus, sid, target)
        print(f"      readback={pos}")


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
    p.add_argument(
        "--mode",
        choices=("auto", "manual"),
        default="auto",
        help="Calibration mode: auto sweep or manual jog",
    )
    p.add_argument(
        "--sweep-step",
        type=int,
        default=18,
        help="Step size per auto-sweep update (raw position units)",
    )
    p.add_argument(
        "--stall-delta",
        type=int,
        default=2,
        help="Position delta considered 'not moving' for end-stop detection",
    )
    p.add_argument(
        "--stall-cycles",
        type=int,
        default=6,
        help="Consecutive stalled updates to auto-detect sweep end",
    )
    p.add_argument(
        "--zero-mode",
        choices=("manual", "current"),
        default="manual",
        help="manual: you set zero with keys; current: use immediate readback as zero",
    )
    p.add_argument("--return-time", type=int, default=700, help="Return-to-zero time (ms)")
    p.add_argument(
        "--auto-test",
        action="store_true",
        default=True,
        help="Run one auto-test sequence after saving calibration (default: on)",
    )
    p.add_argument(
        "--no-auto-test",
        action="store_false",
        dest="auto_test",
        help="Disable post-calibration auto-test",
    )
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
        print(f"Current position: {zero_pos}")

        if args.zero_mode == "manual":
            print("\nSet ZERO position now, then press 'z' to mark.")
            zero_pos = jog_until_mark(
                bus=bus,
                sid=args.servo_id,
                start_pos=zero_pos,
                move_time_ms=args.move_time,
                speed=args.speed,
                mark_key="z",
                mark_label="zero",
            )
        else:
            print(f"Using current position as zero: {zero_pos}")

        print("Press ENTER to start LEFT limit calibration...")
        input()

        print("\nMove to MAX LEFT and press 's' to save.")
        if args.mode == "auto":
            max_left = autosweep_until_save(
                bus,
                args.servo_id,
                zero_pos,
                args.move_time,
                args.speed,
                "left",
                args.sweep_step,
                args.stall_delta,
                args.stall_cycles,
            )
        else:
            max_left = jog_until_mark(
                bus=bus,
                sid=args.servo_id,
                start_pos=zero_pos,
                move_time_ms=args.move_time,
                speed=args.speed,
                mark_key="s",
                mark_label="max_left",
            )

        print(f"Returning to zero/start ({zero_pos})...")
        move_test(bus, args.servo_id, zero_pos, args.return_time, args.speed)
        time.sleep(max(0.3, args.return_time / 1000.0 + 0.1))

        print("\nPress ENTER to start RIGHT limit calibration...")
        input()

        print("Move to MAX RIGHT and press 's' to save.")
        if args.mode == "auto":
            max_right = autosweep_until_save(
                bus,
                args.servo_id,
                zero_pos,
                args.move_time,
                args.speed,
                "right",
                args.sweep_step,
                args.stall_delta,
                args.stall_cycles,
            )
        else:
            max_right = jog_until_mark(
                bus=bus,
                sid=args.servo_id,
                start_pos=zero_pos,
                move_time_ms=args.move_time,
                speed=args.speed,
                mark_key="s",
                mark_label="max_right",
            )

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

        if args.auto_test:
            run_auto_test(
                bus=bus,
                sid=args.servo_id,
                zero_pos=zero_pos,
                max_left=max_left,
                max_right=max_right,
                move_time_ms=max(args.return_time, 800),
                speed=args.speed,
                settle_s=1.1,
            )
        return 0
    except KeyboardInterrupt:
        print("\nStopped.")
        return 130
    finally:
        bus.close()


if __name__ == "__main__":
    raise SystemExit(main())
