#!/usr/bin/env python3
"""Automatic servo motion test using saved calibration limits."""

import argparse
import json
import sys
import time
from typing import Dict, Tuple

from sts3215_test import ADDR_PRESENT_POSITION_L, STSSerial, move_test, u16le


def read_position(bus: STSSerial, sid: int, fallback: int) -> int:
    raw = bus.read(sid, ADDR_PRESENT_POSITION_L, 2)
    if raw is None:
        return fallback
    return u16le(raw)


def load_servo_calibration(path: str, servo_name: str) -> Tuple[int, int, int, int]:
    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)

    if servo_name not in data:
        raise KeyError(f"{servo_name} not found in {path}")

    item: Dict[str, int] = data[servo_name]
    sid = int(item["servo_id"])
    zero = int(item["zero_position"])
    left = int(item["max_left"])
    right = int(item["max_right"])
    return sid, zero, left, right


def main() -> int:
    p = argparse.ArgumentParser(description="Automatic test using calibrated positions")
    p.add_argument("--port", default="/dev/ttyAMA0", help="Serial port")
    p.add_argument("--baud", type=int, default=1_000_000, help="Baudrate")
    p.add_argument("--calibration", default="servo_calibration.json", help="Calibration file")
    p.add_argument("--servo-name", default="M6", help="Servo name key in calibration file")
    p.add_argument("--servo-id", type=int, default=None, help="Override servo ID")
    p.add_argument("--move-time", type=int, default=900, help="Move time in ms")
    p.add_argument("--speed", type=int, default=0, help="Servo speed")
    p.add_argument("--settle", type=float, default=1.2, help="Settle wait in seconds")
    p.add_argument("--cycles", type=int, default=2, help="Number of test cycles")
    args = p.parse_args()

    try:
        sid_cfg, zero, left, right = load_servo_calibration(args.calibration, args.servo_name)
    except Exception as exc:
        print(f"Failed to load calibration: {exc}")
        return 2

    sid = args.servo_id if args.servo_id is not None else sid_cfg
    sequence = [("zero", zero), ("max_left", left), ("max_right", right), ("zero", zero)]

    print(f"Servo: {args.servo_name} (ID {sid})")
    print(f"Sequence: zero={zero}, left={left}, right={right}, cycles={args.cycles}")

    try:
        bus = STSSerial(args.port, args.baud)
    except Exception as exc:
        print(f"Failed to open {args.port}: {exc}")
        return 2

    try:
        if not bus.ping(sid):
            print(f"Servo ID {sid} not responding on {args.port} @ {args.baud}")
            return 1

        for cycle in range(1, args.cycles + 1):
            print(f"\nCycle {cycle}/{args.cycles}")
            for label, target in sequence:
                print(f"  Move -> {label:9s} target={target}")
                move_test(bus, sid, target, args.move_time, args.speed)
                time.sleep(max(0.2, args.settle))
                pos = read_position(bus, sid, target)
                print(f"      readback={pos}")

        print("\nAuto test complete.")
        return 0
    finally:
        bus.close()


if __name__ == "__main__":
    sys.exit(main())

