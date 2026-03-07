# Autonomous RTU-Mounted Near-Stem Trimming Module

## 1. Document Control
- Document title: Technical Specification
- Project: AI-driven under-canopy trimming module for Robotriks RTU
- Version: 0.2
- Date: 2026-03-07
- Owner: Henry
- Status: Draft (expanded AI/safety workflow)

## 2. Purpose and Scope
This document defines the technical specification for an autonomous, RTU-mounted agri-implement that performs safe, stem-proximal trimming of undergrowth around crops while the base RTU navigates the field.

In-scope:
- Mechanical end-effector module and mount concept
- Electrical power and control architecture
- Edge AI perception and decision logic
- 6-DoF actuation and closed-loop control requirements
- Interfaces to RTU control stack
- Safety architecture and verification criteria

Out-of-scope (for this revision):
- Full manufacturing drawings
- Final certified safety validation report
- Finalized complete BOM (pending additional components)

## 3. System Objectives
- Trim vegetation in the 0-200 mm stem-proximal zone.
- Distinguish weeds from crop stems using edge AI.
- Detect humans near the end-effector and force immediate safe shutdown behavior.
- Dynamically command cutting aggressiveness based on weed confidence.
- Maintain cutting-head pose relative to terrain with closed-loop control.
- Integrate safely with Robotriks RTU power, navigation, and mode control.
- Support task-specific model training from user-labeled farm images via frontend workflow.

## 4. Top-Level Requirements
- AI detection target: >90% weed/crop mAP on edge hardware.
- End-to-end detection-to-actuation latency: <100 ms.
- Head height control: RMS error <= +/-5 mm at 50 Hz loop rate.
- Field efficacy: >75% weed height reduction.
- Crop safety: 0 crop damage under defined test protocol.
- Operating base speed target: up to 0.5 m/s RTU traversal.
- Human safety target: if `person` detected inside configurable danger zone, cutter command must transition to OFF with safety override (software + E-stop chain).

## 5. System Architecture
## 5.1 Functional Blocks
- Mobility and navigation: Robotriks RTU.
- Perception: Raspberry Pi 4B + Pi Camera 3 + range sensing.
- Decision: YOLOv8 inference + rule-based action policy.
- Manipulation: 6-DoF serial bus servo arm.
- Cutting subsystem: BLDC motor + nylon trimmer head.
- Supervisory control: mode manager and safety interlocks.
- Frontend and MLOps: dataset, training-job control, model registry, deployment control.

## 5.2 Operational Modes
- IDLE: Arm parked, cutter disabled.
- MANUAL: Operator-authorized direct control with cutter interlocks.
- AUTO_TRIM: AI-guided adaptive trimming.
- FAULT/E_STOP: Immediate cutter shutdown, arm safe-lift/hold.
- HUMAN_NEAR: Safety override state with cutter disabled and arm raised/held away from crop row.

## 6. Hardware Specification (Current Known Components)
## 6.1 Compute and Vision
- Raspberry Pi 4B.
  - Role: Edge compute, inference, control loop host, RTU comms bridge.
  - OS: Linux (Raspberry Pi OS / Debian-based).
- Camera: Raspberry Pi Camera Module 3.
  - Role: RGB image stream for crop/weed detection.

## 6.2 Actuation Bus
- Servo adapter: Waveshare Bus Servo Adapter (A).
  - Interface to host: USB or UART.
  - Role: Half-duplex serial bus interface to STS servo chain.
- Servos: STS3215 serial bus servos (6-DoF arm).
  - Known operating profile used in project: 7.0-7.4 V class operation.
  - ID scheme used: M1..M6 mapped to IDs 1..6.

## 6.3 Distance/Attitude Sensing
- Ultrasonic sensors (model TBD).
  - Role: Ground/obstacle distance estimation for head-height control.
- IMU (model TBD).
  - Role: Arm/head orientation and disturbance compensation.

## 6.4 Cutting Subsystem
- BLDC motor: F50 KV2150.
  - Role: Drive low-mass nylon trimmer head.
- ESC: TBD (must match BLDC power/current envelope and emergency-stop behavior).
- Trimmer head: Nylon line type, low-inertia, guarded mount.

## 6.5 Mechanical and Structure
- Module: Underslung RTU mount.
- Materials: CNC aluminium + PETG protective guards.
- Constraints: Must remain within RTU payload and stability envelope.

## 6.6 Power
- Upstream supply: RTU 24 V rail (system-level source).
- Local power domains (target):
  - Logic domain: 5 V for Pi and low-power electronics.
  - Servo domain: regulated ~7.0-7.4 V.
  - Cutter domain: ESC/motor domain (voltage/current TBD).
- Grounding: common reference ground across compute, servo bus, sensors, and drive subsystems.

## 7. Electrical and Signal Interfaces
## 7.1 Servo Bus
- Protocol: STS/SMS serial bus protocol.
- Host port on Pi: UART (`/dev/ttyAMA0` validated in current testing).
- Wiring for Pi UART:
  - Pi TX (GPIO14 pin 8) -> Adapter RX.
  - Pi RX (GPIO15 pin 10) -> Adapter TX.
  - Pi GND (pin 6) -> Adapter GND.

## 7.2 Vision Pipeline Interface
- Camera to Pi over CSI.
- Inference output interface: timestamped detections with class, bbox, confidence.

## 7.3 RTU Integration Interface
- Transport: Ethernet (ROS-style messages/services or equivalent).
- Required channels:
  - Mode command input.
  - Health/status output.
  - Fault and E-stop propagation.

## 8. Software Specification
## 8.1 Core Runtime Modules
- `perception`: camera capture + YOLOv8 inference.
- `decision`: confidence-based cut strategy.
- `control`: 50 Hz pose/height loop.
- `actuation`: servo bus command layer + cutter command layer.
- `safety`: interlocks, watchdogs, E-stop handling.
- `telemetry`: logging, diagnostics, metrics extraction.
- `frontend_api`: dataset/task management and runtime control endpoints.
- `training_orchestrator`: dataset export, training job execution, artifact tracking.
- `model_registry`: model versioning, promotion, rollback, and deployment metadata.

## 8.2 AI Model Specification
- Model family: YOLOv8 (variant TBD: n/s/m based on Pi performance).
- Baseline deployed class set: `crop_stem`, `weed`, `person`.
- Inference outputs:
  - Class label.
  - Confidence score.
  - Bounding box.
  - Frame timestamp.
- Decision policy baseline:
  - If weed confidence >0.7 in active cutting zone: low cutting height (~20 mm), cutter enabled.
  - Else: safe raised height (~60 mm), cutter disabled.
  - If `person` detected within configured proximity zone: immediate cutter OFF, arm safe raise, and safety state latch.

## 8.3 Frontend and Training Workflow
- Web frontend supports task-based dataset definition (e.g., per crop type, field, operation objective).
- Operators can upload images/video frames and annotate classes to `keep` or `remove` categories mapped to runtime classes.
- Backend exports YOLO-format datasets and launches training jobs (preferably off-Pi for heavy training).
- Model registry stores:
  - model version and checksum,
  - class map,
  - validation metrics,
  - intended task/farm profile,
  - confidence and safety thresholds.
- Deployment flow:
  - Select model version in UI,
  - deploy to Pi inference runtime,
  - perform health check,
  - allow rollback to previous model.

## 8.4 Control Loop Specification
- Loop frequency target: 50 Hz.
- Inputs: AI state, ultrasonic/ToF distance, IMU orientation, servo feedback.
- Outputs: 6-DoF servo position/speed commands and cutter enable/speed setpoint.
- Control objective:
  - Maintain cutting plane parallel to local terrain.
  - Maintain commanded height within +/-5 mm RMS.

## 9. Safety Specification
- Emergency-stop chain with cutter power cutoff in tens of milliseconds.
- AI-based person-proximity safety is advisory to hard safety and cannot replace hardware E-stop.
- Default-safe behavior on any critical fault:
  - Cutter OFF.
  - Arm to safe lift or hold state.
  - Fault latched until explicit clear.
- Human-proximity safety behavior:
  - Trigger condition: person detection confidence above threshold in danger zone near cutting head.
  - Action: force cutter disable command, inhibit re-enable, command safe arm posture.
  - Clear condition: configurable sustained absence window + explicit mode/state conditions.
- Fault classes:
  - Comms timeout (RTU, servo bus, camera pipeline).
  - Over/under-voltage in actuator domains.
  - Sensor invalid/out-of-range.
  - Compute overload causing control deadline misses.

## 10. Validation and Test Plan
## 10.1 Bench Tests
- Servo bus addressing and repeatability (IDs 1..6).
- Height loop step response and RMS error on rig.
- Cutter enable/disable response timing.
- UART and inference timing profiling.

## 10.2 AI Validation
- Dataset split and annotation protocol (TBD).
- mAP, precision, recall per class.
- Human detection precision/recall and false-negative analysis in near-head zone.
- Latency profiling from frame capture to actuation command.

## 10.3 Field Validation
- Weed height reduction measurements.
- Crop damage inspection protocol.
- Performance vs RTU speed and terrain variation.

## 11. Known Risks and Mitigations
- Serial bus collisions from duplicate IDs.
  - Mitigation: one-by-one ID provisioning workflow.
- Voltage drop under multi-servo/cutter load.
  - Mitigation: separated regulated rails, current headroom, logging.
- False positive crop-as-weed detections.
  - Mitigation: conservative confidence thresholds and safety envelopes.
- Control instability on rough terrain.
  - Mitigation: sensor fusion, rate limiting, robust fallback modes.

## 12. Configuration Baseline (Current)
- Servo IDs configured: 1, 2, 3, 4, 5, 6.
- Pi UART port validated: `/dev/ttyAMA0`.
- Servo test utility: `sts3215_test.py`.
- Motion test script: `STServo_Python/stservo-env/sms_sts/read_write.py`.

## 13. Pending Inputs (To Be Added)
- Exact ultrasonic sensor model and mounting geometry.
- IMU model and calibration method.
- ESC model and cutter electrical ratings.
- RTU interface message schema (ROS topics/services or custom protocol).
- Mechanical CAD references and mass/inertia table.
- Complete BOM with part numbers, vendors, and cost.
- Frontend tech stack decision and hosting architecture.
- Final danger-zone geometry definition and person-safety threshold tuning.

## 14. Revision Notes
- v0.1 created with currently confirmed hardware and control goals.
- v0.2 adds human-proximity safety requirements and frontend-driven model training/deployment workflow.
