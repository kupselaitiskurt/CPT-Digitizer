/*
  Rev2_Peripheral.ino
  Arduino Nano BLE Rev2 — BLE Peripheral / Data Collector

  Advertises as "TestSensor".  The GIGA R1 (Central) connects, sends a
  configuration string and START / STOP commands, then the Rev2 streams
  collected CSV data back via BLE notifications.

  Protocol — all characteristics are UTF-8 strings:
    CONFIG (Write)  : "SHAFT:x,TUBE:y,MODE:Single|Multi,INTERVAL:hrs,MAXTIME:hrs"
    CMD    (Write)  : "START" | "STOP" | "SEND" | "RESET"
    DATA   (Notify) : "elapsed_ms,sA,sB"  ...rows...  "END"
    STATUS (Notify) : "IDLE" | "READY" | "RUNNING" | "DONE:<n>" | "SENDING"

  Adjust SENSOR_A / SENSOR_B to the analog pins of your actual sensors.
  INTERVAL and MAXTIME values sent from the GIGA are in hours.
*/

#include <ArduinoBLE.h>

// ── UUIDs — must match GIGA_Main.ino ──────────────────────────────────────
#define SVC_UUID   "19B10000-E8F2-537E-4F6C-D104768A1214"
#define CFG_UUID   "19B10001-E8F2-537E-4F6C-D104768A1214"
#define CMD_UUID   "19B10002-E8F2-537E-4F6C-D104768A1214"
#define DATA_UUID  "19B10003-E8F2-537E-4F6C-D104768A1214"
#define STAT_UUID  "19B10004-E8F2-537E-4F6C-D104768A1214"

// ── Sensor analog pins (change to match your hardware) ────────────────────
#define SENSOR_A   A0
#define SENSOR_B   A1

// ── Data buffer ───────────────────────────────────────────────────────────
// Nano BLE Rev2 has 256 KB RAM.
// 2 000 records × 8 bytes = 16 KB — safe headroom.
// Increase MAX_RECS cautiously if you need longer runs with short intervals.
struct Record {
  uint32_t elapsed_ms;
  int16_t  sA;
  int16_t  sB;
};

static const int MAX_RECS = 2000;
static Record    recs[MAX_RECS];
static int       rec_n = 0;

// ── BLE objects ───────────────────────────────────────────────────────────
BLEService              svc(SVC_UUID);
BLEStringCharacteristic cfgChar (CFG_UUID,  BLEWrite,            128);
BLEStringCharacteristic cmdChar (CMD_UUID,  BLEWrite,             16);
BLEStringCharacteristic dataChar(DATA_UUID, BLERead | BLENotify,  48);
BLEStringCharacteristic stChar  (STAT_UUID, BLERead | BLENotify,  32);

// ── State machine ─────────────────────────────────────────────────────────
enum State { ST_IDLE, ST_READY, ST_RUNNING, ST_DONE };
static State st = ST_IDLE;

// ── Config (runtime defaults; overwritten by CONFIG characteristic) ───────
static unsigned long ivl_ms  = 3600000UL;         // sample interval  (1 hr)
static unsigned long max_ms  = 72UL * 3600000UL;  // max test duration (72 hr)
static unsigned long t_start = 0;
static unsigned long t_last  = 0;

// ── Helpers ───────────────────────────────────────────────────────────────
static String getField(const String& s, const char* key) {
  String k = String(key) + ":";
  int i = s.indexOf(k);
  if (i < 0) return "";
  i += k.length();
  int j = s.indexOf(',', i);
  return (j < 0) ? s.substring(i) : s.substring(i, j);
}

static void notifyStatus(const char* msg) {
  stChar.writeValue(msg);
  Serial.print("[STATUS] "); Serial.println(msg);
}

static void applyConfig(const String& cfg) {
  Serial.print("[CONFIG] "); Serial.println(cfg);
  String iv = getField(cfg, "INTERVAL");
  String mt = getField(cfg, "MAXTIME");
  if (iv.length() > 0) ivl_ms = (unsigned long)(iv.toFloat() * 3600000.0f);
  if (mt.length() > 0) max_ms = (unsigned long)(mt.toFloat() * 3600000.0f);
  rec_n = 0;
  st    = ST_READY;
  notifyStatus("READY");
}

static void takeSample() {
  if (rec_n >= MAX_RECS) return;
  recs[rec_n].elapsed_ms = millis() - t_start;
  recs[rec_n].sA = (int16_t)analogRead(SENSOR_A);
  recs[rec_n].sB = (int16_t)analogRead(SENSOR_B);
  rec_n++;
  Serial.print("[SAMPLE] n="); Serial.println(rec_n);
}

// Streams all buffered records to the GIGA via BLE notifications.
// Called when GIGA sends "SEND" after a "STOP".
static void streamData() {
  notifyStatus("SENDING");

  // CSV header
  dataChar.writeValue("elapsed_ms,sA,sB");
  delay(40);

  for (int i = 0; i < rec_n; i++) {
    char buf[40];
    snprintf(buf, sizeof(buf), "%lu,%d,%d",
             (unsigned long)recs[i].elapsed_ms,
             (int)recs[i].sA, (int)recs[i].sB);
    dataChar.writeValue(buf);
    delay(40);   // throttle — reduce if GIGA handles fast delivery
    BLE.poll();  // keep connection alive during long transfer
  }

  dataChar.writeValue("END");
  st = ST_READY;
  notifyStatus("READY");
}

// ── Setup ─────────────────────────────────────────────────────────────────
void setup() {
  Serial.begin(115200);

  pinMode(SENSOR_A, INPUT);
  pinMode(SENSOR_B, INPUT);

  if (!BLE.begin()) {
    Serial.println("BLE init failed");
    while (true) delay(1000);
  }

  BLE.setLocalName("TestSensor");
  BLE.setDeviceName("TestSensor");
  BLE.setAdvertisedService(svc);

  svc.addCharacteristic(cfgChar);
  svc.addCharacteristic(cmdChar);
  svc.addCharacteristic(dataChar);
  svc.addCharacteristic(stChar);

  BLE.addService(svc);
  stChar.writeValue("IDLE");
  BLE.advertise();
  Serial.println("Advertising as TestSensor");
}

// ── Loop ──────────────────────────────────────────────────────────────────
void loop() {
  BLEDevice central = BLE.central();
  if (!central) { BLE.poll(); return; }

  Serial.print("Central connected: "); Serial.println(central.address());
  st    = ST_READY;
  rec_n = 0;
  notifyStatus("READY");

  while (central.connected()) {
    BLE.poll();

    // ── Handle incoming config ─────────────────────────────────────────
    if (cfgChar.written()) {
      applyConfig(cfgChar.value());
    }

    // ── Handle commands ───────────────────────────────────────────────
    if (cmdChar.written()) {
      String cmd = cmdChar.value();
      cmd.trim();
      Serial.print("[CMD] "); Serial.println(cmd);

      if (cmd == "START" && st == ST_READY) {
        t_start = millis();
        t_last  = t_start;
        st      = ST_RUNNING;
        notifyStatus("RUNNING");

      } else if (cmd == "STOP" && st == ST_RUNNING) {
        st = ST_DONE;
        char buf[24];
        snprintf(buf, sizeof(buf), "DONE:%d", rec_n);
        notifyStatus(buf);

      } else if (cmd == "SEND" && st == ST_DONE) {
        streamData();

      } else if (cmd == "RESET") {
        st    = ST_READY;
        rec_n = 0;
        notifyStatus("READY");
      }
    }

    // ── Sample if running ─────────────────────────────────────────────
    if (st == ST_RUNNING) {
      unsigned long now = millis();
      if (now - t_last >= ivl_ms) {
        t_last = now;
        takeSample();
      }
      // Auto-stop when max time reached
      if (now - t_start >= max_ms) {
        st = ST_DONE;
        char buf[24];
        snprintf(buf, sizeof(buf), "DONE:%d", rec_n);
        notifyStatus(buf);
      }
    }
  }

  Serial.println("Central disconnected");
  st = ST_IDLE;
  notifyStatus("IDLE");
}
