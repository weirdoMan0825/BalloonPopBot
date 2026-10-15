# BalloonPopBot ROS2 Version

This ROS2 package wraps the existing Raspberry Pi car logic. The original Arduino serial command protocol is unchanged:

- `M left right`
- `S`
- `OPEN`
- `CLOSE`
- `STAB`

The motion/search/attack behavior is still implemented by the same logic copied from `balloon_pop.py`.

## Car Movement Logic

The Raspberry Pi is responsible for camera input, YOLO inference, movement decision making, and sending serial commands to Arduino. Arduino only executes low-level motor and servo commands.

### Startup

When the program starts:

1. Load the YOLO TFLite model.
2. Open serial connection to Arduino.
3. Open the USB camera.
4. Send a short warmup pulse to the motors.
5. Move forward briefly.
6. Enter automatic tracking mode.

This startup behavior is kept from the original `balloon_pop.py`.

### Target Selection

Each camera frame is passed to YOLO. The program filters detections by:

- target class id
- confidence threshold
- bounding box area

The current model uses:

```text
0: red_balloon
1: other_balloon
```

By default, the ROS2 node tracks only class `0`, so the car targets red balloons. If multiple valid red balloons are detected, the largest bounding box is selected as the target because it is usually the closest balloon.

### Tracking

The selected bounding box is used to decide the movement:

- If the balloon box touches the left edge margin, turn left.
- If the balloon box touches the right edge margin, turn right.
- If the balloon is inside the center region, move forward.

Motor movement is pulsed instead of continuous. The Raspberry Pi repeatedly sends short `M left right` commands followed by `S`. This keeps the car from overshooting while YOLO is updating.

### Search Mode

If no target is visible:

- If the car has never seen a balloon, it rotates in the configured search direction.
- If the car recently saw a balloon, it keeps moving forward briefly.
- If the balloon is still lost after the timeout, it returns to search rotation.

The default search direction is right.

### Attack Logic

The car attacks only when the target appears large enough in the image:

```text
area_ratio >= ATTACK_AREA_RATIO
```

The target must also stay large for a short hold time. This prevents accidental attacks from one noisy detection.

Attack sequence:

1. Stop tracking movement.
2. Move forward briefly for final approach.
3. Stop.
4. Close the clamp.
5. Trigger the stab servo.
6. Open the clamp.
7. Stop motors.
8. Rotate/search briefly after the attack.
9. Wait for cooldown before another attack.

Arduino receives the same serial commands as the original version:

```text
M left right
S
CLOSE
STAB
OPEN
```

### Safety

The ROS2 node provides an emergency stop topic:

```bash
ros2 topic pub --once /balloon_pop_bot/emergency_stop std_msgs/Bool "{data: true}"
```

When emergency stop is received, the node sends `S` to Arduino and stops the motor pulse controller.

## Package Layout

```text
RP_final/
  balloon_pop.py
  pi_controll.ino
  best.tflite
  best_float16.tflite
  ros2_ws/
    src/
      balloon_pop_bot/
```

## Build on Raspberry Pi

```bash
cd ~/RP_final/ros2_ws
colcon build --packages-select balloon_pop_bot
source install/setup.bash
```

## Run

```bash
ros2 launch balloon_pop_bot balloon_pop.launch.py \
  model_path:="$PWD/../best_float16.tflite" \
  serial_port:=/dev/ttyUSB0 \
  camera_id:=0
```

If Arduino is `/dev/ttyACM0`:

```bash
ros2 launch balloon_pop_bot balloon_pop.launch.py serial_port:=/dev/ttyACM0
```

## ROS2 Topics

Published:

```text
/balloon_pop_bot/action         std_msgs/String
/balloon_pop_bot/status         std_msgs/String
/balloon_pop_bot/target         std_msgs/String
/balloon_pop_bot/area_ratio     std_msgs/Float32
/balloon_pop_bot/target_visible std_msgs/Bool
```

Subscribed:

```text
/balloon_pop_bot/emergency_stop std_msgs/Bool
/balloon_pop_bot/manual_command std_msgs/String
```

Emergency stop:

```bash
ros2 topic pub --once /balloon_pop_bot/emergency_stop std_msgs/Bool "{data: true}"
```

Manual Arduino command:

```bash
ros2 topic pub --once /balloon_pop_bot/manual_command std_msgs/String "{data: 'S'}"
```

## Target Class

The current trained model uses:

```text
0: red_balloon
1: other_balloon
```

The ROS2 node defaults to tracking class `0` only. To track both classes, pass:

```bash
ros2 run balloon_pop_bot balloon_pop_node --ros-args -p target_class_ids:="[0, 1]"
```
