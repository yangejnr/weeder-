#!/usr/bin/env python
#
# *********     Gen Write Example      *********
#
#
# Available ST Servo model on this example : All models using Protocol ST
# This example is tested with a ST Servo(ST3215/ST3020/ST3025), and an URT
#

import sys
import os
import time

if os.name == 'nt':
    import msvcrt
    def getch():
        return msvcrt.getch().decode()
        
else:
    import sys, tty, termios
    fd = sys.stdin.fileno()
    old_settings = termios.tcgetattr(fd)
    def getch():
        try:
            tty.setraw(sys.stdin.fileno())
            ch = sys.stdin.read(1)
        finally:
            termios.tcsetattr(fd, termios.TCSADRAIN, old_settings)
        return ch

sys.path.append("..")
from scservo_sdk import *                      # Uses SC Servo SDK library

# Default setting
BAUDRATE                    = 1000000           # SC Servo default baudrate : 1000000
DEVICENAME                  = '/dev/ttyACM0'    # Check which port is being used on your controller
                                                # ex) Windows: "COM1"   Linux: "/dev/ttyUSB0" Mac: "/dev/tty.usbserial-*"
SCS_MINIMUM_POSITION_VALUE  = 0
SCS_MAXIMUM_POSITION_VALUE  = 4095
SCS_MOVING_SPEED            = 2400        # SC Servo moving speed
SCS_MOVING_ACC              = 50          # SC Servo moving acc

DEGREE_SEQUENCE = [0, 90, 180, 270, 360, 0]
PHASE_REPEAT_COUNT = 1
TARGET_TOLERANCE = 15
SETTLE_DELAY_SEC = 0.15
PHASES = [
    ("Phase 1 - Move ID 1", [1]),
    ("Phase 2 - Move ID 2", [2]),
    ("Phase 3 - Move ID 3", [3]),
    ("Phase 4 - Move ID 4", [4]),
    ("Phase 5 - Move ID 5", [5]),
    ("Phase 6 - Move ID 6", [6]),
    ("Phase 7 - Move IDs 1, 2, 3, 4, 5 and 6", [1, 2, 3, 4, 5, 6]),
]


def deg_to_pos(deg):
    if deg < 0:
        deg = 0
    if deg > 360:
        deg = 360
    return int(round((deg / 360.0) * SCS_MAXIMUM_POSITION_VALUE))


def unique_phase_ids():
    ids = []
    for _, phase_ids in PHASES:
        for servo_id in phase_ids:
            if servo_id not in ids:
                ids.append(servo_id)
    return ids


def preflight_check(packet_handler, expected_ids):
    print("Preflight check: ping expected IDs:", expected_ids)
    ok_ids = []
    bad_ids = []
    for servo_id in expected_ids:
        _, scs_comm_result, scs_error = packet_handler.ping(servo_id)
        if scs_comm_result == COMM_SUCCESS and scs_error == 0:
            ok_ids.append(servo_id)
            print("[ID:%03d] OK" % servo_id)
        else:
            bad_ids.append(servo_id)
            msg = packet_handler.getTxRxResult(scs_comm_result) if scs_comm_result != COMM_SUCCESS else packet_handler.getRxPacketError(scs_error)
            print("[ID:%03d] FAIL - %s" % (servo_id, msg))

    if bad_ids:
        print("Preflight failed. Missing/unstable IDs:", bad_ids)
        print("Hint: test one-servo-at-a-time and ensure unique IDs before running phases.")
        return False
    print("Preflight passed. All expected IDs are reachable.")
    return True

# Initialize PortHandler instance
# Set the port path
# Get methods and members of PortHandlerLinux or PortHandlerWindows
portHandler = PortHandler(DEVICENAME)

# Initialize PacketHandler instance
# Get methods and members of Protocol
packetHandler = sms_sts(portHandler)
    
# Open port
if portHandler.openPort():
    print("Succeeded to open the port")
else:
    print("Failed to open the port")
    print("Press any key to terminate...")
    getch()
    quit()

# Set port baudrate
if portHandler.setBaudRate(BAUDRATE):
    print("Succeeded to change the baudrate")
else:
    print("Failed to change the baudrate")
    print("Press any key to terminate...")
    getch()
    quit()

expected_ids = unique_phase_ids()
if not preflight_check(packetHandler, expected_ids):
    portHandler.closePort()
    sys.exit(1)

for phase_name, phase_ids in PHASES:
    print("\n=== %s ===" % phase_name)
    for cycle in range(PHASE_REPEAT_COUNT):
        print("Cycle %d/%d" % (cycle + 1, PHASE_REPEAT_COUNT))
        for goal_deg in DEGREE_SEQUENCE:
            print("Base step angle: %d deg" % goal_deg)
            active_ids = []
            goal_by_id = {}

            # Write goal position/moving speed/moving acc to all servos in this phase.
            for servo_id in phase_ids:
                servo_goal_deg = goal_deg
                servo_goal_pos = deg_to_pos(servo_goal_deg)
                goal_by_id[servo_id] = (servo_goal_deg, servo_goal_pos)
                scs_comm_result, scs_error = packetHandler.WritePosEx(
                    servo_id, servo_goal_pos, SCS_MOVING_SPEED, SCS_MOVING_ACC
                )
                if scs_comm_result != COMM_SUCCESS:
                    print("[ID:%03d] %s" % (servo_id, packetHandler.getTxRxResult(scs_comm_result)))
                    continue
                if scs_error != 0:
                    print("[ID:%03d] %s" % (servo_id, packetHandler.getRxPacketError(scs_error)))
                print("[ID:%03d] TargetDeg:%3d TargetPos:%4d" % (servo_id, servo_goal_deg, servo_goal_pos))
                active_ids.append(servo_id)

            if not active_ids:
                print("No servo accepted the command for this step.")
                continue

            # Let servo state update before the first read to avoid skipping steps.
            time.sleep(SETTLE_DELAY_SEC)

            settled = set()
            while len(settled) < len(active_ids):
                for servo_id in active_ids:
                    if servo_id in settled:
                        continue

                    # Read SC Servo present position
                    scs_present_position, scs_present_speed, scs_comm_result, scs_error = packetHandler.ReadPosSpeed(servo_id)
                    if scs_comm_result != COMM_SUCCESS:
                        print("[ID:%03d] %s" % (servo_id, packetHandler.getTxRxResult(scs_comm_result)))
                        settled.add(servo_id)
                        continue
                    else:
                        servo_goal_deg, servo_goal_pos = goal_by_id[servo_id]
                        print("[ID:%03d] GoalDeg:%3d GoalPos:%4d PresPos:%4d PresSpd:%4d" % (
                            servo_id, servo_goal_deg, servo_goal_pos, scs_present_position, scs_present_speed
                        ))
                    if scs_error != 0:
                        print("[ID:%03d] %s" % (servo_id, packetHandler.getRxPacketError(scs_error)))

                    # Read SC Servo moving status
                    moving, scs_comm_result, scs_error = packetHandler.ReadMoving(servo_id)
                    if scs_comm_result != COMM_SUCCESS:
                        print("[ID:%03d] %s" % (servo_id, packetHandler.getTxRxResult(scs_comm_result)))
                        settled.add(servo_id)
                        continue

                    _, servo_goal_pos = goal_by_id[servo_id]
                    if moving == 0 and abs(scs_present_position - servo_goal_pos) <= TARGET_TOLERANCE:
                        settled.add(servo_id)
                time.sleep(0.05)

# Close port
portHandler.closePort()
