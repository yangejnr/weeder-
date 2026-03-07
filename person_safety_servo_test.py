#!/usr/bin/env python3
"""Camera + YOLO person safety test for STS bus servo.

Behavior:
- If a person is detected above threshold, servo motion is stopped (hold position).
- If no person is detected for N frames, servo resumes periodic motion.
"""

import argparse
import sys
import time

import cv2
from ultralytics import YOLO

from sts3215_test import (
    ADDR_PRESENT_POSITION_L,
    STSSerial,
    move_test,
    u16le,
)


def read_position(bus: STSSerial, sid: int, fallback: int) -> int:
    raw = bus.read(sid, ADDR_PRESENT_POSITION_L, 2)
    if raw is None:
        return fallback
    return u16le(raw)


def person_detected(result, person_conf: float) -> bool:
    if result.boxes is None:
        return False

    cls = result.boxes.cls
    conf = result.boxes.conf
    if cls is None or conf is None:
        return False

    for c, s in zip(cls.tolist(), conf.tolist()):
        # COCO class id 0 is person for YOLOv8 pretrained models.
        if int(c) == 0 and float(s) >= person_conf:
            return True
    return False


def main() -> int:
    p = argparse.ArgumentParser(description="Person safety servo motion test")
    p.add_argument("--model", default="yolov8n.pt", help="YOLO model path")
    p.add_argument("--source", default="0", help="Video source (index or device/file)")
    p.add_argument("--person-conf", type=float, default=0.5, help="Person confidence threshold")
    p.add_argument("--clear-frames", type=int, default=10, help="Frames without person before resume")
    p.add_argument("--port", default="/dev/ttyAMA0", help="Servo serial port")
    p.add_argument("--baud", type=int, default=1_000_000, help="Servo baudrate")
    p.add_argument("--servo-id", type=int, default=1, help="Servo ID to move")
    p.add_argument("--move-a", type=int, default=512, help="Motion endpoint A")
    p.add_argument("--move-b", type=int, default=3072, help="Motion endpoint B")
    p.add_argument("--move-time", type=int, default=1000, help="Move time in ms")
    p.add_argument("--speed", type=int, default=0, help="Servo speed (0 default)")
    p.add_argument("--interval", type=float, default=1.5, help="Seconds between move commands")
    p.add_argument("--no-display", action="store_true", help="Disable video display window")
    args = p.parse_args()

    src = int(args.source) if args.source.isdigit() else args.source

    model = YOLO(args.model)

    try:
        bus = STSSerial(args.port, args.baud)
    except Exception as exc:
        print(f"Failed to open servo port {args.port}: {exc}")
        return 2

    if not bus.ping(args.servo_id):
        print(f"Servo ID {args.servo_id} not responding on {args.port} @ {args.baud}")
        bus.close()
        return 2

    cap = cv2.VideoCapture(src)
    if not cap.isOpened():
        print(f"Failed to open video source: {args.source}")
        bus.close()
        return 2

    print("Running. Press 'q' in window or Ctrl+C to stop.")

    motion_targets = [max(0, min(4095, args.move_a)), max(0, min(4095, args.move_b))]
    target_idx = 0
    last_move_ts = 0.0
    current_target = read_position(bus, args.servo_id, motion_targets[0])

    stopped_for_person = False
    clear_count = 0

    try:
        while True:
            ok, frame = cap.read()
            if not ok:
                print("Video frame read failed; exiting.")
                break

            result = model(frame, verbose=False)[0]
            person_near = person_detected(result, args.person_conf)

            now = time.time()

            if person_near:
                clear_count = 0
                if not stopped_for_person:
                    hold = read_position(bus, args.servo_id, current_target)
                    move_test(bus, args.servo_id, hold, 300, args.speed)
                    current_target = hold
                    stopped_for_person = True
                    print("SAFETY: person detected -> servo HOLD")
            else:
                clear_count += 1
                if stopped_for_person and clear_count >= args.clear_frames:
                    stopped_for_person = False
                    print("SAFETY: area clear -> resume motion")

            if not stopped_for_person and (now - last_move_ts) >= args.interval:
                current_target = motion_targets[target_idx]
                move_test(bus, args.servo_id, current_target, args.move_time, args.speed)
                target_idx = 1 - target_idx
                last_move_ts = now

            if not args.no_display:
                label = "PERSON:STOP" if person_near else "CLEAR:RUN"
                color = (0, 0, 255) if person_near else (0, 255, 0)
                cv2.putText(frame, label, (12, 28), cv2.FONT_HERSHEY_SIMPLEX, 0.8, color, 2)
                cv2.imshow("person_safety_servo_test", frame)
                key = cv2.waitKey(1) & 0xFF
                if key == ord("q"):
                    break

    except KeyboardInterrupt:
        pass
    finally:
        cap.release()
        cv2.destroyAllWindows()
        bus.close()

    return 0


if __name__ == "__main__":
    sys.exit(main())
