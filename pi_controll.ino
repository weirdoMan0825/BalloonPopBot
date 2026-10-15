#include <Servo.h>

// ============================================================
// L298N motor pins
// ============================================================

const int ENA = 5;
const int IN1 = 8;
const int IN2 = 9;

const int ENB = 6;
const int IN3 = 10;
const int IN4 = 11;


// ============================================================
// SG90 servo pins
// ============================================================

// 上方刺破伺服馬達
const int SERVO_STAB_PIN = 4;

// 左側夾具
const int SERVO_LEFT_PIN = 7;

// 右側夾具
const int SERVO_RIGHT_PIN = 12;

Servo stabServo;
Servo leftServo;
Servo rightServo;


// ============================================================
// Servo angle settings
// 請依照你的機構實際調整
// ============================================================

// 上方刺破馬達
const int STAB_REST_ANGLE = 65;
const int STAB_HIT_ANGLE = 135;

// 右側夾具
const int RIGHT_OPEN_ANGLE = 50;
const int RIGHT_CLOSE_ANGLE = 110;

// 左側夾具通常需要和左側反向
const int LEFT_OPEN_ANGLE = 120;
const int LEFT_CLOSE_ANGLE = 60;


// ============================================================
// Servo timing settings
// ============================================================

// 左右夾具移動後等待時間
const int CLAMP_MOVE_DELAY_MS = 450;

// 刺下去後停留時間
const int STAB_HOLD_MS = 300;

// 刺破馬達收回後等待時間
const int STAB_RETURN_DELAY_MS = 250;


// ============================================================
// Motor functions
// ============================================================

void setMotorOne(
  int speedValue,
  int inA,
  int inB,
  int enPin
) {
  speedValue = constrain(speedValue, -255, 255);

  if (speedValue > 0) {
    digitalWrite(inA, HIGH);
    digitalWrite(inB, LOW);
    analogWrite(enPin, speedValue);
  }
  else if (speedValue < 0) {
    digitalWrite(inA, LOW);
    digitalWrite(inB, HIGH);
    analogWrite(enPin, -speedValue);
  }
  else {
    digitalWrite(inA, LOW);
    digitalWrite(inB, LOW);
    analogWrite(enPin, 0);
  }
}


void setMotors(int leftSpeed, int rightSpeed) {
  setMotorOne(
    leftSpeed,
    IN1,
    IN2,
    ENA
  );

  setMotorOne(
    rightSpeed,
    IN3,
    IN4,
    ENB
  );
}


// ============================================================
// Servo functions
// ============================================================

void openClamp() {
  leftServo.write(LEFT_OPEN_ANGLE);
  rightServo.write(RIGHT_OPEN_ANGLE);

  delay(CLAMP_MOVE_DELAY_MS);

  Serial.println("CLAMP_OPEN_OK");
}


void closeClamp() {
  leftServo.write(LEFT_CLOSE_ANGLE);
  rightServo.write(RIGHT_CLOSE_ANGLE);

  delay(CLAMP_MOVE_DELAY_MS);

  Serial.println("CLAMP_CLOSE_OK");
}


void stabOnce() {
  // 確保從收回位置開始
  stabServo.write(STAB_REST_ANGLE);
  delay(150);

  // 向下刺
  stabServo.write(STAB_HIT_ANGLE);
  delay(STAB_HOLD_MS);

  // 收回
  stabServo.write(STAB_REST_ANGLE);
  delay(STAB_RETURN_DELAY_MS);

  Serial.println("STAB_OK");
}


// 可選：完整夾取＋刺破流程
void popSequence() {
  Serial.println("POP_START");

  // 為安全起見先停馬達
  setMotors(0, 0);
  delay(100);

  closeClamp();
  stabOnce();

  Serial.println("POP_DONE");
}


// ============================================================
// Setup
// ============================================================

void setup() {
  Serial.begin(115200);

  // 避免 readStringUntil 等待太久
  Serial.setTimeout(50);

  // 馬達腳位
  pinMode(ENA, OUTPUT);
  pinMode(IN1, OUTPUT);
  pinMode(IN2, OUTPUT);

  pinMode(ENB, OUTPUT);
  pinMode(IN3, OUTPUT);
  pinMode(IN4, OUTPUT);

  setMotors(0, 0);

  // Servo 初始化
  stabServo.attach(SERVO_STAB_PIN);
  leftServo.attach(SERVO_LEFT_PIN);
  rightServo.attach(SERVO_RIGHT_PIN);

  // 啟動時：
  // 刺破馬達保持收回
  // 左右夾具保持打開
  stabServo.write(STAB_REST_ANGLE);
  leftServo.write(LEFT_OPEN_ANGLE);
  rightServo.write(RIGHT_OPEN_ANGLE);

  delay(500);

  Serial.println("ARDUINO_READY");
}


// ============================================================
// Main loop
// ============================================================

void loop() {
  if (!Serial.available()) {
    return;
  }

  String cmd = Serial.readStringUntil('\n');
  cmd.trim();

  if (cmd.length() == 0) {
    return;
  }

  // ----------------------------------------------------------
  // Communication test
  // ----------------------------------------------------------

  if (cmd == "PING") {
    Serial.println("PONG");
  }

  // ----------------------------------------------------------
  // Motor stop
  // ----------------------------------------------------------

  else if (cmd == "S") {
    setMotors(0, 0);
    Serial.println("STOP_OK");
  }

  // ----------------------------------------------------------
  // Motor command: M left right
  // ----------------------------------------------------------

  else if (cmd.startsWith("M ")) {
    int firstSpace = cmd.indexOf(' ');
    int secondSpace = cmd.indexOf(
      ' ',
      firstSpace + 1
    );

    if (secondSpace > 0) {
      int leftSpeed = cmd.substring(
        firstSpace + 1,
        secondSpace
      ).toInt();

      int rightSpeed = cmd.substring(
        secondSpace + 1
      ).toInt();

      leftSpeed = constrain(
        leftSpeed,
        -255,
        255
      );

      rightSpeed = constrain(
        rightSpeed,
        -255,
        255
      );

      setMotors(
        leftSpeed,
        rightSpeed
      );

      Serial.print("MOTOR_OK ");
      Serial.print(leftSpeed);
      Serial.print(" ");
      Serial.println(rightSpeed);
    }
    else {
      Serial.println("ERR_BAD_M_CMD");
    }
  }

  // ----------------------------------------------------------
  // Open clamp
  // ----------------------------------------------------------

  else if (cmd == "OPEN") {
    openClamp();
  }

  // ----------------------------------------------------------
  // Close clamp
  // ----------------------------------------------------------

  else if (cmd == "CLOSE") {
    // 安全起見，夾取前先停車
    setMotors(0, 0);
    closeClamp();
  }

  // ----------------------------------------------------------
  // Stab
  // ----------------------------------------------------------

  else if (cmd == "STAB") {
    // 安全起見，刺破前先停車
    setMotors(0, 0);
    stabOnce();
  }

  // ----------------------------------------------------------
  // Optional complete sequence
  // ----------------------------------------------------------

  else if (cmd == "P") {
    popSequence();
  }

  // ----------------------------------------------------------
  // Unknown command
  // ----------------------------------------------------------

  else {
    Serial.print("ERR_UNKNOWN_CMD ");
    Serial.println(cmd);
  }
}