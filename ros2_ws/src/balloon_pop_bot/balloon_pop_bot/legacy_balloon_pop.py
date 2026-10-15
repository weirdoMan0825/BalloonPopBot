import time
import threading
import cv2
import serial
from ultralytics import YOLO


# ============================================================
# 基本設定
# ============================================================

SERIAL_PORT = "/dev/ttyUSB0"
BAUD = 115200

MODEL_PATH = "best_float16.tflite"

CAM_ID = 0
FRAME_W = 640
FRAME_H = 480

IMG_SIZE = 416
CONF_THRES = 0.70

# 模型 class 0~6 全部視為氣球
BALLOON_CLASS_IDS = set(range(7))


# ============================================================
# 程式啟動時的固定前進
# ============================================================

# 啟動暖機脈衝
START_WARMUP_SPEED = 100
START_WARMUP_ON_SEC = 0.02
START_WARMUP_OFF_SEC = 0.03
START_WARMUP_TOTAL_SEC = 1.00

# 暖機後全速連續前進
START_FORWARD_SPEED = 100
START_FORWARD_SEC = 1.50

LEFT_MOTOR_SCALE = 0.95
RIGHT_MOTOR_SCALE = 1.00


# ============================================================
# 氣球追蹤設定
# ============================================================

# bbox 進入畫面左右多少比例時才轉向
EDGE_MARGIN_RATIO = 0.12

# 短暫漏偵測時繼續直行的容忍時間
LOST_TIMEOUT_SEC = 0.70

# 搜尋方向："left" 或 "right"
SEARCH_DIRECTION = "right"


# ============================================================
# 攻擊觸發設定
# ============================================================

# bbox 面積占畫面比例達到此值時，準備攻擊
ATTACK_AREA_RATIO = 0.35

# 面積必須連續超過門檻多久，才正式執行攻擊
ATTACK_HOLD_SEC = 0.20

# 攻擊前最後一段連續前進，不使用脈衝
FINAL_FORWARD_SPEED = 100
FINAL_FORWARD_SEC = 0.30

# 最後前進後，等待車體穩定
BEFORE_ATTACK_WAIT_SEC = 0.15

# 兩側夾具閉合後保持多久
CLOSE_HOLD_SEC = 0.40

# 上方 SG90 刺破後等待多久
STAB_WAIT_SEC = 0.20

# 兩側夾具重新張開後等待多久
OPEN_WAIT_SEC = 0.20

# 攻擊完成後，強制原地搜尋多久
POST_ATTACK_SEARCH_SEC = 1.20

# 攻擊完成後多久內不允許再次攻擊
ATTACK_COOLDOWN_SEC = 1.50


# ============================================================
# 馬達短脈衝設定
# ============================================================

FORWARD_SPEED = 150
TURN_SPEED = 150
SEARCH_SPEED = 120

# 前進脈衝
FORWARD_ON_SEC = 0.020
FORWARD_OFF_SEC = 0.050

# 轉向脈衝
TURN_ON_SEC = 0.020
TURN_OFF_SEC = 0.120

# 搜尋旋轉脈衝
SEARCH_ON_SEC = 0.020
SEARCH_OFF_SEC = 0.040


# ============================================================
# 終端機輸出設定
# ============================================================

# 每隔多久輸出一次目前狀態，避免終端機刷太快
STATUS_PRINT_INTERVAL_SEC = 0.50


# ============================================================
# 動作名稱
# ============================================================

ACTION_STOP = "STOP"
ACTION_FORWARD = "FORWARD"
ACTION_LEFT = "TURN_LEFT"
ACTION_RIGHT = "TURN_RIGHT"
ACTION_SEARCH_LEFT = "SEARCH_LEFT"
ACTION_SEARCH_RIGHT = "SEARCH_RIGHT"
ACTION_ATTACK_WAIT = "ATTACK_WAIT"
ACTION_ATTACKING = "ATTACKING"
ACTION_POST_ATTACK_SEARCH = "POST_ATTACK_SEARCH"


# ============================================================
# 背景馬達脈衝控制器
# ============================================================

def apply_motor_scale(left, right):
    """
    套用左右馬達倍率補償。

    注意：
    - 正數代表前進方向
    - 負數代表反方向
    - 倍率會保留正負號
    """

    left = int(left * RIGHT_MOTOR_SCALE)
    right = int(right * LEFT_MOTOR_SCALE)

    left = max(-255, min(255, left))
    right = max(-255, min(255, right))

    return left, right


def motor_cmd(left, right):
    """
    產生已補償的 M 指令。
    """
    left, right = apply_motor_scale(left, right)
    return f"M {left} {right}"

class MotorPulseController:
    """
    背景執行緒持續輸出短脈衝。

    YOLO 主執行緒只需更新 action，
    不會被馬達脈衝的 sleep 阻塞。
    """

    def __init__(self, serial_port):
        self.ser = serial_port

        self.action = ACTION_STOP
        self.running = True
        self.manual_override = False

        self.lock = threading.Lock()
        self.serial_lock = threading.Lock()

        self.thread = threading.Thread(
            target=self._run,
            daemon=True
        )
        self.thread.start()

    def _send(self, command):
        with self.serial_lock:
            self.ser.write((command + "\n").encode())

    def set_action(self, action):
        with self.lock:
            self.action = action

    def get_action(self):
        with self.lock:
            return self.action

    def set_manual_override(self, enabled):
        with self.lock:
            self.manual_override = enabled

    def is_manual_override(self):
        with self.lock:
            return self.manual_override

    def direct_send(self, command):
        """
        直接傳送命令。
        攻擊流程或連續前進時使用。
        """
        self._send(command)

    def _motor_command(self, action):
        """
        依照你目前實測的馬達方向：

        M 正 正     前進
        M 正 負     左轉
        M 負 正     右轉
        """

        if action == ACTION_FORWARD:
            return (
                motor_cmd(FORWARD_SPEED, FORWARD_SPEED),
                FORWARD_ON_SEC,
                FORWARD_OFF_SEC
            )

        if action == ACTION_LEFT:
            return (
                motor_cmd(TURN_SPEED, -TURN_SPEED),
                TURN_ON_SEC,
                TURN_OFF_SEC
            )

        if action == ACTION_RIGHT:
            return (
                motor_cmd(-TURN_SPEED, TURN_SPEED),
                TURN_ON_SEC,
                TURN_OFF_SEC
            )

        if action == ACTION_SEARCH_LEFT:
            return (
                motor_cmd(SEARCH_SPEED, -SEARCH_SPEED),
                SEARCH_ON_SEC,
                SEARCH_OFF_SEC
            )

        if action == ACTION_SEARCH_RIGHT:
            return (
                motor_cmd(-SEARCH_SPEED, SEARCH_SPEED),
                SEARCH_ON_SEC,
                SEARCH_OFF_SEC
            )

        return "S", 0.01, 0.01

    def _run(self):
        previous_action = None

        while self.running:
            # 直接控制期間，背景執行緒不傳任何命令
            if self.is_manual_override():
                time.sleep(0.005)
                continue

            action = self.get_action()

            if action == ACTION_STOP:
                if previous_action != ACTION_STOP:
                    self._send("S")

                previous_action = ACTION_STOP
                time.sleep(0.01)
                continue

            command, on_time, off_time = self._motor_command(action)

            self._send(command)
            previous_action = action
            time.sleep(on_time)

            # ON 時段結束後，若沒有進入直接控制，就送停止
            if not self.is_manual_override():
                self._send("S")

            time.sleep(off_time)

    def emergency_stop(self):
        self.set_action(ACTION_STOP)
        self.set_manual_override(True)
        self._send("S")

    def close(self):
        self.running = False
        self.set_action(ACTION_STOP)
        self.set_manual_override(True)

        try:
            self._send("S")
        except serial.SerialException:
            pass

        self.thread.join(timeout=1.0)


# ============================================================
# 直接前進
# ============================================================

def startup_warmup_pulse(motor):
    """
    啟動時先用短脈衝暖機一段時間。
    """
    motor.set_action(ACTION_STOP)
    motor.set_manual_override(True)

    motor.direct_send("S")
    time.sleep(0.03)

    start_time = time.monotonic()

    while time.monotonic() - start_time < START_WARMUP_TOTAL_SEC:
        motor.direct_send(
            motor_cmd(START_WARMUP_SPEED, START_WARMUP_SPEED)
        )
        time.sleep(START_WARMUP_ON_SEC)

        motor.direct_send("S")
        time.sleep(START_WARMUP_OFF_SEC)

    motor.direct_send("S")

def direct_forward(motor, speed, duration):
    """
    不使用脈衝，持續前進指定時間。
    """

    motor.set_action(ACTION_STOP)
    motor.set_manual_override(True)

    motor.direct_send("S")
    time.sleep(0.03)

    motor.direct_send(motor_cmd(speed, speed))
    time.sleep(duration)

    motor.direct_send("S")


# ============================================================
# 雙針攻擊流程
# ============================================================

def execute_attack_sequence(motor):
    """
    攻擊流程：

    最後連續直走
    → 停車
    → CLOSE，左右夾具關閉
    → STAB，上方 SG90 刺破
    → OPEN，左右夾具打開
    → 停車

    Arduino 端需要支援：
    CLOSE
    STAB
    OPEN
    """

    print("\n[ATTACK] Attack sequence started.")

    # 停止背景脈衝，避免命令互相衝突
    motor.set_action(ACTION_STOP)
    motor.set_manual_override(True)

    motor.direct_send("S")
    time.sleep(0.05)

    # 1. 最後連續向前
    print(
        f"[ATTACK] Final forward: "
        f"speed={FINAL_FORWARD_SPEED}, "
        f"time={FINAL_FORWARD_SEC:.2f}s"
    )

    motor.direct_send(
        motor_cmd(FINAL_FORWARD_SPEED, FINAL_FORWARD_SPEED)
    )
    time.sleep(FINAL_FORWARD_SEC)

    # 2. 停車
    motor.direct_send("S")
    time.sleep(BEFORE_ATTACK_WAIT_SEC)

    # 3. 左右夾具關閉
    print("[ATTACK] CLOSE: clamp closing.")
    motor.direct_send("CLOSE")
    time.sleep(CLOSE_HOLD_SEC)

    # 4. 上方 SG90 刺破
    print("[ATTACK] STAB: upper servo stabbing.")
    motor.direct_send("STAB")
    time.sleep(STAB_WAIT_SEC)

    # 5. 左右夾具打開
    print("[ATTACK] OPEN: clamp opening.")
    motor.direct_send("OPEN")
    time.sleep(OPEN_WAIT_SEC)

    # 6. 保證馬達停止
    motor.direct_send("S")

    print("[ATTACK] Attack sequence completed.\n")


# ============================================================
# 尋找最大氣球
# ============================================================

def find_best_balloon(result):
    """
    從 YOLO 偵測結果中，選擇 bbox 面積最大的氣球。
    """

    if result.boxes is None or len(result.boxes) == 0:
        return None

    best = None
    best_area = 0.0

    for box in result.boxes:
        cls_id = int(box.cls[0])
        confidence = float(box.conf[0])

        if cls_id not in BALLOON_CLASS_IDS:
            continue

        if confidence < CONF_THRES:
            continue

        x1, y1, x2, y2 = box.xyxy[0].tolist()

        box_width = max(0.0, x2 - x1)
        box_height = max(0.0, y2 - y1)
        area = box_width * box_height

        if area > best_area:
            best_area = area

            best = {
                "cls_id": cls_id,
                "conf": confidence,
                "x1": x1,
                "y1": y1,
                "x2": x2,
                "y2": y2,
                "cx": (x1 + x2) / 2.0,
                "cy": (y1 + y2) / 2.0,
                "area": area,
            }

    return best


# ============================================================
# 一般追蹤決策
# ============================================================

def decide_tracking_action(best, frame_width, frame_height):
    """
    氣球未達攻擊面積時：

    bbox 碰左側區域 → 左轉
    bbox 碰右側區域 → 右轉
    其餘情況 → 前進
    """

    frame_area = frame_width * frame_height
    area_ratio = best["area"] / frame_area

    edge_margin = frame_width * EDGE_MARGIN_RATIO
    left_boundary = edge_margin
    right_boundary = frame_width - edge_margin

    if best["x1"] <= left_boundary:
        return ACTION_LEFT, area_ratio

    if best["x2"] >= right_boundary:
        return ACTION_RIGHT, area_ratio

    return ACTION_FORWARD, area_ratio


# ============================================================
# 搜尋方向
# ============================================================

def get_search_action():
    if SEARCH_DIRECTION == "left":
        return ACTION_SEARCH_LEFT

    return ACTION_SEARCH_RIGHT


# ============================================================
# 主程式
# ============================================================

def main():
    ser = None
    cap = None
    motor = None

    try:
        print("[INFO] Loading model:")
        print("       ", MODEL_PATH)

        model = YOLO(
            MODEL_PATH,
            task="detect"
        )

        print("[INFO] Opening serial:", SERIAL_PORT)

        ser = serial.Serial(
            SERIAL_PORT,
            BAUD,
            timeout=0.1
        )

        # Arduino 開啟 Serial 後通常會重新啟動
        time.sleep(2.0)

        ser.reset_input_buffer()
        ser.write(b"S\n")

        print("[INFO] Opening camera:", CAM_ID)

        cap = cv2.VideoCapture(CAM_ID)
        cap.set(
            cv2.CAP_PROP_FRAME_WIDTH,
            FRAME_W
        )
        cap.set(
            cv2.CAP_PROP_FRAME_HEIGHT,
            FRAME_H
        )

        if not cap.isOpened():
            raise RuntimeError(
                f"Cannot open camera {CAM_ID}"
            )

        motor = MotorPulseController(ser)

        # ====================================================
        # 啟動時連續前進
        # ====================================================

        print(
            f"[START] Warmup pulse for "
            f"{START_WARMUP_TOTAL_SEC:.2f}s"
        )

        startup_warmup_pulse(motor)

        print(
            f"[START] Full-speed forward: "
            f"speed={START_FORWARD_SPEED}, "
            f"time={START_FORWARD_SEC:.2f}s"
        )

        direct_forward(
            motor,
            START_FORWARD_SPEED,
            START_FORWARD_SEC
        )

        # 恢復背景脈衝控制
        motor.set_action(ACTION_STOP)
        motor.set_manual_override(False)

        print("[INFO] Automatic tracking started.")
        print("[INFO] Press Ctrl+C to stop safely.\n")

        has_seen_balloon = False
        last_seen_time = 0.0

        attack_area_start_time = None

        # 上次攻擊完成時間
        last_attack_time = -999.0

        # 攻擊後強制搜尋到什麼時間
        post_attack_search_until = 0.0

        action = ACTION_STOP
        area_ratio = 0.0

        last_status_print_time = 0.0

        while True:
            ret, frame = cap.read()

            if not ret:
                motor.set_action(ACTION_STOP)
                print("[WARN] Failed to read camera frame.")
                time.sleep(0.05)
                continue

            now = time.monotonic()

            frame_height, frame_width = frame.shape[:2]
            frame_area = frame_width * frame_height

            results = model.predict(
                frame,
                imgsz=IMG_SIZE,
                conf=CONF_THRES,
                verbose=False
            )

            best = find_best_balloon(
                results[0]
            )

            if best is not None:
                area_ratio = (
                    best["area"] / frame_area
                )
            else:
                area_ratio = 0.0

            # =================================================
            # 攻擊後強制搜尋
            # =================================================

            if now < post_attack_search_until:
                action = ACTION_POST_ATTACK_SEARCH
                motor.set_manual_override(False)
                motor.set_action(
                    get_search_action()
                )

                attack_area_start_time = None

            # =================================================
            # 偵測到氣球
            # =================================================

            elif best is not None:
                has_seen_balloon = True
                last_seen_time = now

                cooldown_finished = (
                    now - last_attack_time
                    >= ATTACK_COOLDOWN_SEC
                )

                # 攻擊面積判斷必須優先於左右邊界判斷
                if (
                    area_ratio >= ATTACK_AREA_RATIO
                    and cooldown_finished
                ):
                    if attack_area_start_time is None:
                        attack_area_start_time = now

                    attack_hold_duration = (
                        now - attack_area_start_time
                    )

                    action = ACTION_ATTACK_WAIT

                    # 等待面積持續達標期間先停車
                    motor.set_action(ACTION_STOP)

                    if (
                        attack_hold_duration
                        >= ATTACK_HOLD_SEC
                    ):
                        action = ACTION_ATTACKING
                        motor.set_action(ACTION_STOP)

                        execute_attack_sequence(
                            motor
                        )

                        attack_finished_time = (
                            time.monotonic()
                        )

                        last_attack_time = (
                            attack_finished_time
                        )

                        post_attack_search_until = (
                            attack_finished_time
                            + POST_ATTACK_SEARCH_SEC
                        )

                        # 清除上一顆氣球的追蹤狀態
                        attack_area_start_time = None
                        has_seen_balloon = False
                        last_seen_time = 0.0

                        # 恢復背景脈衝控制並開始搜尋
                        motor.set_action(
                            get_search_action()
                        )
                        motor.set_manual_override(False)

                        action = (
                            ACTION_POST_ATTACK_SEARCH
                        )

                else:
                    attack_area_start_time = None

                    action, area_ratio = (
                        decide_tracking_action(
                            best,
                            frame_width,
                            frame_height
                        )
                    )

                    motor.set_manual_override(False)
                    motor.set_action(action)

            # =================================================
            # 沒有偵測到氣球
            # =================================================

            else:
                attack_area_start_time = None

                if has_seen_balloon:
                    lost_duration = (
                        now - last_seen_time
                    )

                    if (
                        lost_duration
                        < LOST_TIMEOUT_SEC
                    ):
                        # 短暫漏偵測，繼續向前
                        action = ACTION_FORWARD
                    else:
                        # 長時間漏偵測，旋轉搜尋
                        action = get_search_action()
                else:
                    # 程式啟動後還沒看到氣球
                    action = get_search_action()

                motor.set_manual_override(False)
                motor.set_action(action)

            # =================================================
            # 終端機狀態輸出
            # =================================================

            if (
                now - last_status_print_time
                >= STATUS_PRINT_INTERVAL_SEC
            ):
                if best is not None:
                    confidence = best["conf"]
                    center_x = best["cx"]

                    if attack_area_start_time is not None:
                        attack_hold = (
                            now
                            - attack_area_start_time
                        )
                    else:
                        attack_hold = 0.0

                    print(
                        f"\r[STATUS] "
                        f"action={action:<20} "
                        f"conf={confidence:.2f} "
                        f"area={area_ratio:.3f} "
                        f"cx={center_x:.0f} "
                        f"hold={attack_hold:.2f}s",
                        end="",
                        flush=True
                    )

                else:
                    if has_seen_balloon:
                        lost_duration = (
                            now - last_seen_time
                        )
                    else:
                        lost_duration = 0.0

                    print(
                        f"\r[STATUS] "
                        f"action={action:<20} "
                        f"balloon=NONE "
                        f"lost={lost_duration:.2f}s",
                        end="",
                        flush=True
                    )

                last_status_print_time = now

    except KeyboardInterrupt:
        print(
            "\n\n[INFO] Ctrl+C received."
        )
        print("[INFO] Stopping motors safely.")

    except serial.SerialException as exc:
        print(
            f"\n[ERROR] Serial error: {exc}"
        )

    except Exception as exc:
        print(
            f"\n[ERROR] {type(exc).__name__}: {exc}"
        )

    finally:
        # 無論正常結束或發生錯誤，都保證停止馬達
        if motor is not None:
            motor.close()

        elif ser is not None:
            try:
                ser.write(b"S\n")
            except serial.SerialException:
                pass

        if cap is not None:
            cap.release()

        if ser is not None and ser.is_open:
            ser.close()

        cv2.destroyAllWindows()

        print("[INFO] Motor stopped.")
        print("[INFO] Camera and serial closed.")


if __name__ == "__main__":
    main()
