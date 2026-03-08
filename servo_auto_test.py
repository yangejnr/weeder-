#!/usr/bin/env python3
"""Automatic servo motion test using saved calibration limits."""

import argparse
import json
import sys
import time
from typing import Dict, List, Tuple

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


def parse_servo_names(servo_name: str, servo_names: str) -> List[str]:
    if servo_names.strip():
        names = [n.strip() for n in servo_names.split(",") if n.strip()]
        if names:
            return names
    return [servo_name.strip()]


def main() -> int:
    p = argparse.ArgumentParser(description="Automatic test using calibrated positions")
    p.add_argument("--port", default="/dev/ttyAMA0", help="Serial port")
    p.add_argument("--baud", type=int, default=1_000_000, help="Baudrate")
    p.add_argument("--calibration", default="servo_calibration.json", help="Calibration file")
    p.add_argument("--servo-name", default="M6", help="Single servo name key in calibration file")
    p.add_argument(
        "--servo-names",
        default="",
        help="Comma-separated servo names to test together (e.g. M2,M6)",
    )
    p.add_argument("--servo-id", type=int, default=None, help="Override servo ID")
    p.add_argument("--move-time", type=int, default=900, help="Move time in ms")
    p.add_argument("--speed", type=int, default=0, help="Servo speed")
    p.add_argument("--settle", type=float, default=1.2, help="Settle wait in seconds")
    p.add_argument("--cycles", type=int, default=2, help="Number of test cycles")
    args = p.parse_args()

    names = parse_servo_names(args.servo_name, args.servo_names)
    servo_map: Dict[str, Dict[str, object]] = {}
    try:
        for idx, name in enumerate(names):
            sid_cfg, zero, left, right = load_servo_calibration(args.calibration, name)
            sid = args.servo_id if (args.servo_id is not None and idx == 0 and len(names) == 1) else sid_cfg
            servo_map[name] = {
                "sid": sid,
                "sequence": [("zero", zero), ("max_left", left), ("max_right", right), ("zero", zero)],
            }
    except Exception as exc:
        print(f"Failed to load calibration: {exc}")
        return 2

    print("Servos under test:")
    for name in names:
        entry = servo_map[name]
        sid = int(entry["sid"])
        seq = entry["sequence"]
        print(
            f"  {name} (ID {sid}) -> "
            f"zero={seq[0][1]}, left={seq[1][1]}, right={seq[2][1]}"
        )
    print(f"Cycles: {args.cycles}")

    try:
        bus = STSSerial(args.port, args.baud)
    except Exception as exc:
        print(f"Failed to open {args.port}: {exc}")
        return 2

    try:
        bad = False
        for name in names:
            sid = int(servo_map[name]["sid"])
            if not bus.ping(sid):
                print(f"[{name}] Servo ID {sid} not responding on {args.port} @ {args.baud}")
                bad = True
        if bad:
            return 1

        for cycle in range(1, args.cycles + 1):
            print(f"\nCycle {cycle}/{args.cycles}")
            for step_idx in range(4):
                label = str(servo_map[names[0]]["sequence"][step_idx][0])
                print(f"  Move -> {label:9s}")

                # Send command to all servos for this step.
                for name in names:
                    sid = int(servo_map[name]["sid"])
                    target = int(servo_map[name]["sequence"][step_idx][1])
                    move_test(bus, sid, target, args.move_time, args.speed)
                    print(f"      [{name}] target={target}")

                time.sleep(max(0.2, args.settle))

                for name in names:
                    sid = int(servo_map[name]["sid"])
                    target = int(servo_map[name]["sequence"][step_idx][1])
                    pos = read_position(bus, sid, target)
                    print(f"      [{name}] readback={pos}")

        print("\nAuto test complete.")
        return 0
    finally:
        bus.close()


if __name__ == "__main__":
    sys.exit(main())
