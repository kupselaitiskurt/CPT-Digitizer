/*
  GIGA_Main.ino
  Arduino GIGA R1 WiFi + GIGA Display Shield

  Screens:  Main | New Shaft | Bluetooth
  BLE:      Central — manual scan screen lets user pick from discovered devices.
            Only devices advertising the custom service UUID appear in the list.
  SD:       Saves config CSV on Save; data CSV auto-saved after BLE transfer.
  RTC:      mbed RTC shown in every top bar, updated every second.

  SD CS pin: change SD_CS_PIN if your wiring differs from pin 10.
*/

// ── Display ───────────────────────────────────────────────────────────────
#include "Arduino_H7_Video.h"
#include "Arduino_GigaDisplayTouch.h"
#include "lvgl.h"

// ── BLE ───────────────────────────────────────────────────────────────────
#include <ArduinoBLE.h>

// ── RTC ───────────────────────────────────────────────────────────────────
#include "mbed.h"
#include <mbed_mktime.h>

// ── SD ────────────────────────────────────────────────────────────────────
#include <SD.h>
#ifndef SD_CS_PIN
#define SD_CS_PIN 10
#endif
static bool sd_ready = false;

// ─────────────────────────────────────────────────────────────────────────
// BLE UUIDs — must match Rev2_Peripheral.ino
// ─────────────────────────────────────────────────────────────────────────
#define BLE_SVC_UUID   "19B10000-E8F2-537E-4F6C-D104768A1214"
#define BLE_CFG_UUID   "19B10001-E8F2-537E-4F6C-D104768A1214"
#define BLE_CMD_UUID   "19B10002-E8F2-537E-4F6C-D104768A1214"
#define BLE_DATA_UUID  "19B10003-E8F2-537E-4F6C-D104768A1214"
#define BLE_STAT_UUID  "19B10004-E8F2-537E-4F6C-D104768A1214"

// BLE connection state
enum BLEConnState { BLE_OFF, BLE_IDLE, BLE_SCANNING, BLE_CONNECTED };
static BLEConnState      ble_st = BLE_OFF;
static BLEDevice         ble_peripheral;
static BLECharacteristic ble_cfg_char;
static BLECharacteristic ble_cmd_char;
static BLECharacteristic ble_data_char;
static BLECharacteristic ble_stat_char;

// Received data buffer
static String rx_buf      = "";
static bool   rx_complete = false;
static String g_last_shaft = "";
static String g_last_tube  = "";
static String g_last_dtok  = "";

// BLE scan results — store BLEDevice so we can connect after scan stops
struct FoundDev { String name; String addr; BLEDevice dev; };
static const int MAX_FOUND = 16;
static FoundDev  found_devs[MAX_FOUND];
static int       found_n   = 0;
static int       found_sel = -1;

// ─────────────────────────────────────────────────────────────────────────
// LVGL 8/9 shims
// ─────────────────────────────────────────────────────────────────────────
#if LVGL_VERSION_MAJOR >= 9
  #define EVT_SEND(obj,code,param) lv_obj_send_event((obj),(code),(param))
  #define LV_TARGET(e)             lv_event_get_current_target_obj(e)
#else
  #define EVT_SEND(obj,code,param) lv_event_send((obj),(code),(param))
  #define LV_TARGET(e)             ((lv_obj_t*)lv_event_get_current_target(e))
#endif

// ─────────────────────────────────────────────────────────────────────────
// Display & Touch
// ─────────────────────────────────────────────────────────────────────────
Arduino_H7_Video         Display(800, 480, GigaDisplayShield);
Arduino_GigaDisplayTouch Touch;

// ─────────────────────────────────────────────────────────────────────────
// UI handles — MAIN screen
// ─────────────────────────────────────────────────────────────────────────
static lv_obj_t* scr_main       = nullptr;
static lv_obj_t* label_ble_main = nullptr;
static lv_obj_t* label_batt_main= nullptr;
static lv_obj_t* label_dt_main  = nullptr;
static lv_obj_t* list_tests     = nullptr;

// ─────────────────────────────────────────────────────────────────────────
// UI handles — NEW SHAFT screen
// ─────────────────────────────────────────────────────────────────────────
static lv_obj_t* scr_shaft        = nullptr;
static lv_obj_t* label_ble_shaft  = nullptr;
static lv_obj_t* label_batt_shaft = nullptr;
static lv_obj_t* label_dt_shaft   = nullptr;
static lv_obj_t* kb               = nullptr;

static lv_obj_t* ta_shaft         = nullptr;
static lv_obj_t* ta_tubes         = nullptr;
static lv_obj_t* ta_tubeid        = nullptr;
static lv_obj_t* cb_single        = nullptr;
static lv_obj_t* cb_multi         = nullptr;

static lv_obj_t* single_box       = nullptr;
static lv_obj_t* dd_single        = nullptr;
static lv_obj_t* single_range_box = nullptr;
static lv_obj_t* ta_min_depth     = nullptr;
static lv_obj_t* ta_max_depth     = nullptr;

static lv_obj_t* multi_box        = nullptr;
static lv_obj_t* ta_max_time      = nullptr;
static lv_obj_t* ta_interval      = nullptr;

static lv_obj_t* calendar         = nullptr;
static lv_obj_t* lbl_date         = nullptr;
static lv_obj_t* time_panel       = nullptr;
static lv_obj_t* roller_hour      = nullptr;
static lv_obj_t* roller_min       = nullptr;
static lv_obj_t* dd_format        = nullptr;
static lv_obj_t* dd_ampm          = nullptr;
static lv_obj_t* lbl_time         = nullptr;

static int  g_start_year  = 2025;
static int  g_start_month = 1;
static int  g_start_day   = 1;
static bool g_is_24h      = false;
static int  g_hour        = 7;
static int  g_minute      = 30;

// ─────────────────────────────────────────────────────────────────────────
// UI handles — BLUETOOTH screen
// ─────────────────────────────────────────────────────────────────────────
static lv_obj_t* scr_ble        = nullptr;
static lv_obj_t* ble_list       = nullptr;
static lv_obj_t* ble_status_lbl = nullptr;
static lv_obj_t* btn_ble_conn   = nullptr;
static lv_obj_t* btn_ble_disc   = nullptr;

// ─────────────────────────────────────────────────────────────────────────
// Timers
// ─────────────────────────────────────────────────────────────────────────
static lv_timer_t*   battery_timer = nullptr;
static unsigned long lastRTCTick   = 0;
static const unsigned long RTC_INTERVAL_MS = 1000;

// ─────────────────────────────────────────────────────────────────────────
// Styles
// ─────────────────────────────────────────────────────────────────────────
static lv_style_t style_btn_text;
static lv_style_t style_list_sel;
static lv_style_t style_radio_ind;
static lv_style_t style_input;
static lv_style_t style_input_focus;
static lv_style_t style_dd_list;

// ─────────────────────────────────────────────────────────────────────────
// Test records
// ─────────────────────────────────────────────────────────────────────────
struct TestRecord { String name; uint32_t t0; uint32_t t1; };
static const int MAX_TESTS = 128;
static TestRecord tests[MAX_TESTS];
static int  tests_count    = 0;
static int  selected_index = -1;
static bool test_running   = false;
static uint32_t current_start_ms = 0;
static int  run_counter    = 0;
static int  multi_test_no  = 1;
static bool g_single_run   = true;

// ─────────────────────────────────────────────────────────────────────────
// Styles init
// ─────────────────────────────────────────────────────────────────────────
static void init_styles() {
  lv_style_init(&style_btn_text);
  lv_style_set_text_font(&style_btn_text, LV_FONT_DEFAULT);

  lv_style_init(&style_list_sel);
  lv_style_set_bg_opa(&style_list_sel, LV_OPA_COVER);
  lv_style_set_bg_color(&style_list_sel, lv_color_hex(0x2A6DF2));
  lv_style_set_text_color(&style_list_sel, lv_color_white());

  lv_style_init(&style_radio_ind);
  lv_style_set_radius(&style_radio_ind, LV_RADIUS_CIRCLE);

  lv_style_init(&style_input);
  lv_style_set_bg_opa(&style_input, LV_OPA_COVER);
  lv_style_set_bg_color(&style_input, lv_color_hex(0x1D2730));
  lv_style_set_border_width(&style_input, 2);
  lv_style_set_border_color(&style_input, lv_color_hex(0x3B4652));
  lv_style_set_radius(&style_input, 10);
  lv_style_set_pad_left(&style_input, 14);
  lv_style_set_pad_right(&style_input, 14);
  lv_style_set_pad_top(&style_input, 14);
  lv_style_set_pad_bottom(&style_input, 14);
  lv_style_set_min_height(&style_input, 56);
  lv_style_set_text_color(&style_input, lv_color_hex(0xEAEAEA));

  lv_style_init(&style_input_focus);
  lv_style_set_border_color(&style_input_focus, lv_color_hex(0x2A6DF2));
  lv_style_set_border_width(&style_input_focus, 3);

  lv_style_init(&style_dd_list);
  lv_style_set_bg_opa(&style_dd_list, LV_OPA_COVER);
  lv_style_set_bg_color(&style_dd_list, lv_color_hex(0x11161B));
  lv_style_set_border_width(&style_dd_list, 1);
  lv_style_set_border_color(&style_dd_list, lv_color_hex(0x3B4652));
}

// ─────────────────────────────────────────────────────────────────────────
// RTC helpers
// ─────────────────────────────────────────────────────────────────────────
static void rtc_set_manual(int yr, int mo, int day, int hr, int mn, int sec) {
  tm t = {};
  t.tm_year = yr - 1900; t.tm_mon = mo - 1; t.tm_mday = day;
  t.tm_hour = hr;        t.tm_min = mn;      t.tm_sec  = sec;
  set_time(mktime(&t));
}

static String getLocalDateTime12hr() {
  char buf[48]; tm t;
  _rtc_localtime(time(NULL), &t, RTC_4_YEAR_LEAP_YEAR_SUPPORT);
  const char* months[] = {"Jan","Feb","Mar","Apr","May","Jun",
                          "Jul","Aug","Sep","Oct","Nov","Dec"};
  int hour = t.tm_hour; const char* ap = "AM";
  if      (hour == 0)   { hour = 12; }
  else if (hour == 12)  { ap = "PM"; }
  else if (hour > 12)   { hour -= 12; ap = "PM"; }
  snprintf(buf, sizeof(buf), "%s %02d, %04d  %02d:%02d %s",
           months[t.tm_mon], t.tm_mday, t.tm_year+1900, hour, t.tm_min, ap);
  return String(buf);
}

static void rtc_tick() {
  String now = getLocalDateTime12hr();
  if (label_dt_main)  lv_label_set_text(label_dt_main,  now.c_str());
  if (label_dt_shaft) lv_label_set_text(label_dt_shaft, now.c_str());
}

// ─────────────────────────────────────────────────────────────────────────
// General helpers
// ─────────────────────────────────────────────────────────────────────────
static int read_battery_percent() { static int f=72; return f; }

static void set_batt_label(lv_obj_t* l, int pct) {
  if (!l) return;
  char buf[24]; snprintf(buf,sizeof(buf),"Battery: %d%%",pct);
  lv_label_set_text(l,buf);
}

static void battery_tick(lv_timer_t*) {
  int pct = constrain(read_battery_percent(), 0, 100);
  set_batt_label(label_batt_main,  pct);
  set_batt_label(label_batt_shaft, pct);
}

static String sanitize_for_filename(const String& in) {
  String out; out.reserve(in.length());
  for (size_t i=0;i<in.length();++i){
    char c=in[i];
    if((c>='a'&&c<='z')||(c>='A'&&c<='Z')||(c>='0'&&c<='9')||c=='-'||c=='_') out+=c;
    else out+='_';
  }
  while(out.length()&&out[0]=='_')              out.remove(0,1);
  while(out.length()&&out[out.length()-1]=='_') out.remove(out.length()-1);
  return out.length()?out:String("NA");
}

static String build_datetime_token() {
  char date[9];
  snprintf(date,sizeof(date),"%04d%02d%02d",g_start_year,g_start_month,g_start_day);
  if (g_is_24h) {
    char t[5]; snprintf(t,sizeof(t),"%02d%02d",g_hour,g_minute);
    return String(date)+"-"+t;
  }
  int h12=g_hour%12; if(h12==0) h12=12;
  char t[10]; snprintf(t,sizeof(t),"%02d%02d%s",h12,g_minute,g_hour>=12?"pm":"am");
  return String(date)+"-"+t;
}

static String ta_text(lv_obj_t* ta) {
  if(!ta) return String();
  const char* p=lv_textarea_get_text(ta);
  return p?String(p):String();
}

// ─────────────────────────────────────────────────────────────────────────
// Alert message box — LVGL 8 compatible
// ─────────────────────────────────────────────────────────────────────────
static void mbox_alert(const char* title, const char* msg) {
#if LVGL_VERSION_MAJOR >= 9
  lv_obj_t* m = lv_msgbox_create(lv_scr_act());
  lv_msgbox_add_title(m, title);
  lv_msgbox_add_text(m, msg);
  lv_obj_t* btn = lv_msgbox_add_footer_button(m, "OK");
  lv_obj_add_event_cb(btn, [](lv_event_t* e){
    lv_obj_del_async(lv_obj_get_parent(lv_obj_get_parent((lv_obj_t*)lv_event_get_target(e))));
  }, LV_EVENT_CLICKED, NULL);
#else
  static const char* btns[] = {"OK", ""};
  lv_obj_t* m = lv_msgbox_create(lv_scr_act(), title, msg, btns, false);
  lv_obj_add_event_cb(m, [](lv_event_t* e){
    if (lv_event_get_code(e)==LV_EVENT_VALUE_CHANGED) lv_obj_del_async(LV_TARGET(e));
  }, LV_EVENT_ALL, NULL);
#endif
  lv_obj_center(m);
}

// ─────────────────────────────────────────────────────────────────────────
// SD helpers
// ─────────────────────────────────────────────────────────────────────────
static bool sd_ensure() {
  if (sd_ready) return true;
  if (!SD.begin(SD_CS_PIN)) return false;
  sd_ready = true; return true;
}

static String uniquify(const String& fname) {
  if (!SD.exists(fname.c_str())) return fname;
  int dot=fname.lastIndexOf('.');
  String base=(dot>0)?fname.substring(0,dot):fname;
  String ext =(dot>0)?fname.substring(dot):"";
  for(int i=2;i<1000;i++){
    String f2=base+"_"+String(i)+ext;
    if(!SD.exists(f2.c_str())) return f2;
  }
  return fname;
}

// ─────────────────────────────────────────────────────────────────────────
// BLE helpers
// ─────────────────────────────────────────────────────────────────────────
static String bleCharToStr(BLECharacteristic& c) {
  int n=c.valueLength(); if(n<=0) return "";
  return String((const char*)c.value(), n);
}

static void ble_update_ui() {
  const char* txt = (ble_st==BLE_CONNECTED) ? "BLE: connected"
                  : (ble_st==BLE_SCANNING)  ? "BLE: scanning"
                  : (ble_st==BLE_IDLE)      ? "BLE: idle"
                                             : "BLE: off";
  if (label_ble_main)  lv_label_set_text(label_ble_main,  txt);
  if (label_ble_shaft) lv_label_set_text(label_ble_shaft, txt);
}

static void ble_send_cmd(const char* cmd) {
  if (ble_st==BLE_CONNECTED && ble_cmd_char && ble_cmd_char.canWrite())
    ble_cmd_char.writeValue(cmd);
}

// Forward declaration (needs sanitize_for_filename defined above)
static void ble_save_data();

static bool ble_try_connect(BLEDevice& dev) {
  if (!dev.connect()) return false;
  if (!dev.discoverAttributes()) { dev.disconnect(); return false; }
  ble_cfg_char  = dev.characteristic(BLE_CFG_UUID);
  ble_cmd_char  = dev.characteristic(BLE_CMD_UUID);
  ble_data_char = dev.characteristic(BLE_DATA_UUID);
  ble_stat_char = dev.characteristic(BLE_STAT_UUID);
  if (!ble_cfg_char||!ble_cmd_char||!ble_data_char||!ble_stat_char) {
    dev.disconnect(); return false;
  }
  if (ble_data_char.canSubscribe()) ble_data_char.subscribe();
  if (ble_stat_char.canSubscribe()) ble_stat_char.subscribe();
  ble_peripheral = dev;
  return true;
}

// ── BLE scan-screen helpers ───────────────────────────────────────────────
static void ble_status_set(const char* msg) {
  if (ble_status_lbl) lv_label_set_text(ble_status_lbl, msg);
}

static void ble_list_refresh() {
  if (!ble_list) return;
  lv_obj_clean(ble_list);
  for (int i=0; i<found_n; i++) {
    String row = found_devs[i].name + "   " + found_devs[i].addr;
    lv_obj_t* btn = lv_list_add_btn(ble_list, NULL, row.c_str());
    lv_obj_add_flag(btn, LV_OBJ_FLAG_CHECKABLE);
    lv_obj_add_style(btn, &style_list_sel, LV_PART_MAIN | LV_STATE_CHECKED);
    lv_obj_add_event_cb(btn, [](lv_event_t* e){
      intptr_t idx=(intptr_t)lv_event_get_user_data(e);
      uint32_t n=lv_obj_get_child_cnt(ble_list);
      for(uint32_t j=0;j<n;j++)
        lv_obj_clear_state(lv_obj_get_child(ble_list,j), LV_STATE_CHECKED);
      lv_obj_add_state((lv_obj_t*)lv_event_get_target(e), LV_STATE_CHECKED);
      found_sel=(int)idx;
      if (btn_ble_conn) lv_obj_clear_state(btn_ble_conn, LV_STATE_DISABLED);
    }, LV_EVENT_CLICKED, (void*)(intptr_t)i);
    if (i==found_sel) lv_obj_add_state(btn, LV_STATE_CHECKED);
  }
  if (found_n==0) {
    ble_status_set("Scanning... no compatible devices found yet.");
  } else {
    char buf[56];
    snprintf(buf,sizeof(buf),"Found %d device(s). Tap one, then Connect.", found_n);
    ble_status_set(buf);
  }
}

// Drives scanning, notification polling, and disconnect detection.
static void ble_tick() {
  BLE.poll();

  if (ble_st==BLE_CONNECTED) {
    if (!ble_peripheral.connected()) {
      ble_st = BLE_IDLE;
      ble_update_ui();
      ble_status_set("Connection lost.");
      if (btn_ble_disc) lv_obj_add_state(btn_ble_disc, LV_STATE_DISABLED);
      if (btn_ble_conn) lv_obj_add_state(btn_ble_conn, LV_STATE_DISABLED);
      return;
    }
    if (ble_data_char && ble_data_char.valueUpdated()) {
      String line = bleCharToStr(ble_data_char);
      if (line=="END") {
        rx_complete = true;
        if (g_last_shaft.length()>0) ble_save_data();
      } else {
        rx_buf += line + "\n";
      }
    }
    if (ble_stat_char && ble_stat_char.valueUpdated()) {
      String s = bleCharToStr(ble_stat_char);
      if (s.startsWith("DONE:")) ble_send_cmd("SEND");
    }

  } else if (ble_st==BLE_SCANNING) {
    BLEDevice dev = BLE.available();
    if (!dev) return;
    // Deduplicate by MAC address
    String addr = dev.address();
    for (int i=0; i<found_n; i++) { if(found_devs[i].addr==addr) return; }
    if (found_n>=MAX_FOUND) return;
    String nm = dev.localName();
    if (nm.length()==0) nm = "(unnamed)";
    found_devs[found_n] = { nm, addr, dev };
    found_n++;
    ble_list_refresh();
  }
}

static void ble_init() {
  if (!BLE.begin()) return;
  ble_st = BLE_IDLE;
  ble_update_ui();
}

// Auto-save received data to SD card
static void ble_save_data() {
  if (!sd_ensure()) { mbox_alert("SD Error","SD init failed."); return; }
  String fname = sanitize_for_filename(g_last_shaft) + "-" +
                 sanitize_for_filename(g_last_tube)  + "-" +
                 g_last_dtok + "-data.csv";
  if (fname.length()>60) fname=fname.substring(0,56)+".csv";
  fname = uniquify(fname);
  File f = SD.open(fname.c_str(), FILE_WRITE);
  if (!f) { mbox_alert("SD Error","Could not create data file."); return; }
  f.print(rx_buf); f.close();
  mbox_alert("Data Saved", ("Data saved:\n"+fname).c_str());
  rx_buf=""; rx_complete=false;
}

// ─────────────────────────────────────────────────────────────────────────
// Test list helpers
// ─────────────────────────────────────────────────────────────────────────
static void add_test(const String& name, uint32_t t0, uint32_t t1) {
  if (tests_count>=MAX_TESTS) return;
  tests[tests_count++]={name,t0,t1};
}

static void clear_selection_visual() {
  if (!list_tests) return;
  uint32_t n=lv_obj_get_child_cnt(list_tests);
  for(uint32_t i=0;i<n;++i)
    lv_obj_clear_state(lv_obj_get_child(list_tests,i), LV_STATE_CHECKED);
}

static void refresh_test_list() {
  lv_obj_clean(list_tests);
  for(int i=0;i<tests_count;++i){
    lv_obj_t* it=lv_list_add_btn(list_tests, NULL, tests[i].name.c_str());
    lv_obj_add_flag(it, LV_OBJ_FLAG_CHECKABLE);
    lv_obj_add_style(it, &style_list_sel, LV_PART_MAIN|LV_STATE_CHECKED);
    lv_obj_add_event_cb(it,[](lv_event_t* e){
      lv_obj_t* btn=(lv_obj_t*)lv_event_get_target(e);
      intptr_t idx=(intptr_t)lv_event_get_user_data(e);
      if(selected_index==(int)idx){
        lv_obj_clear_state(btn,LV_STATE_CHECKED); selected_index=-1;
      } else {
        clear_selection_visual();
        lv_obj_add_state(btn,LV_STATE_CHECKED); selected_index=(int)idx;
      }
    }, LV_EVENT_CLICKED, (void*)(intptr_t)i);
    if(i==selected_index) lv_obj_add_state(it,LV_STATE_CHECKED);
  }
}

// ─────────────────────────────────────────────────────────────────────────
// Button factory
// ─────────────────────────────────────────────────────────────────────────
static lv_obj_t* make_button(lv_obj_t* parent, const char* text, lv_event_cb_t cb) {
  lv_obj_t* b=lv_btn_create(parent);
  lv_obj_set_size(b, LV_PCT(100), 72);
  lv_obj_add_event_cb(b, cb, LV_EVENT_CLICKED, nullptr);
  lv_obj_t* l=lv_label_create(b);
  lv_label_set_text(l,text);
  lv_obj_add_style(l,&style_btn_text,0);
  lv_obj_center(l);
  return b;
}

// ─────────────────────────────────────────────────────────────────────────
// Keyboard helpers
// ─────────────────────────────────────────────────────────────────────────
static void kb_set_text_mode(lv_obj_t* k) {
#if defined(LV_KEYBOARD_MODE_TEXT_LOWER)
  lv_keyboard_set_mode(k, LV_KEYBOARD_MODE_TEXT_LOWER);
#elif defined(LV_KEYBOARD_MODE_TEXT)
  lv_keyboard_set_mode(k, LV_KEYBOARD_MODE_TEXT);
#else
  (void)k;
#endif
}

static void update_single_option_ui();
static void update_runmode_ui();

static void build_visible_inputs(lv_obj_t* list[], int& count) {
  count=0;
  list[count++]=ta_shaft; list[count++]=ta_tubes; list[count++]=ta_tubeid;
  if(g_single_run){
    if(single_range_box&&!lv_obj_has_flag(single_range_box,LV_OBJ_FLAG_HIDDEN)){
      list[count++]=ta_min_depth; list[count++]=ta_max_depth;
    }
  } else { list[count++]=ta_max_time; list[count++]=ta_interval; }
  int w=0;
  for(int i=0;i<count;++i){
    if(list[i]&&!lv_obj_has_flag(list[i],LV_OBJ_FLAG_HIDDEN)) list[w++]=list[i];
  }
  count=w;
}

static bool focus_next_input(lv_obj_t* current) {
  lv_obj_t* inputs[10]; int n=0;
  build_visible_inputs(inputs,n); if(n==0) return false;
  int idx=-1;
  for(int i=0;i<n;++i){ if(inputs[i]==current){ idx=i; break; } }
  int next=(idx>=0)?((idx+1)%n):0;
  lv_obj_t* target=inputs[next];
  lv_group_focus_obj(target);
  lv_obj_add_state(target,LV_STATE_FOCUSED);
  if(kb){ lv_keyboard_set_textarea(kb,target);
          lv_obj_clear_flag(kb,LV_OBJ_FLAG_HIDDEN);
          lv_obj_move_foreground(kb); }
  EVT_SEND(target,LV_EVENT_FOCUSED,NULL);
  return true;
}

static void on_textarea_focus(lv_event_t* e) {
  if(!kb) return;
  lv_event_code_t code=lv_event_get_code(e);
  lv_obj_t* ta=(lv_obj_t*)lv_event_get_target(e);
  if(code==LV_EVENT_FOCUSED){
    lv_keyboard_set_textarea(kb,ta);
    lv_obj_clear_flag(kb,LV_OBJ_FLAG_HIDDEN);
    lv_obj_move_foreground(kb);
  } else if(code==LV_EVENT_DEFOCUSED){
    if(lv_keyboard_get_textarea(kb)==ta) lv_keyboard_set_textarea(kb,NULL);
  }
}

// ─────────────────────────────────────────────────────────────────────────
// Button callbacks
// ─────────────────────────────────────────────────────────────────────────
static void on_new_shaft(lv_event_t*) {
  lv_scr_load_anim(scr_shaft, LV_SCR_LOAD_ANIM_MOVE_LEFT, 200, 0, false);
}

static void on_start(lv_event_t*) {
  if(test_running) return;
  if(ble_st!=BLE_CONNECTED){
    mbox_alert("Not Connected","Use Bluetooth button to connect a device first.");
    return;
  }
  rx_buf=""; rx_complete=false;
  ble_send_cmd("START");
  test_running=true; current_start_ms=millis();
  add_test(String("Run ")+(++run_counter)+" (running)", current_start_ms, 0);
  refresh_test_list();
}

static void on_stop(lv_event_t*) {
  if(!test_running) return;
  test_running=false;
  ble_send_cmd("STOP");
  if(tests_count>0){
    tests[tests_count-1].name.replace(" (running)","");
    tests[tests_count-1].t1=millis();
    refresh_test_list();
  }
}

static void on_graph(lv_event_t*) {
  if(rx_buf.isEmpty()){ mbox_alert("No Data","No data received yet."); return; }
  int lines=0;
  for(size_t i=0;i<rx_buf.length();i++) if(rx_buf[i]=='\n') lines++;
  char buf[64];
  snprintf(buf,sizeof(buf),"%d data records in buffer.", lines>0?lines-1:0);
  mbox_alert("Graph (stub)", buf);
}

static void on_export(lv_event_t*) {
  if(ble_st!=BLE_CONNECTED){
    mbox_alert("Not Connected","Connect a device first.");
    return;
  }
  if(rx_complete&&rx_buf.length()>0){
    if(g_last_shaft.length()>0) ble_save_data();
    else mbox_alert("No Config","Save a shaft config before exporting.");
  } else {
    ble_send_cmd("SEND");
    mbox_alert("Export","Requesting data from device...");
  }
}

static void on_delete(lv_event_t*) {
  if(selected_index<0) return;
  for(int i=selected_index;i<tests_count-1;++i) tests[i]=tests[i+1];
  tests_count--; selected_index=-1; refresh_test_list();
}

static void on_save(lv_event_t*) {
  String shaft=sanitize_for_filename(ta_text(ta_shaft));
  String tube =sanitize_for_filename(ta_text(ta_tubeid));
  if(shaft=="NA"||tube=="NA"){
    mbox_alert("Missing Data","Enter Shaft ID and Tube ID before saving.");
    return;
  }
  String dtok=build_datetime_token();
  g_last_shaft=shaft; g_last_tube=tube; g_last_dtok=dtok;

  if(!sd_ensure()){ mbox_alert("SD Error","SD init failed."); return; }
  String fname=shaft+"-"+tube+"-"+dtok+"-set";
  if(!g_single_run) fname+="-"+String(multi_test_no);
  fname+=".csv";
  if(fname.length()>64) fname=fname.substring(0,60)+".csv";
  if(g_single_run) fname=uniquify(fname);

  File f=SD.open(fname.c_str(), FILE_WRITE);
  if(!f){ mbox_alert("Save Failed","Could not create config file."); return; }
  f.println("shaft_id,tube_id,date_time_token,mode,notes");
  f.print(shaft); f.print(','); f.print(tube); f.print(',');
  f.print(dtok);  f.print(',');
  f.print(g_single_run?"Single":"Multi"); f.print(',');
  if(!g_single_run){ f.print("test_no="); f.print(multi_test_no); }
  f.println(); f.close();
  if(!g_single_run) multi_test_no++;

  if(ble_st==BLE_CONNECTED && ble_cfg_char && ble_cfg_char.canWrite()){
    String cfg="SHAFT:"+shaft+",TUBE:"+tube;
    cfg+=",MODE:"+String(g_single_run?"Single":"Multi");
    String iv=ta_text(ta_interval), mt=ta_text(ta_max_time);
    if(iv.length()>0) cfg+=",INTERVAL:"+iv;
    if(mt.length()>0) cfg+=",MAXTIME:"+mt;
    ble_cfg_char.writeValue(cfg.c_str());
  }
  mbox_alert("Saved", ("Config saved: "+fname).c_str());
}

// ── BLE screen callbacks ──────────────────────────────────────────────────
static void on_ble_scan_btn(lv_event_t*) {
  found_n=0; found_sel=-1;
  ble_list_refresh();
  if(btn_ble_conn) lv_obj_add_state(btn_ble_conn, LV_STATE_DISABLED);
  BLE.stopScan();
  // Scan only for devices advertising our service UUID —
  // phones, earbuds, and unrelated equipment are invisible.
  BLE.scanForUuid(BLE_SVC_UUID);
  ble_st=BLE_SCANNING;
  ble_update_ui();
  ble_status_set("Scanning for compatible devices...");
}

static void on_ble_conn_btn(lv_event_t*) {
  if(found_sel<0||found_sel>=found_n) return;
  BLE.stopScan();
  ble_st=BLE_IDLE;
  ble_update_ui();
  ble_status_set("Connecting...");

  if(ble_try_connect(found_devs[found_sel].dev)){
    ble_st=BLE_CONNECTED;
    ble_update_ui();
    String msg="Connected: "+found_devs[found_sel].name
               +"  ("+found_devs[found_sel].addr+")";
    ble_status_set(msg.c_str());
    if(btn_ble_disc) lv_obj_clear_state(btn_ble_disc, LV_STATE_DISABLED);
    if(btn_ble_conn) lv_obj_add_state(btn_ble_conn,   LV_STATE_DISABLED);
  } else {
    ble_st=BLE_IDLE;
    ble_update_ui();
    ble_status_set("Connection failed. Scan and try again.");
  }
}

static void on_ble_disc_btn(lv_event_t*) {
  if(ble_st==BLE_CONNECTED) ble_peripheral.disconnect();
  BLE.stopScan();
  ble_st=BLE_IDLE;
  ble_update_ui();
  ble_status_set("Disconnected.");
  if(btn_ble_disc) lv_obj_add_state(btn_ble_disc, LV_STATE_DISABLED);
  if(btn_ble_conn) lv_obj_add_state(btn_ble_conn, LV_STATE_DISABLED);
  found_sel=-1;
}

static void on_ble_btn(lv_event_t*) {
  lv_scr_load_anim(scr_ble, LV_SCR_LOAD_ANIM_MOVE_LEFT, 200, 0, false);
  on_ble_scan_btn(nullptr); // auto-start scan when screen opens
}

// ─────────────────────────────────────────────────────────────────────────
// Visibility helpers — New Shaft screen
// ─────────────────────────────────────────────────────────────────────────
static void update_single_option_ui() {
  if(!single_range_box||!dd_single) return;
  uint32_t sel=lv_dropdown_get_selected(dd_single);
  if(sel==1) lv_obj_clear_flag(single_range_box, LV_OBJ_FLAG_HIDDEN);
  else       lv_obj_add_flag(single_range_box,   LV_OBJ_FLAG_HIDDEN);
}

static void update_runmode_ui() {
  if(!single_box||!multi_box) return;
  if(g_single_run){
    lv_obj_clear_flag(single_box, LV_OBJ_FLAG_HIDDEN);
    lv_obj_add_flag(multi_box,    LV_OBJ_FLAG_HIDDEN);
    update_single_option_ui();
  } else {
    lv_obj_add_flag(single_box,   LV_OBJ_FLAG_HIDDEN);
    lv_obj_clear_flag(multi_box,  LV_OBJ_FLAG_HIDDEN);
  }
}

// ─────────────────────────────────────────────────────────────────────────
// Time-picker helpers
// ─────────────────────────────────────────────────────────────────────────
static void update_time_label() {
  char buf[32];
  if(g_is_24h){ snprintf(buf,sizeof(buf),"Selected: %02d:%02d",g_hour,g_minute); }
  else {
    int h12=g_hour%12; if(h12==0) h12=12;
    snprintf(buf,sizeof(buf),"Selected: %02d:%02d %s",h12,g_minute,g_hour>=12?"pm":"am");
  }
  lv_label_set_text(lbl_time,buf);
}

static void time_format_apply_to_widgets() {
  if(g_is_24h){
    static const char* h24="00\n01\n02\n03\n04\n05\n06\n07\n08\n09\n10\n11\n"
                            "12\n13\n14\n15\n16\n17\n18\n19\n20\n21\n22\n23";
    lv_roller_set_options(roller_hour,h24,LV_ROLLER_MODE_NORMAL);
    lv_roller_set_selected(roller_hour,g_hour,LV_ANIM_OFF);
  } else {
    static const char* h12="01\n02\n03\n04\n05\n06\n07\n08\n09\n10\n11\n12";
    lv_roller_set_options(roller_hour,h12,LV_ROLLER_MODE_NORMAL);
    int h=g_hour%12; if(h==0) h=12;
    lv_roller_set_selected(roller_hour,h-1,LV_ANIM_OFF);
    lv_dropdown_set_selected(dd_ampm,(g_hour>=12)?1:0);
  }
}

static void time_format_changed() {
  g_is_24h=(lv_dropdown_get_selected(dd_format)==1);
  if(g_is_24h) lv_obj_add_state(dd_ampm,   LV_STATE_DISABLED);
  else         lv_obj_clear_state(dd_ampm,  LV_STATE_DISABLED);
  time_format_apply_to_widgets(); update_time_label();
}

static void time_ampm_changed() {
  bool want_pm=(lv_dropdown_get_selected(dd_ampm)==1);
  if(!g_is_24h){
    if( want_pm && g_hour<12)  g_hour+=12;
    if(!want_pm && g_hour>=12) g_hour-=12;
  }
  update_time_label();
}

static void time_hour_changed() {
  int sel=lv_roller_get_selected(roller_hour);
  if(g_is_24h){ g_hour=sel; }
  else {
    int h12=sel+1; bool pm=(lv_dropdown_get_selected(dd_ampm)==1);
    g_hour=(h12%12)+(pm?12:0);
  }
  update_time_label();
}

static void time_min_changed() {
  g_minute=lv_roller_get_selected(roller_min); update_time_label();
}

// ─────────────────────────────────────────────────────────────────────────
// BLUETOOTH screen
// ─────────────────────────────────────────────────────────────────────────
static void build_ble_screen() {
  scr_ble = lv_obj_create(NULL);
  lv_obj_remove_style_all(scr_ble);
  lv_obj_set_style_bg_color(scr_ble, lv_color_hex(0x101418), 0);
  lv_obj_set_style_bg_opa(scr_ble, LV_OPA_COVER, 0);
  lv_obj_set_scroll_dir(scr_ble, LV_DIR_NONE);
  lv_obj_clear_flag(scr_ble, LV_OBJ_FLAG_SCROLLABLE);
  lv_obj_set_flex_flow(scr_ble, LV_FLEX_FLOW_COLUMN);

  // ── Top bar ──────────────────────────────────────────────────────────────
  lv_obj_t* topbar = lv_obj_create(scr_ble);
  lv_obj_remove_style_all(topbar);
  lv_obj_set_size(topbar, LV_PCT(100), 56);
  lv_obj_set_flex_flow(topbar, LV_FLEX_FLOW_ROW);
  lv_obj_set_style_pad_all(topbar, 16, 0);
  lv_obj_set_flex_align(topbar, LV_FLEX_ALIGN_SPACE_BETWEEN,
                         LV_FLEX_ALIGN_CENTER, LV_FLEX_ALIGN_CENTER);

  lv_obj_t* title = lv_label_create(topbar);
  lv_label_set_text(title, "Bluetooth Devices");
  lv_obj_set_style_text_color(title, lv_color_hex(0xEAEAEA), 0);

  lv_obj_t* btn_back = lv_btn_create(topbar);
  lv_obj_set_size(btn_back, 80, 40);
  lv_obj_add_event_cb(btn_back, [](lv_event_t*){
    BLE.stopScan();
    if (ble_st==BLE_SCANNING) { ble_st=BLE_IDLE; ble_update_ui(); }
    lv_scr_load_anim(scr_main, LV_SCR_LOAD_ANIM_MOVE_RIGHT, 200, 0, false);
  }, LV_EVENT_CLICKED, NULL);
  { lv_obj_t* l=lv_label_create(btn_back); lv_label_set_text(l,"Back"); lv_obj_center(l); }

  // ── Status label ─────────────────────────────────────────────────────────
  ble_status_lbl = lv_label_create(scr_ble);
  lv_label_set_text(ble_status_lbl, "Press Scan to discover nearby devices.");
  lv_obj_set_style_text_color(ble_status_lbl, lv_color_hex(0xA0B0C0), 0);
  lv_obj_set_style_pad_left(ble_status_lbl, 16, 0);
  lv_obj_set_style_pad_top(ble_status_lbl, 8, 0);
  lv_label_set_long_mode(ble_status_lbl, LV_LABEL_LONG_WRAP);
  lv_obj_set_width(ble_status_lbl, LV_PCT(100));

  // ── Device list ──────────────────────────────────────────────────────────
  ble_list = lv_list_create(scr_ble);
  lv_obj_set_width(ble_list, LV_PCT(100));
  lv_obj_set_flex_grow(ble_list, 1);
  lv_obj_set_style_bg_color(ble_list, lv_color_hex(0x182026), 0);
  lv_obj_set_style_bg_opa(ble_list, LV_OPA_COVER, 0);
  lv_obj_set_scrollbar_mode(ble_list, LV_SCROLLBAR_MODE_AUTO);

  // ── Bottom action row ────────────────────────────────────────────────────
  lv_obj_t* acts = lv_obj_create(scr_ble);
  lv_obj_remove_style_all(acts);
  lv_obj_set_size(acts, LV_PCT(100), 76);
  lv_obj_set_flex_flow(acts, LV_FLEX_FLOW_ROW);
  lv_obj_set_style_pad_all(acts, 12, 0);
  lv_obj_set_style_pad_gap(acts, 12, 0);
  lv_obj_set_flex_align(acts, LV_FLEX_ALIGN_SPACE_EVENLY,
                         LV_FLEX_ALIGN_CENTER, LV_FLEX_ALIGN_CENTER);

  lv_obj_t* btn_scan = lv_btn_create(acts);
  lv_obj_set_size(btn_scan, LV_PCT(30), 52);
  lv_obj_add_event_cb(btn_scan, on_ble_scan_btn, LV_EVENT_CLICKED, NULL);
  { lv_obj_t* l=lv_label_create(btn_scan); lv_label_set_text(l,"Scan"); lv_obj_center(l); }

  btn_ble_conn = lv_btn_create(acts);
  lv_obj_set_size(btn_ble_conn, LV_PCT(30), 52);
  lv_obj_add_state(btn_ble_conn, LV_STATE_DISABLED);
  lv_obj_add_event_cb(btn_ble_conn, on_ble_conn_btn, LV_EVENT_CLICKED, NULL);
  { lv_obj_t* l=lv_label_create(btn_ble_conn); lv_label_set_text(l,"Connect"); lv_obj_center(l); }

  btn_ble_disc = lv_btn_create(acts);
  lv_obj_set_size(btn_ble_disc, LV_PCT(30), 52);
  lv_obj_add_state(btn_ble_disc, LV_STATE_DISABLED);
  lv_obj_add_event_cb(btn_ble_disc, on_ble_disc_btn, LV_EVENT_CLICKED, NULL);
  { lv_obj_t* l=lv_label_create(btn_ble_disc); lv_label_set_text(l,"Disconnect"); lv_obj_center(l); }
}

// ─────────────────────────────────────────────────────────────────────────
// MAIN screen
// ─────────────────────────────────────────────────────────────────────────
static void build_main_screen() {
  scr_main = lv_obj_create(NULL);
  lv_obj_remove_style_all(scr_main);
  lv_obj_set_style_bg_color(scr_main, lv_color_hex(0x101418), 0);
  lv_obj_set_style_bg_opa(scr_main, LV_OPA_COVER, 0);
  lv_obj_set_scroll_dir(scr_main, LV_DIR_NONE);
  lv_obj_set_scrollbar_mode(scr_main, LV_SCROLLBAR_MODE_OFF);
  lv_obj_clear_flag(scr_main, LV_OBJ_FLAG_SCROLLABLE);
  lv_obj_set_flex_flow(scr_main, LV_FLEX_FLOW_COLUMN);

  // Top bar
  lv_obj_t* topbar = lv_obj_create(scr_main);
  lv_obj_remove_style_all(topbar);
  lv_obj_set_size(topbar, LV_PCT(100), 56);
  lv_obj_set_flex_flow(topbar, LV_FLEX_FLOW_ROW);
  lv_obj_set_style_pad_all(topbar, 16, 0);
  lv_obj_set_flex_align(topbar, LV_FLEX_ALIGN_SPACE_BETWEEN,
                         LV_FLEX_ALIGN_CENTER, LV_FLEX_ALIGN_CENTER);

  label_dt_main = lv_label_create(topbar);
  lv_label_set_text(label_dt_main, "—");
  lv_obj_set_style_text_color(label_dt_main, lv_color_hex(0xEAEAEA), 0);

  label_ble_main = lv_label_create(topbar);
  lv_label_set_text(label_ble_main, "BLE: off");
  lv_obj_set_style_text_color(label_ble_main, lv_color_hex(0xEAEAEA), 0);

  label_batt_main = lv_label_create(topbar);
  lv_label_set_text(label_batt_main, "Battery: --%");
  lv_obj_set_style_text_color(label_batt_main, lv_color_hex(0xEAEAEA), 0);

  // Body
  lv_obj_t* body = lv_obj_create(scr_main);
  lv_obj_remove_style_all(body);
  lv_obj_set_width(body, LV_PCT(100));
  lv_obj_set_flex_flow(body, LV_FLEX_FLOW_ROW);
  lv_obj_set_style_pad_all(body, 16, 0);
  lv_obj_set_style_pad_gap(body, 16, 0);
  lv_obj_set_height(body, LV_SIZE_CONTENT);
  lv_obj_set_flex_grow(body, 1);

  // Left pane
  lv_obj_t* left = lv_obj_create(body);
  lv_obj_remove_style_all(left);
  lv_obj_set_size(left, LV_PCT(35), LV_PCT(100));
  lv_obj_set_flex_flow(left, LV_FLEX_FLOW_COLUMN);
  lv_obj_set_style_pad_gap(left, 10, 0);
  lv_obj_set_scroll_dir(left, LV_DIR_VER);
  lv_obj_set_scrollbar_mode(left, LV_SCROLLBAR_MODE_AUTO);
  lv_obj_clear_flag(left, LV_OBJ_FLAG_SCROLL_ELASTIC);

  make_button(left, "New Shaft",  on_new_shaft);
  make_button(left, "Bluetooth",  on_ble_btn);
  make_button(left, "Start",      on_start);
  make_button(left, "Stop",       on_stop);
  make_button(left, "Graph",      on_graph);
  make_button(left, "Export",     on_export);
  make_button(left, "Delete",     on_delete);

  // Right pane — test list
  lv_obj_t* right = lv_obj_create(body);
  lv_obj_remove_style_all(right);
  lv_obj_set_size(right, LV_PCT(65), LV_PCT(100));
  lv_obj_set_flex_flow(right, LV_FLEX_FLOW_COLUMN);
  lv_obj_set_style_pad_gap(right, 8, 0);
  lv_obj_set_scroll_dir(right, LV_DIR_VER);
  lv_obj_set_scrollbar_mode(right, LV_SCROLLBAR_MODE_AUTO);
  lv_obj_clear_flag(right, LV_OBJ_FLAG_SCROLL_ELASTIC);

  lv_obj_t* listTitle = lv_label_create(right);
  lv_label_set_text(listTitle, "Completed Tests");
  lv_obj_set_style_text_color(listTitle, lv_color_hex(0xEAEAEA), 0);

  list_tests = lv_list_create(right);
  lv_obj_set_width(list_tests, LV_PCT(100));
  lv_obj_set_style_bg_color(list_tests, lv_color_hex(0x182026), 0);
  lv_obj_set_style_bg_opa(list_tests, LV_OPA_COVER, 0);
  lv_obj_set_flex_grow(list_tests, 1);
  lv_obj_set_scrollbar_mode(list_tests, LV_SCROLLBAR_MODE_AUTO);

  add_test("Demo Test 1", 0, 0);
  add_test("Demo Test 2", 0, 0);
  refresh_test_list();
}

// ─────────────────────────────────────────────────────────────────────────
// NEW SHAFT screen
// ─────────────────────────────────────────────────────────────────────────
static void build_shaft_screen() {
  scr_shaft = lv_obj_create(NULL);
  lv_obj_remove_style_all(scr_shaft);
  lv_obj_set_style_bg_color(scr_shaft, lv_color_hex(0x101418), 0);
  lv_obj_set_style_bg_opa(scr_shaft, LV_OPA_COVER, 0);
  lv_obj_set_scroll_dir(scr_shaft, LV_DIR_NONE);
  lv_obj_clear_flag(scr_shaft, LV_OBJ_FLAG_SCROLLABLE);
  lv_obj_set_flex_flow(scr_shaft, LV_FLEX_FLOW_COLUMN);

  // Top bar
  lv_obj_t* topbar = lv_obj_create(scr_shaft);
  lv_obj_remove_style_all(topbar);
  lv_obj_set_size(topbar, LV_PCT(100), 56);
  lv_obj_set_flex_flow(topbar, LV_FLEX_FLOW_ROW);
  lv_obj_set_style_pad_all(topbar, 16, 0);
  lv_obj_set_flex_align(topbar, LV_FLEX_ALIGN_SPACE_BETWEEN,
                         LV_FLEX_ALIGN_CENTER, LV_FLEX_ALIGN_CENTER);

  label_dt_shaft = lv_label_create(topbar);
  lv_label_set_text(label_dt_shaft, "—");
  lv_obj_set_style_text_color(label_dt_shaft, lv_color_hex(0xEAEAEA), 0);

  label_ble_shaft = lv_label_create(topbar);
  lv_label_set_text(label_ble_shaft, "BLE: off");
  lv_obj_set_style_text_color(label_ble_shaft, lv_color_hex(0xEAEAEA), 0);

  label_batt_shaft = lv_label_create(topbar);
  lv_label_set_text(label_batt_shaft, "Battery: --%");
  lv_obj_set_style_text_color(label_batt_shaft, lv_color_hex(0xEAEAEA), 0);

  // Scrollable form
  lv_obj_t* form = lv_obj_create(scr_shaft);
  lv_obj_remove_style_all(form);
  lv_obj_set_flex_flow(form, LV_FLEX_FLOW_COLUMN);
  lv_obj_set_style_pad_all(form, 16, 0);
  lv_obj_set_style_pad_gap(form, 12, 0);
  lv_obj_set_width(form, LV_PCT(100));
  lv_obj_set_flex_grow(form, 1);
  lv_obj_set_scroll_dir(form, LV_DIR_VER);

  #define MAKE_ROW(parent) ({ \
    lv_obj_t* r=lv_obj_create(parent); lv_obj_remove_style_all(r); \
    lv_obj_set_flex_flow(r,LV_FLEX_FLOW_ROW); \
    lv_obj_set_style_pad_all(r,0,0); lv_obj_set_style_pad_gap(r,12,0); \
    lv_obj_set_width(r,LV_PCT(100)); lv_obj_set_height(r,LV_SIZE_CONTENT); r; })

  #define MAKE_LBL(parent,txt) ({ \
    lv_obj_t* l=lv_label_create(parent); lv_label_set_text(l,txt); \
    lv_obj_set_style_text_color(l,lv_color_hex(0xEAEAEA),0); l; })

  #define WIRE_TA(ta) \
    lv_obj_add_style(ta,&style_input,0); \
    lv_obj_add_style(ta,&style_input_focus,LV_STATE_FOCUSED); \
    lv_obj_add_event_cb(ta,on_textarea_focus,LV_EVENT_FOCUSED,NULL); \
    lv_obj_add_event_cb(ta,on_textarea_focus,LV_EVENT_DEFOCUSED,NULL)

  { lv_obj_t* r=MAKE_ROW(form); MAKE_LBL(r,"Shaft ID:");
    ta_shaft=lv_textarea_create(r); lv_obj_set_width(ta_shaft,LV_PCT(60));
    lv_textarea_set_one_line(ta_shaft,true);
    lv_textarea_set_placeholder_text(ta_shaft,"e.g. SH-001"); WIRE_TA(ta_shaft); }

  { lv_obj_t* r=MAKE_ROW(form); MAKE_LBL(r,"Number of Tubes:");
    ta_tubes=lv_textarea_create(r); lv_obj_set_width(ta_tubes,LV_PCT(30));
    lv_textarea_set_one_line(ta_tubes,true);
    lv_textarea_set_placeholder_text(ta_tubes,"e.g. 3"); WIRE_TA(ta_tubes); }

  { lv_obj_t* r=MAKE_ROW(form); MAKE_LBL(r,"Tube ID:");
    ta_tubeid=lv_textarea_create(r); lv_obj_set_width(ta_tubeid,LV_PCT(60));
    lv_textarea_set_one_line(ta_tubeid,true);
    lv_textarea_set_placeholder_text(ta_tubeid,"e.g. T-101"); WIRE_TA(ta_tubeid); }

  { lv_obj_t* r=MAKE_ROW(form); MAKE_LBL(r,"Run Mode:");
    cb_single=lv_checkbox_create(r); lv_checkbox_set_text(cb_single,"Single");
    lv_obj_add_style(cb_single,&style_radio_ind,LV_PART_INDICATOR);
    lv_obj_set_style_text_color(cb_single,lv_color_hex(0xEAEAEA),LV_PART_MAIN);
    cb_multi=lv_checkbox_create(r);  lv_checkbox_set_text(cb_multi,"Multi");
    lv_obj_add_style(cb_multi,&style_radio_ind,LV_PART_INDICATOR);
    lv_obj_set_style_text_color(cb_multi,lv_color_hex(0xEAEAEA),LV_PART_MAIN);
    lv_obj_add_state(cb_single,LV_STATE_CHECKED); g_single_run=true; }

  // Single section
  single_box=lv_obj_create(form); lv_obj_remove_style_all(single_box);
  lv_obj_set_flex_flow(single_box,LV_FLEX_FLOW_COLUMN);
  lv_obj_set_style_pad_all(single_box,0,0); lv_obj_set_style_pad_gap(single_box,12,0);
  lv_obj_set_width(single_box,LV_PCT(100)); lv_obj_set_height(single_box,LV_SIZE_CONTENT);

  { lv_obj_t* r=MAKE_ROW(single_box); MAKE_LBL(r,"Single Option:");
    dd_single=lv_dropdown_create(r); lv_dropdown_set_options(dd_single,"Full Length\nRange");
    lv_obj_set_width(dd_single,LV_PCT(40));
    lv_obj_add_style(dd_single,&style_input,0);
    lv_obj_add_style(dd_single,&style_input_focus,LV_STATE_FOCUSED);
#if LVGL_VERSION_MAJOR < 9
    lv_obj_t* ddl=lv_dropdown_get_list(dd_single);
    if(ddl) lv_obj_add_style(ddl,&style_dd_list,0);
#endif
  }

  single_range_box=lv_obj_create(single_box); lv_obj_remove_style_all(single_range_box);
  lv_obj_set_flex_flow(single_range_box,LV_FLEX_FLOW_COLUMN);
  lv_obj_set_style_pad_all(single_range_box,0,0);
  lv_obj_set_style_pad_gap(single_range_box,12,0);
  lv_obj_set_width(single_range_box,LV_PCT(100));
  lv_obj_set_height(single_range_box,LV_SIZE_CONTENT);

  { lv_obj_t* r=MAKE_ROW(single_range_box); MAKE_LBL(r,"Minimum Depth (ft):");
    ta_min_depth=lv_textarea_create(r); lv_obj_set_width(ta_min_depth,LV_PCT(30));
    lv_textarea_set_one_line(ta_min_depth,true);
    lv_textarea_set_placeholder_text(ta_min_depth,"e.g. 10"); WIRE_TA(ta_min_depth); }

  { lv_obj_t* r=MAKE_ROW(single_range_box); MAKE_LBL(r,"Maximum Depth (ft):");
    ta_max_depth=lv_textarea_create(r); lv_obj_set_width(ta_max_depth,LV_PCT(30));
    lv_textarea_set_one_line(ta_max_depth,true);
    lv_textarea_set_placeholder_text(ta_max_depth,"e.g. 150"); WIRE_TA(ta_max_depth); }

  // Multi section
  multi_box=lv_obj_create(form); lv_obj_remove_style_all(multi_box);
  lv_obj_set_flex_flow(multi_box,LV_FLEX_FLOW_COLUMN);
  lv_obj_set_style_pad_all(multi_box,0,0); lv_obj_set_style_pad_gap(multi_box,12,0);
  lv_obj_set_width(multi_box,LV_PCT(100)); lv_obj_set_height(multi_box,LV_SIZE_CONTENT);

  { lv_obj_t* r=MAKE_ROW(multi_box); MAKE_LBL(r,"Max Test Time (hrs):");
    ta_max_time=lv_textarea_create(r); lv_obj_set_width(ta_max_time,LV_PCT(30));
    lv_textarea_set_one_line(ta_max_time,true);
    lv_textarea_set_placeholder_text(ta_max_time,"e.g. 72"); WIRE_TA(ta_max_time); }

  { lv_obj_t* r=MAKE_ROW(multi_box); MAKE_LBL(r,"Interval (hrs):");
    ta_interval=lv_textarea_create(r); lv_obj_set_width(ta_interval,LV_PCT(30));
    lv_textarea_set_one_line(ta_interval,true);
    lv_textarea_set_placeholder_text(ta_interval,"e.g. 1"); WIRE_TA(ta_interval); }

  // Calendar + Time row
  lv_obj_t* sched_row=MAKE_ROW(form); lv_obj_set_style_pad_gap(sched_row,16,0);

  lv_obj_t* cal_panel=lv_obj_create(sched_row); lv_obj_remove_style_all(cal_panel);
  lv_obj_set_flex_flow(cal_panel,LV_FLEX_FLOW_COLUMN);
  lv_obj_set_style_pad_all(cal_panel,0,0); lv_obj_set_style_pad_gap(cal_panel,8,0);
  lv_obj_set_width(cal_panel,260); lv_obj_set_height(cal_panel,LV_SIZE_CONTENT);

  calendar=lv_calendar_create(cal_panel); lv_obj_set_size(calendar,260,240);
#if LV_USE_CALENDAR_HEADER_DROPDOWN
  lv_calendar_add_header_dropdown(calendar);
#elif LV_USE_CALENDAR_HEADER_ARROW
  lv_calendar_add_header_arrow(calendar);
#endif
  lv_calendar_set_today_date(calendar,2025,1,1);
  lv_calendar_set_month_shown(calendar,2025,1);
  lv_obj_add_event_cb(calendar,[](lv_event_t* e){
    if(lv_event_get_code(e)==LV_EVENT_VALUE_CHANGED){
      lv_calendar_date_t d;
      if(lv_calendar_get_pressed_date(calendar,&d)){
        g_start_year=d.year; g_start_month=d.month; g_start_day=d.day;
        char buf[48];
        snprintf(buf,sizeof(buf),"Selected date: %02d/%02d/%04d",d.month,d.day,d.year);
        lv_label_set_text(lbl_date,buf);
      }
    }
  }, LV_EVENT_ALL, NULL);

  lbl_date=lv_label_create(cal_panel);
  lv_label_set_text(lbl_date,"Selected date: --/--/----");
  lv_obj_set_style_text_color(lbl_date,lv_color_hex(0xEAEAEA),0);

  time_panel=lv_obj_create(sched_row); lv_obj_remove_style_all(time_panel);
  lv_obj_set_flex_flow(time_panel,LV_FLEX_FLOW_COLUMN);
  lv_obj_set_style_pad_all(time_panel,0,0); lv_obj_set_style_pad_gap(time_panel,8,0);
  lv_obj_set_width(time_panel,220); lv_obj_set_height(time_panel,LV_SIZE_CONTENT);

  lv_obj_t* trow1=MAKE_ROW(time_panel); lv_obj_set_style_pad_gap(trow1,12,0);
  roller_hour=lv_roller_create(trow1); lv_roller_set_visible_row_count(roller_hour,3);
  lv_obj_set_width(roller_hour,80);
  lv_roller_set_options(roller_hour,"01\n02\n03\n04\n05\n06\n07\n08\n09\n10\n11\n12",LV_ROLLER_MODE_NORMAL);
  lv_roller_set_selected(roller_hour,6,LV_ANIM_OFF);
  lv_obj_add_event_cb(roller_hour,[](lv_event_t*){ time_hour_changed(); },LV_EVENT_VALUE_CHANGED,NULL);

  roller_min=lv_roller_create(trow1); lv_roller_set_visible_row_count(roller_min,3);
  lv_obj_set_width(roller_min,80);
  lv_roller_set_options(roller_min,
    "00\n01\n02\n03\n04\n05\n06\n07\n08\n09\n10\n11\n12\n13\n14\n15\n16\n17\n18\n19\n20\n"
    "21\n22\n23\n24\n25\n26\n27\n28\n29\n30\n31\n32\n33\n34\n35\n36\n37\n38\n39\n40\n"
    "41\n42\n43\n44\n45\n46\n47\n48\n49\n50\n51\n52\n53\n54\n55\n56\n57\n58\n59",
    LV_ROLLER_MODE_NORMAL);
  lv_roller_set_selected(roller_min,30,LV_ANIM_OFF);
  lv_obj_add_event_cb(roller_min,[](lv_event_t*){ time_min_changed(); },LV_EVENT_VALUE_CHANGED,NULL);

  lv_obj_t* trow2=MAKE_ROW(time_panel); lv_obj_set_style_pad_gap(trow2,12,0);
  dd_format=lv_dropdown_create(trow2); lv_dropdown_set_options(dd_format,"12\n24");
  lv_obj_set_width(dd_format,80); lv_dropdown_set_selected(dd_format,0);
  lv_obj_add_event_cb(dd_format,[](lv_event_t*){ time_format_changed(); },LV_EVENT_VALUE_CHANGED,NULL);

  dd_ampm=lv_dropdown_create(trow2); lv_dropdown_set_options(dd_ampm,"am\npm");
  lv_obj_set_width(dd_ampm,80); lv_dropdown_set_selected(dd_ampm,0);
  lv_obj_add_event_cb(dd_ampm,[](lv_event_t*){ time_ampm_changed(); },LV_EVENT_VALUE_CHANGED,NULL);

  lbl_time=lv_label_create(time_panel);
  lv_obj_set_style_text_color(lbl_time,lv_color_hex(0xEAEAEA),0);
  update_time_label();

  // Save + Back
  lv_obj_t* actions=MAKE_ROW(form); lv_obj_set_style_pad_gap(actions,12,0);

  lv_obj_t* btn_save=lv_btn_create(actions);
  lv_obj_set_size(btn_save,LV_PCT(50),56);
  lv_obj_add_event_cb(btn_save,on_save,LV_EVENT_CLICKED,NULL);
  { lv_obj_t* l=lv_label_create(btn_save); lv_label_set_text(l,"Save"); lv_obj_center(l); }

  lv_obj_t* btn_back=lv_btn_create(actions);
  lv_obj_set_size(btn_back,LV_PCT(50),56);
  lv_obj_add_event_cb(btn_back,[](lv_event_t*){
    lv_scr_load_anim(scr_main,LV_SCR_LOAD_ANIM_MOVE_RIGHT,200,0,false);
  },LV_EVENT_CLICKED,NULL);
  { lv_obj_t* l=lv_label_create(btn_back); lv_label_set_text(l,"Back"); lv_obj_center(l); }

  // Keyboard
  kb=lv_keyboard_create(scr_shaft);
  lv_obj_set_width(kb,LV_PCT(100)); lv_obj_set_height(kb,180);
  kb_set_text_mode(kb);
  lv_obj_align(kb,LV_ALIGN_BOTTOM_MID,0,0);
  lv_obj_add_event_cb(kb,[](lv_event_t* e){
    lv_event_code_t code=lv_event_get_code(e);
    if(code==LV_EVENT_READY){ lv_obj_t* cur=lv_keyboard_get_textarea(kb); if(cur) focus_next_input(cur); }
    else if(code==LV_EVENT_CANCEL){ lv_keyboard_set_textarea(kb,NULL); lv_obj_add_flag(kb,LV_OBJ_FLAG_HIDDEN); }
  }, LV_EVENT_ALL, NULL);

  // Run-mode radio
  auto on_runmode=[](lv_event_t* e){
    lv_obj_t* src=(lv_obj_t*)lv_event_get_target(e);
    bool checked=lv_obj_has_state(src,LV_STATE_CHECKED);
    if(checked){
      if(src==cb_single){ lv_obj_clear_state(cb_multi,LV_STATE_CHECKED); g_single_run=true; }
      else               { lv_obj_clear_state(cb_single,LV_STATE_CHECKED); g_single_run=false; }
    } else {
      bool other=lv_obj_has_state(src==cb_single?cb_multi:cb_single,LV_STATE_CHECKED);
      if(!other) lv_obj_add_state(src,LV_STATE_CHECKED);
    }
    update_runmode_ui();
  };
  lv_obj_add_event_cb(cb_single,on_runmode,LV_EVENT_VALUE_CHANGED,NULL);
  lv_obj_add_event_cb(cb_multi, on_runmode,LV_EVENT_VALUE_CHANGED,NULL);

  lv_obj_add_event_cb(dd_single,[](lv_event_t* e){
    if(lv_event_get_code(e)==LV_EVENT_VALUE_CHANGED) update_single_option_ui();
  },LV_EVENT_ALL,NULL);

  update_runmode_ui();
  time_format_apply_to_widgets();
  lv_obj_add_state(ta_shaft,LV_STATE_FOCUSED);
  EVT_SEND(ta_shaft,LV_EVENT_FOCUSED,NULL);

  #undef MAKE_ROW
  #undef MAKE_LBL
  #undef WIRE_TA
}

// ─────────────────────────────────────────────────────────────────────────
// Setup
// ─────────────────────────────────────────────────────────────────────────
void setup() {
  Serial.begin(115200);
  Display.begin();
  Touch.begin();

  init_styles();
  build_main_screen();
  build_shaft_screen();
  build_ble_screen();

  rtc_set_manual(2025, 10, 7, 16, 35, 0); // update to your local time

  lv_scr_load(scr_main);

  battery_timer = lv_timer_create(battery_tick, 2000, nullptr);
  battery_tick(nullptr);
  rtc_tick();

  ble_init();
}

// ─────────────────────────────────────────────────────────────────────────
// Loop
// ─────────────────────────────────────────────────────────────────────────
void loop() {
  lv_timer_handler();

  unsigned long now = millis();
  if (now - lastRTCTick >= RTC_INTERVAL_MS) {
    lastRTCTick = now;
    rtc_tick();
  }

  ble_tick();

  delay(5);
}
