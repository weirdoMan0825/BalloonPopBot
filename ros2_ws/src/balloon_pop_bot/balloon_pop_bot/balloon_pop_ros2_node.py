import json
import threading
import time

import cv2
import rclpy
import serial
from rclpy.node import Node
from std_msgs.msg import Bool, Float32, String
from ultralytics import YOLO

from . import legacy_balloon_pop as legacy


def as_bool(value):
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.strip().lower() in ("1", "true", "yes", "on")
    return bool(value)


class BalloonPopRosNode(Node):
    def __init__(self):
        super().__init__("balloon_pop_node")

        self.declare_parameter("serial_port", legacy.SERIAL_PORT)
        self.declare_parameter("baud", legacy.BAUD)
        self.declare_parameter("model_path", legacy.MODEL_PATH)
        self.declare_parameter("camera_id", legacy.CAM_ID)
        self.declare_parameter("frame_w", legacy.FRAME_W)
        self.declare_parameter("frame_h", legacy.FRAME_H)
        self.declare_parameter("img_size", legacy.IMG_SIZE)
        self.declare_parameter("conf_thres", legacy.CONF_THRES)
        self.declare_parameter("target_class_ids", [0])
        self.declare_parameter("startup_sequence", True)
        self.declare_parameter("status_print_interval_sec", legacy.STATUS_PRINT_INTERVAL_SEC)

        self.serial_port = self.get_parameter("serial_port").value
        self.baud = int(self.get_parameter("baud").value)
        self.model_path = self.get_parameter("model_path").value
        self.camera_id = int(self.get_parameter("camera_id").value)
        self.frame_w = int(self.get_parameter("frame_w").value)
        self.frame_h = int(self.get_parameter("frame_h").value)
        self.img_size = int(self.get_parameter("img_size").value)
        self.conf_thres = float(self.get_parameter("conf_thres").value)
        self.target_class_ids = set(int(v) for v in self.get_parameter("target_class_ids").value)
        self.startup_sequence = as_bool(self.get_parameter("startup_sequence").value)
        self.status_interval = float(self.get_parameter("status_print_interval_sec").value)

        # Keep legacy behavior but allow ROS parameters to override runtime constants.
        legacy.SERIAL_PORT = self.serial_port
        legacy.BAUD = self.baud
        legacy.MODEL_PATH = self.model_path
        legacy.CAM_ID = self.camera_id
        legacy.FRAME_W = self.frame_w
        legacy.FRAME_H = self.frame_h
        legacy.IMG_SIZE = self.img_size
        legacy.CONF_THRES = self.conf_thres
        legacy.BALLOON_CLASS_IDS = self.target_class_ids
        legacy.STATUS_PRINT_INTERVAL_SEC = self.status_interval

        self.action_pub = self.create_publisher(String, "balloon_pop_bot/action", 10)
        self.status_pub = self.create_publisher(String, "balloon_pop_bot/status", 10)
        self.target_pub = self.create_publisher(String, "balloon_pop_bot/target", 10)
        self.area_pub = self.create_publisher(Float32, "balloon_pop_bot/area_ratio", 10)
        self.visible_pub = self.create_publisher(Bool, "balloon_pop_bot/target_visible", 10)

        self.create_subscription(Bool, "balloon_pop_bot/emergency_stop", self._on_emergency_stop, 10)
        self.create_subscription(String, "balloon_pop_bot/manual_command", self._on_manual_command, 10)

        self._stop_requested = False
        self._manual_command = None
        self._lock = threading.Lock()

        self.ser = None
        self.cap = None
        self.motor = None

    def _publish_string(self, pub, text):
        msg = String()
        msg.data = text
        pub.publish(msg)

    def _publish_area(self, value):
        msg = Float32()
        msg.data = float(value)
        self.area_pub.publish(msg)

    def _publish_visible(self, value):
        msg = Bool()
        msg.data = bool(value)
        self.visible_pub.publish(msg)

    def _on_emergency_stop(self, msg):
        if not msg.data:
            return
        with self._lock:
            self._stop_requested = True
        if self.motor is not None:
            self.get_logger().warn("Emergency stop requested.")
            self.motor.emergency_stop()

    def _on_manual_command(self, msg):
        command = msg.data.strip()
        if not command:
            return
        with self._lock:
            self._manual_command = command
        self.get_logger().info(f"Manual command queued: {command}")

    def _consume_manual_command(self):
        with self._lock:
            command = self._manual_command
            self._manual_command = None
        return command

    def _is_stop_requested(self):
        with self._lock:
            return self._stop_requested

    def _publish_target(self, best):
        if best is None:
            self._publish_string(self.target_pub, "{}")
            self._publish_visible(False)
            self._publish_area(0.0)
            return

        payload = {
            "class_id": int(best["cls_id"]),
            "confidence": float(best["conf"]),
            "x1": float(best["x1"]),
            "y1": float(best["y1"]),
            "x2": float(best["x2"]),
            "y2": float(best["y2"]),
            "cx": float(best["cx"]),
            "cy": float(best["cy"]),
            "area": float(best["area"]),
        }
        self._publish_string(self.target_pub, json.dumps(payload))
        self._publish_visible(True)

    def run(self):
        try:
            self.get_logger().info(f"Loading model: {self.model_path}")
            model = YOLO(self.model_path, task="detect")

            self.get_logger().info(f"Opening serial: {self.serial_port}")
            self.ser = serial.Serial(self.serial_port, self.baud, timeout=0.1)
            time.sleep(2.0)
            self.ser.reset_input_buffer()
            self.ser.write(b"S\n")

            self.get_logger().info(f"Opening camera: {self.camera_id}")
            self.cap = cv2.VideoCapture(self.camera_id)
            self.cap.set(cv2.CAP_PROP_FRAME_WIDTH, self.frame_w)
            self.cap.set(cv2.CAP_PROP_FRAME_HEIGHT, self.frame_h)

            if not self.cap.isOpened():
                raise RuntimeError(f"Cannot open camera {self.camera_id}")

            self.motor = legacy.MotorPulseController(self.ser)

            if self.startup_sequence:
                self.get_logger().info("Running original startup warmup sequence.")
                legacy.startup_warmup_pulse(self.motor)
                legacy.direct_forward(
                    self.motor,
                    legacy.START_FORWARD_SPEED,
                    legacy.START_FORWARD_SEC,
                )

            self.motor.set_action(legacy.ACTION_STOP)
            self.motor.set_manual_override(False)

            self.get_logger().info("ROS2 automatic tracking started.")
            self.get_logger().info(f"Target class ids: {sorted(self.target_class_ids)}")

            has_seen_balloon = False
            last_seen_time = 0.0
            attack_area_start_time = None
            last_attack_time = -999.0
            post_attack_search_until = 0.0
            action = legacy.ACTION_STOP
            area_ratio = 0.0
            last_status_print_time = 0.0

            while rclpy.ok() and not self._is_stop_requested():
                rclpy.spin_once(self, timeout_sec=0.0)

                manual_command = self._consume_manual_command()
                if manual_command is not None and self.motor is not None:
                    self.motor.set_manual_override(True)
                    self.motor.direct_send(manual_command)
                    self._publish_string(self.action_pub, f"MANUAL:{manual_command}")
                    continue

                ret, frame = self.cap.read()

                if not ret:
                    self.motor.set_action(legacy.ACTION_STOP)
                    self.get_logger().warn("Failed to read camera frame.")
                    time.sleep(0.05)
                    continue

                now = time.monotonic()

                frame_height, frame_width = frame.shape[:2]
                frame_area = frame_width * frame_height

                results = model.predict(
                    frame,
                    imgsz=self.img_size,
                    conf=self.conf_thres,
                    verbose=False,
                )

                best = legacy.find_best_balloon(results[0])
                self._publish_target(best)

                if best is not None:
                    area_ratio = best["area"] / frame_area
                else:
                    area_ratio = 0.0
                self._publish_area(area_ratio)

                if now < post_attack_search_until:
                    action = legacy.ACTION_POST_ATTACK_SEARCH
                    self.motor.set_manual_override(False)
                    self.motor.set_action(legacy.get_search_action())
                    attack_area_start_time = None

                elif best is not None:
                    has_seen_balloon = True
                    last_seen_time = now

                    cooldown_finished = (
                        now - last_attack_time >= legacy.ATTACK_COOLDOWN_SEC
                    )

                    if area_ratio >= legacy.ATTACK_AREA_RATIO and cooldown_finished:
                        if attack_area_start_time is None:
                            attack_area_start_time = now

                        attack_hold_duration = now - attack_area_start_time
                        action = legacy.ACTION_ATTACK_WAIT
                        self.motor.set_action(legacy.ACTION_STOP)

                        if attack_hold_duration >= legacy.ATTACK_HOLD_SEC:
                            action = legacy.ACTION_ATTACKING
                            self.motor.set_action(legacy.ACTION_STOP)
                            self._publish_string(self.action_pub, action)
                            legacy.execute_attack_sequence(self.motor)

                            attack_finished_time = time.monotonic()
                            last_attack_time = attack_finished_time
                            post_attack_search_until = (
                                attack_finished_time + legacy.POST_ATTACK_SEARCH_SEC
                            )

                            attack_area_start_time = None
                            has_seen_balloon = False
                            last_seen_time = 0.0

                            self.motor.set_action(legacy.get_search_action())
                            self.motor.set_manual_override(False)
                            action = legacy.ACTION_POST_ATTACK_SEARCH

                    else:
                        attack_area_start_time = None
                        action, area_ratio = legacy.decide_tracking_action(
                            best,
                            frame_width,
                            frame_height,
                        )
                        self.motor.set_manual_override(False)
                        self.motor.set_action(action)

                else:
                    attack_area_start_time = None

                    if has_seen_balloon:
                        lost_duration = now - last_seen_time

                        if lost_duration < legacy.LOST_TIMEOUT_SEC:
                            action = legacy.ACTION_FORWARD
                        else:
                            action = legacy.get_search_action()
                    else:
                        action = legacy.get_search_action()

                    self.motor.set_manual_override(False)
                    self.motor.set_action(action)

                self._publish_string(self.action_pub, action)

                if now - last_status_print_time >= self.status_interval:
                    if best is not None:
                        attack_hold = (
                            now - attack_area_start_time
                            if attack_area_start_time is not None
                            else 0.0
                        )
                        status = (
                            f"action={action} "
                            f"conf={best['conf']:.2f} "
                            f"area={area_ratio:.3f} "
                            f"cx={best['cx']:.0f} "
                            f"hold={attack_hold:.2f}s"
                        )
                    else:
                        lost_duration = now - last_seen_time if has_seen_balloon else 0.0
                        status = (
                            f"action={action} "
                            f"target=NONE "
                            f"lost={lost_duration:.2f}s"
                        )

                    self._publish_string(self.status_pub, status)
                    self.get_logger().info(status)
                    last_status_print_time = now

        except KeyboardInterrupt:
            self.get_logger().info("KeyboardInterrupt received.")
        except serial.SerialException as exc:
            self.get_logger().error(f"Serial error: {exc}")
        except Exception as exc:
            self.get_logger().error(f"{type(exc).__name__}: {exc}")
        finally:
            self.close()

    def close(self):
        if self.motor is not None:
            self.motor.close()
            self.motor = None
        elif self.ser is not None:
            try:
                self.ser.write(b"S\n")
            except serial.SerialException:
                pass

        if self.cap is not None:
            self.cap.release()
            self.cap = None

        if self.ser is not None and self.ser.is_open:
            self.ser.close()
            self.ser = None

        cv2.destroyAllWindows()
        self.get_logger().info("Motor stopped. Camera and serial closed.")


def main(args=None):
    rclpy.init(args=args)
    node = BalloonPopRosNode()
    try:
        node.run()
    finally:
        node.destroy_node()
        rclpy.shutdown()


if __name__ == "__main__":
    main()
