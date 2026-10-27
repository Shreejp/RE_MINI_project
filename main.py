"""
ROBOT ENGINEERING | Pico W smart storage dashboard
MicroPython on Raspberry Pi Pico W (not desktop Python)

Upload BOTH files to the Pico W root:
  main.py
  dashboard.html

GPIO: DHT22 GP16 | DS18B20 GP17 | HC-SR04 TRIG GP18, ECHO GP19
      Moisture AO GP26 | LDR AO GP27 (or digital DO GP20)
      Buzzer control GP22 | NO push button

SAFETY: ECHO must be <=3.3 V at GP19. A standard 5 V HC-SR04
needs a voltage divider unless the module already has one.
"""
import time
import asyncio
import network
import gc
import json
from machine import Pin, ADC, PWM, time_pulse_us
import dht
import onewire
import ds18x20

# =============== CHANGE THESE TWO LINES ===============
WIFI_SSID = "YOUR_WIFI_SSID"
WIFI_PASSWORD = "YOUR_WIFI_PASSWORD"
# Pico W connects to a 2.4 GHz Wi-Fi network.

# =============== SENSOR SETTINGS =====================
LDR_MODE = "analog"       # "analog": AO GP27; "digital": DO GP20
BUZZER_ENABLED = True     # False until your buzzer wiring is verified
BUZZER_TYPE = "active"    # "active" or "passive"
BUZZER_ACTIVE_HIGH = True # Some active LOW modules need False

# Each sensor is read at its own safe speed. The browser receives updates
# immediately via an HTTP event stream; no timed page refresh is used.
ADC_EVERY_MS = 350
SONAR_EVERY_MS = 700
DHT_EVERY_MS = 2400    # DHT22 needs >2 seconds between measurements.
PROBE_EVERY_MS = 1400  # DS18B20 12-bit conversion needs up to 750 ms.
ALARM_REPEAT_MS = 60000

# Demonstration thresholds; NOT universal food-storage recommendations.
HUMIDITY_ALERT_RH = 70.0
AIR_TEMP_ALERT_C = 35.0
PRODUCT_TEMP_ALERT_C = 35.0
LOW_FILL_ALERT_PCT = 15.0

# Use actual measured distances from HC-SR04 face to EMPTY bottom
# and to the material surface when the container is FULL.
# Leave as None until calibrated. Fill % will then be unavailable.
EMPTY_DISTANCE_CM = None   # e.g. 29.5
FULL_DISTANCE_CM = None    # e.g. 5.0

# This sensor does NOT measure real seed/food moisture %.
# Optional 0-100 comparative index for ONE material after testing.
MOISTURE_DRY_RAW = None
MOISTURE_DAMP_RAW = None

# Optional light intensity index (relative, NOT lux).
LIGHT_DARK_RAW = None
LIGHT_BRIGHT_RAW = None

HTML_FILE = "dashboard.html"
HTTP_PORT = 80

# =============== GPIO =================================
dht22 = dht.DHT22(Pin(16))
probe = ds18x20.DS18X20(onewire.OneWire(Pin(17)))
trig = Pin(18, Pin.OUT, value=0)
echo = Pin(19, Pin.IN)
moist_adc = ADC(Pin(26))
if LDR_MODE == "analog":
    light_in = ADC(Pin(27))
elif LDR_MODE == "digital":
    light_in = Pin(20, Pin.IN)
else:
    raise ValueError('LDR_MODE must be "analog" or "digital"')

buzzer_pin = None
buzzer_pwm = None
if BUZZER_ENABLED:
    if BUZZER_TYPE == "active":
        buzzer_pin = Pin(22, Pin.OUT)
        buzzer_pin.value(0 if BUZZER_ACTIVE_HIGH else 1)
    elif BUZZER_TYPE == "passive":
        buzzer_pwm = PWM(Pin(22))
        buzzer_pwm.freq(2200)
        buzzer_pwm.duty_u16(0)
    else:
        raise ValueError('BUZZER_TYPE must be "active" or "passive"')


def set_buzzer(on):
    if not BUZZER_ENABLED:
        return
    if buzzer_pin is not None:
        buzzer_pin.value((1 if BUZZER_ACTIVE_HIGH else 0) if on else
                         (0 if BUZZER_ACTIVE_HIGH else 1))
    elif buzzer_pwm is not None:
        buzzer_pwm.duty_u16(28000 if on else 0)


async def beep_pattern():
    try:
        set_buzzer(True)
        await asyncio.sleep_ms(140)
        set_buzzer(False)
        await asyncio.sleep_ms(90)
        set_buzzer(True)
        await asyncio.sleep_ms(140)
    finally:
        set_buzzer(False)


def adc_average(pin, n=6):
    total = 0
    for _ in range(n):
        total += pin.read_u16()
    return total // n


def relative_index(value, first, second):
    if value is None or first is None or second is None or first == second:
        return None
    v = 100 * (value - first) / (second - first)
    return round(max(0, min(100, v)), 1)


def fill_percent(distance):
    if distance is None or EMPTY_DISTANCE_CM is None or FULL_DISTANCE_CM is None:
        return None
    span = EMPTY_DISTANCE_CM - FULL_DISTANCE_CM
    if span <= 0:
        return None
    return round(max(0, min(100, (EMPTY_DISTANCE_CM-distance)*100/span)), 1)


state = {
    "uptime_s": 0, "sample_number": 0, "air_seq": 0,
    "air_temp_c": None, "humidity_rh": None,
    "product_temp_c": None, "moisture_raw": None,
    "moisture_index": None, "light_raw": None, "light_index": None,
    "light_mode": LDR_MODE, "distance_cm": None, "fill_pct": None,
    "errors": {}, "alerts": [], "status": "initializing",
    "calibration": {
        "fill": (EMPTY_DISTANCE_CM is not None and FULL_DISTANCE_CM is not None and
                 EMPTY_DISTANCE_CM > FULL_DISTANCE_CM),
        "moisture": (MOISTURE_DRY_RAW is not None and MOISTURE_DAMP_RAW is not None and
                     MOISTURE_DRY_RAW != MOISTURE_DAMP_RAW),
        "light": (LIGHT_DARK_RAW is not None and LIGHT_BRIGHT_RAW is not None and
                  LIGHT_DARK_RAW != LIGHT_BRIGHT_RAW)
    }
}


def sensor_error(sensor, message):
    # Do not accidentally erase errors from another sensor.
    if message:
        state["errors"][sensor] = str(message)
    else:
        state["errors"].pop(sensor, None)


def publish():
    alerts = []
    t = state["air_temp_c"]
    h = state["humidity_rh"]
    pt = state["product_temp_c"]
    f = state["fill_pct"]
    if h is not None and h >= HUMIDITY_ALERT_RH:
        alerts.append("High container humidity")
    if t is not None and t >= AIR_TEMP_ALERT_C:
        alerts.append("High air temperature")
    if pt is not None and pt >= PRODUCT_TEMP_ALERT_C:
        alerts.append("High stored-product temperature")
    if f is not None and f <= LOW_FILL_ALERT_PCT:
        alerts.append("Low storage fill level")
    state["alerts"] = alerts
    state["status"] = "alert" if alerts else ("sensor_error" if state["errors"] else "normal")
    state["sample_number"] += 1
    state["uptime_s"] = time.ticks_ms() // 1000
    # Clients waiting on /api/stream detect this change and get the new state.


async def adc_loop():
    while True:
        try:
            raw = adc_average(moist_adc)
            state["moisture_raw"] = raw
            state["moisture_index"] = relative_index(raw, MOISTURE_DRY_RAW, MOISTURE_DAMP_RAW)
            sensor_error("Moisture", None)
        except Exception as exc:
            state["moisture_raw"] = state["moisture_index"] = None
            sensor_error("Moisture", exc)
        try:
            raw = adc_average(light_in) if LDR_MODE == "analog" else light_in.value()
            state["light_raw"] = raw
            state["light_index"] = (relative_index(raw, LIGHT_DARK_RAW, LIGHT_BRIGHT_RAW)
                                    if LDR_MODE == "analog" else None)
            sensor_error("LDR", None)
        except Exception as exc:
            state["light_raw"] = state["light_index"] = None
            sensor_error("LDR", exc)
        publish()
        await asyncio.sleep_ms(ADC_EVERY_MS)


async def air_loop():
    while True:
        try:
            dht22.measure()
            t, h = dht22.temperature(), dht22.humidity()
            if not (-40 <= t <= 80 and 0 <= h <= 100):
                raise ValueError("Air reading outside sensor range")
            state["air_temp_c"] = round(t, 1)
            state["humidity_rh"] = round(h, 1)
            sensor_error("DHT22", None)
        except Exception as exc:
            state["air_temp_c"] = state["humidity_rh"] = None
            sensor_error("DHT22", exc)
        state["air_seq"] += 1
        publish()
        await asyncio.sleep_ms(DHT_EVERY_MS)


async def probe_loop():
    while True:
        try:
            ids = probe.scan()
            if not ids:
                raise OSError("DS18B20 not detected (check 4.7k pull-up)")
            probe.convert_temp()
            # Non-blocking wait: the server and faster sensors keep working.
            await asyncio.sleep_ms(760)
            reading = probe.read_temp(ids[0])
            if reading is None or not (-55.0 < reading < 85.0):
                raise ValueError("Invalid DS18B20 reading")
            state["product_temp_c"] = round(reading, 1)
            sensor_error("DS18B20", None)
        except Exception as exc:
            state["product_temp_c"] = None
            sensor_error("DS18B20", exc)
        publish()
        await asyncio.sleep_ms(PROBE_EVERY_MS)


def ultrasonic_ping(t):
    trig.off()
    time.sleep_us(3)
    trig.on()
    time.sleep_us(10)
    trig.off()
    try:
        pulse = time_pulse_us(echo, 1, 30000)
    except (OSError, ValueError):
        return None
    if pulse <= 0:
        return None
    air_t = 20.0 if t is None else t
    cm = pulse * (331.3 + 0.606 * air_t) / 20000.0
    return cm if 2 <= cm <= 400 else None


async def sonar_loop():
    recent = []
    while True:
        try:
            reading = ultrasonic_ping(state["air_temp_c"])
            if reading is None:
                recent = []
                state["distance_cm"] = state["fill_pct"] = None
                sensor_error("HC-SR04", "No valid echo (check target and wiring)")
            else:
                recent.append(reading)
                if len(recent) > 3:
                    recent.pop(0)
                ordered = sorted(recent)
                dist = round(ordered[len(ordered)//2], 1)
                state["distance_cm"] = dist
                state["fill_pct"] = fill_percent(dist)
                sensor_error("HC-SR04", None)
        except Exception as exc:
            state["distance_cm"] = state["fill_pct"] = None
            sensor_error("HC-SR04", exc)
        publish()
        await asyncio.sleep_ms(SONAR_EVERY_MS)


async def alarm_loop():
    last_alerts = ()
    last_alarm = None
    while True:
        current = tuple(state["alerts"])
        now = time.ticks_ms()
        if current and (current != last_alerts or last_alarm is None or
                        time.ticks_diff(now, last_alarm) >= ALARM_REPEAT_MS):
            last_alarm = now
            await beep_pattern()
        last_alerts = current
        await asyncio.sleep_ms(450)


async def send_response(writer, code, mime, body):
    if isinstance(body, str):
        body = body.encode("utf-8")
    head = ("HTTP/1.1 {}\r\nContent-Type: {}\r\nCache-Control: no-store\r\n"
            "Connection: close\r\nContent-Length: {}\r\n\r\n").format(code, mime, len(body))
    writer.write(head.encode("utf-8"))
    writer.write(body)
    await writer.drain()


async def serve_page(writer):
    try:
        f = open(HTML_FILE, "rb")
    except OSError:
        await send_response(writer, "500 Internal Server Error", "text/plain",
                            "dashboard.html not found: upload alongside main.py")
        return
    try:
        import os
        size = os.stat(HTML_FILE)[6]
        writer.write(("HTTP/1.1 200 OK\r\nContent-Type: text/html; charset=utf-8\r\n"
                      "Cache-Control: no-store\r\nConnection: close\r\n"
                      "Content-Length: {}\r\n\r\n").format(size).encode())
        await writer.drain()
        while True:
            chunk = f.read(768)
            if not chunk:
                break
            writer.write(chunk)
            await writer.drain()
    finally:
        f.close()


active_streams = 0
MAX_STREAMS = 3   # Protect Pico W RAM from many simultaneous browser tabs.


async def serve_events(writer):
    global active_streams
    if active_streams >= MAX_STREAMS:
        await send_response(writer, "503 Service Unavailable", "text/plain",
                            "Too many live viewers; close an unused dashboard tab")
        return
    active_streams += 1
    try:
        writer.write(b"HTTP/1.1 200 OK\r\nContent-Type: text/event-stream\r\n"
                     b"Cache-Control: no-cache, no-transform\r\nConnection: keep-alive\r\n"
                     b"X-Accel-Buffering: no\r\n\r\n")
        await writer.drain()
        last_version = -1
        last_ping = time.ticks_ms()
        while True:
            seq = state["sample_number"]
            if seq != last_version:
                # Server-Sent Events push JSON immediately after a sensor update.
                message = "data: " + json.dumps(state) + "\n\n"
                writer.write(message.encode("utf-8"))
                await writer.drain()
                last_version = seq
                last_ping = time.ticks_ms()
            elif time.ticks_diff(time.ticks_ms(), last_ping) > 15000:
                writer.write(b": keep-alive\n\n")
                await writer.drain()
                last_ping = time.ticks_ms()
            await asyncio.sleep_ms(75)
    finally:
        active_streams -= 1


async def handle_client(reader, writer):
    try:
        request = await reader.readline()
        if not request or len(request) > 512:
            return
        # Drain a small number of HTTP request headers.
        for _ in range(32):
            header = await reader.readline()
            if not header or header in (b"\r\n", b"\n"):
                break
            if len(header) > 1024:
                return
        parts = request.split()
        if len(parts) < 2 or parts[0] != b"GET":
            await send_response(writer, "405 Method Not Allowed", "text/plain", "GET only")
            return
        path = parts[1].split(b"?", 1)[0]
        if path in (b"/", b"/index.html"):
            await serve_page(writer)
        elif path == b"/api/data":
            # Keep old JSON endpoint for diagnostics / backwards compatibility.
            await send_response(writer, "200 OK", "application/json; charset=utf-8",
                                json.dumps(state))
        elif path == b"/api/stream":
            await serve_events(writer)
        elif path == b"/favicon.ico":
            await send_response(writer, "204 No Content", "text/plain", b"")
        else:
            await send_response(writer, "404 Not Found", "text/plain", "Not found")
    except (OSError, ValueError, EOFError):
        # Expected when the browser closes a tab, reloads, or loses Wi-Fi.
        pass
    except Exception as exc:
        print("HTTP handler error:", exc)
    finally:
        writer.close()
        try:
            await writer.wait_closed()
        except Exception:
            pass


def connect_wifi():
    if WIFI_SSID == "YOUR_WIFI_NAME" or not WIFI_SSID:
        raise ValueError("Edit WIFI_SSID and WIFI_PASSWORD near top of main.py")
    wlan = network.WLAN(network.STA_IF)
    wlan.active(True)
    wlan.connect(WIFI_SSID, WIFI_PASSWORD)
    print("Connecting to Wi-Fi:", WIFI_SSID)
    for _ in range(40):
        if wlan.isconnected():
            print("Wi-Fi connected!\n\n  OPEN: http://{}/\n".format(wlan.ifconfig()[0]))
            return wlan
        time.sleep_ms(500)
    raise RuntimeError("Wi-Fi connection failed. Use 2.4GHz SSID and check password.")


async def maintenance_loop(wlan):
    last_wifi = time.ticks_ms()
    while True:
        if not wlan.isconnected() and time.ticks_diff(time.ticks_ms(), last_wifi) >= 15000:
            last_wifi = time.ticks_ms()
            print("Wi-Fi disconnected; reconnecting...")
            try:
                wlan.connect(WIFI_SSID, WIFI_PASSWORD)
            except OSError as exc:
                print("Wi-Fi retry failed:", exc)
        gc.collect()
        await asyncio.sleep_ms(3000)


async def run_async():
    wlan = connect_wifi()
    server = await asyncio.start_server(handle_client, "0.0.0.0", HTTP_PORT, backlog=4)
    asyncio.create_task(adc_loop())
    asyncio.create_task(air_loop())
    asyncio.create_task(probe_loop())
    asyncio.create_task(sonar_loop())
    asyncio.create_task(alarm_loop())
    asyncio.create_task(maintenance_loop(wlan))
    print("Live event stream ready at /api/stream")
    print("Dashboard ready. Stop with Ctrl+C in Thonny.")
    try:
        while True:
            await asyncio.sleep(3600)
    finally:
        server.close()
        await server.wait_closed()


def run():
    print("\nROBOT ENGINEERING | REAL-TIME PICO W DASHBOARD")
    try:
        asyncio.run(run_async())
    finally:
        set_buzzer(False)
        if buzzer_pwm is not None:
            buzzer_pwm.deinit()
        try:
            asyncio.new_event_loop()
        except Exception:
            pass


if __name__ == "__main__":
    run()
