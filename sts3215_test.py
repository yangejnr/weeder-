#!/usr/bin/env python3
"""Simple STS3215 bus-servo test utility for Waveshare Bus Servo Adapter.

Features:
- Scan IDs on the bus
- Read present position / voltage / temperature
- Optional move test
- Optional ID change (one-servo-at-a-time)
"""

import argparse
import sys
import time
from typing import List, Optional

import serial

HEADER = bytes((0xFF, 0xFF))

# STS/SMS register addresses
ADDR_ID = 5
ADDR_LOCK = 55
ADDR_TORQUE_ENABLE = 40
ADDR_GOAL_POSITION_L = 42
ADDR_PRESENT_POSITION_L = 56
ADDR_PRESENT_VOLTAGE = 62
ADDR_PRESENT_TEMPERATURE = 63

INST_PING = 0x01
INST_READ = 0x02
INST_WRITE = 0x03


class STSSerial:
    def __init__(self, port: str, baud: int = 1_000_000, timeout: float = 0.08):
        self.ser = serial.Serial(port=port, baudrate=baud, timeout=timeout)
        self.ser.reset_input_buffer()
        self.ser.reset_output_buffer()

    def close(self) -> None:
        self.ser.close()

    @staticmethod
    def _checksum(packet_body: bytes) -> int:
        return (~(sum(packet_body) & 0xFF)) & 0xFF

    def _make_packet(self, sid: int, inst: int, params: bytes = b"") -> bytes:
        length = len(params) + 2
        body = bytes((sid, length, inst)) + params
        chksum = self._checksum(body)
        return HEADER + body + bytes((chksum,))

    def _read_status(self, expected_id: int) -> Optional[bytes]:
        start = self.ser.read(2)
        if start != HEADER:
            return None

        rest = self.ser.read(3)
        if len(rest) != 3:
            return None

        sid, length, err = rest
        if sid != expected_id or length < 2:
            return None

        params_and_chk = self.ser.read(length - 1)
        if len(params_and_chk) != length - 1:
            return None

        params = params_and_chk[:-1]
        recv_chk = params_and_chk[-1]

        body = bytes((sid, length, err)) + params
        if recv_chk != self._checksum(body):
            return None

        if err != 0:
            return None

        return params

    def ping(self, sid: int) -> bool:
        self.ser.reset_input_buffer()
        self.ser.write(self._make_packet(sid, INST_PING))
        self.ser.flush()
        return self._read_status(sid) is not None

    def read(self, sid: int, addr: int, nbytes: int) -> Optional[bytes]:
        self.ser.reset_input_buffer()
        self.ser.write(self._make_packet(sid, INST_READ, bytes((addr, nbytes))))
        self.ser.flush()
        data = self._read_status(sid)
        if data is None or len(data) != nbytes:
            return None
        return data

    def write(self, sid: int, addr: int, data: bytes) -> None:
        self.ser.write(self._make_packet(sid, INST_WRITE, bytes((addr,)) + data))
        self.ser.flush()



def u16le(raw: bytes) -> int:
    return raw[0] | (raw[1] << 8)



def scan_ids(bus: STSSerial, start: int, end: int) -> List[int]:
    found = []
    for sid in range(start, end + 1):
        if bus.ping(sid):
            found.append(sid)
    return found



def read_basic(bus: STSSerial, sid: int) -> None:
    pos_raw = bus.read(sid, ADDR_PRESENT_POSITION_L, 2)
    volt_raw = bus.read(sid, ADDR_PRESENT_VOLTAGE, 1)
    temp_raw = bus.read(sid, ADDR_PRESENT_TEMPERATURE, 1)

    if pos_raw is None:
        print(f"ID {sid}: read failed")
        return

    pos = u16le(pos_raw)
    volt = volt_raw[0] / 10.0 if volt_raw else None
    temp = temp_raw[0] if temp_raw else None
    print(
        f"ID {sid}: pos={pos}" +
        (f", voltage={volt:.1f}V" if volt is not None else ", voltage=?") +
        (f", temp={temp}C" if temp is not None else ", temp=?")
    )



def move_test(bus: STSSerial, sid: int, pos: int, move_time_ms: int, speed: int) -> None:
    pos = max(0, min(4095, pos))
    move_time_ms = max(0, min(0xFFFF, move_time_ms))
    speed = max(0, min(0xFFFF, speed))

    bus.write(sid, ADDR_TORQUE_ENABLE, bytes((1,)))
    time.sleep(0.02)

    payload = bytes((
        pos & 0xFF,
        (pos >> 8) & 0xFF,
        move_time_ms & 0xFF,
        (move_time_ms >> 8) & 0xFF,
        speed & 0xFF,
        (speed >> 8) & 0xFF,
    ))
    bus.write(sid, ADDR_GOAL_POSITION_L, payload)



def set_servo_id(bus: STSSerial, old_id: int, new_id: int) -> bool:
    if not (0 <= old_id <= 253 and 0 <= new_id <= 253):
        return False
    if not bus.ping(old_id):
        return False
    # STS EEPROM write often requires explicit unlock/lock around ID update.
    bus.write(old_id, ADDR_LOCK, bytes((0,)))
    time.sleep(0.03)
    bus.write(old_id, ADDR_ID, bytes((new_id,)))
    time.sleep(0.08)
    bus.write(new_id, ADDR_LOCK, bytes((1,)))
    time.sleep(0.03)
    return bus.ping(new_id)



def main() -> int:
    p = argparse.ArgumentParser(description="STS3215 test tool for Waveshare Bus Servo Adapter")
    p.add_argument("--port", default="/dev/ttyACM0", help="Serial port (default: /dev/ttyACM0)")
    p.add_argument("--baud", type=int, default=1_000_000, help="Baudrate (default: 1000000)")
    p.add_argument("--scan-start", type=int, default=1, help="First ID to scan")
    p.add_argument("--scan-end", type=int, default=20, help="Last ID to scan")
    p.add_argument("--move", action="store_true", help="Run movement test after scan")
    p.add_argument(
        "--set-id",
        nargs=2,
        type=int,
        metavar=("OLD_ID", "NEW_ID"),
        help="Change one servo ID (connect one servo only)",
    )
    p.add_argument("--target", type=int, default=2048, help="Target position for move test")
    p.add_argument("--move-time", type=int, default=600, help="Move time in ms")
    p.add_argument("--speed", type=int, default=0, help="Speed (0 = max/default)")
    args = p.parse_args()

    try:
        bus = STSSerial(args.port, args.baud)
    except Exception as exc:
        print(f"Failed to open {args.port}: {exc}")
        return 2

    try:
        if args.set_id:
            old_id, new_id = args.set_id
            print(f"Changing servo ID {old_id} -> {new_id} on {args.port} @ {args.baud}...")
            ok = set_servo_id(bus, old_id, new_id)
            if ok:
                print(f"ID change succeeded: {old_id} -> {new_id}")
                return 0
            print("ID change failed (servo not found at old ID or no response at new ID).")
            return 1

        print(f"Scanning IDs {args.scan_start}..{args.scan_end} on {args.port} @ {args.baud}...")
        found = scan_ids(bus, args.scan_start, args.scan_end)
        if not found:
            print("No servos found.")
            return 1

        print("Found IDs:", ", ".join(map(str, found)))
        for sid in found:
            read_basic(bus, sid)

        if args.move:
            print(f"Running move test to position {args.target}...")
            for sid in found:
                print(f"  Move ID {sid}")
                move_test(bus, sid, args.target, args.move_time, args.speed)
                time.sleep(0.05)

            time.sleep(max(0.2, args.move_time / 1000.0 + 0.1))
            print("Positions after move:")
            for sid in found:
                read_basic(bus, sid)

        return 0
    finally:
        bus.close()


if __name__ == "__main__":
    sys.exit(main())
