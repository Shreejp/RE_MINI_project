ROBOT ENGINEERING | LIVE PICO W DASHBOARD
=========================================
Project: Dry Fruits, Seeds, and Spices Monitoring System
Update: sensor-driven live feed + slightly darker charcoal/green design

PACKAGE
-------
main.py          NEW Pico W MicroPython sensor reader + live SSE web server
dashboard.html   Updated responsive dark green Robot Engineering dashboard
README_SETUP.txt This guide

CRITICAL: REPLACE BOTH FILES
----------------------------
The new dashboard uses /api/stream for a continuous live feed. Older versions
of main.py only support /api/data. Installing only the dashboard.html will
NOT work: it will show 'Reconnecting'. Both main.py and dashboard.html must
be uploaded to the Pico W's root filesystem.

BEFORE YOU OVERWRITE YOUR EXISTING main.py
------------------------------------------
Copy your actual WIFI_SSID, WIFI_PASSWORD and any calibrated values from the
old main.py into this new main.py first. The included source contains
placeholders for Wi-Fi credentials and unset calibration variables.

CONFIGURE AT THE TOP OF main.py
--------------------------------
WIFI_SSID = "YOUR_WIFI_NAME"
WIFI_PASSWORD = "YOUR_WIFI_PASSWORD"

Keep or adjust these values if already calibrated:
  EMPTY_DISTANCE_CM, FULL_DISTANCE_CM
  MOISTURE_DRY_RAW, MOISTURE_DAMP_RAW
  LIGHT_DARK_RAW, LIGHT_BRIGHT_RAW
  LDR_MODE ("analog" for AO/GP27; "digital" for DO/GP20)
  BUZZER_ENABLED, BUZZER_TYPE, BUZZER_ACTIVE_HIGH

UPLOAD AND RUN WITH THONNY
-------------------------
1. Connect Pico W by USB; close MicroPico, VS Code's serial port and Thonny
   shells in other windows so the Pico COM port isn't locked.
2. In Thonny, Run > Configure interpreter > MicroPython (Raspberry Pi Pico).
3. Stop the running program with Thonny's red Stop button.
4. Open THIS ZIP's new main.py on the PC, fill Wi-Fi credentials and transfer
   previous calibration settings into it.
5. File > Save as... > Raspberry Pi Pico; name it exactly main.py in root.
   Allow overwrite of the old main.py.
6. Open THIS ZIP's dashboard.html, File > Save as... > Raspberry Pi Pico,
   name it exactly dashboard.html, allow overwrite.
7. Return to main.py and press F5, or press Ctrl+D in the MicroPython Shell.
8. In the Shell, find the line: OPEN: http://192.168.x.x/
9. Open that exact address in Chrome/Edge/Safari on a phone/laptop connected
   to the same local Wi-Fi network, then reload the page.

NOTE: The Pico W is the local web server. The correct URL is its LAN IP,
not http://localhost on your computer. Use 2.4 GHz Wi-Fi for the Pico W.

HOW THE LIVE FEED WORKS
-----------------------
- The web page keeps a continuous HTTP Server-Sent Events (SSE) connection
  to /api/stream. The Pico pushes each new sensor state to the browser.
- There is NO five-second fetch interval or five-second page refresh.
- Raw moisture and light: sample approximately every 350 milliseconds.
- Ultrasonic sensor: sample approximately every 700 milliseconds.
- DHT22 temperature and humidity: new sensor sample about every 2.4 seconds;
  readings must not be forced faster than the device supports.
- DS18B20: each reading requires a conversion wait of about 760 ms, followed
  by a break; currently repeats about every 2.2 seconds.
- The interface keeps updating other sensors while slower sensors work.
- EventSource automatically reconnects after a dropped Wi-Fi connection.
- /api/data is retained for diagnosis (enter http://PICO_IP/api/data).
- Each browser-session chart keeps its latest 30 valid DHT readings in RAM.

WIRING (UNCHANGED; NO BUTTON)
-----------------------------
DHT22 DATA          --> GP16 (physical pin 21)
DS18B20 DATA        --> GP17 (physical pin 22), 4.7k pull-up if bare probe
HC-SR04 TRIG        --> GP18 (physical pin 24)
HC-SR04 ECHO        --> GP19 (physical pin 25) ONLY if 3.3V-safe
Capacitive moisture --> GP26 ADC (physical pin 31)
LDR AO              --> GP27 ADC (physical pin 32)
LDR DO alternative  --> GP20, with LDR_MODE = "digital"
Buzzer SIG          --> GP22 (physical pin 29), 3.3V-compatible driver/module
DHT22, DS18B20, LDR, moisture --> 3V3_OUT (Pico pin 36) as appropriate
HC-SR04             --> 5V VBUS (Pico pin 40) if module requires 5V
Connect ALL grounds together. No push button is used.

ELECTRICAL SAFETY & MEASUREMENT LIMITATIONS
------------------------------------------
- A normal 5V HC-SR04 Echo is NOT safe for Pico W GPIO. The Echo can be
  direct-connected ONLY if your module's built-in divider/level-shifter
  definitely outputs at most 3.3V. Verify module specification or measure it.
- Do not drive a high-current bare buzzer directly from a Pico GPIO.
- Capacitive SOIL moisture sensors do not measure scientifically accurate
  moisture percentage inside seeds, dried fruit or spices. Raw output and
  calibrated comparative indices are not actual water content percentages.
- HC-SR04 reports distance, not weight. Fill percentage only appears after
  EMPTY_DISTANCE_CM and FULL_DISTANCE_CM are set for your container.
- Warning limits (70 %RH / 35 deg C / etc.) are demonstration defaults, NOT
  validated food safety limits. Specific products need separate limits.
- Dropdown product selection changes the browser label, not alert thresholds.
- This is an unencrypted local HTTP server intended for a trusted network.
  Do not expose its port to the public Internet.

DIAGNOSING COMMON PROBLEMS
--------------------------
'Wi-Fi connection failed': verify 2.4 GHz router name and password.
'Connecting' / 'Reconnecting' forever: confirm BOTH new files are uploaded,
Pico program is running and /api/stream is supported.
'Sensor needs attention': check sensor wiring, power and pull-ups.
'Fill not calibrated': enter empty/full ultrasonic reference distances.
'The page doesn't appear': check that Pico and phone are on the same network;
some guest Wi-Fi networks isolate connected devices from each other.

VERIFICATION PERFORMED
----------------------
- MicroPython source syntax checked on desktop Python and separately tested
  with hardware-module stubs. This is not a substitute for on-device testing.
- Browser layout checked at desktop, tablet, mobile sizes in Chromium.
- Browser live event handler exercised with changing sensor values, warnings,
  missing DS18B20 data and reconnection-related states.
- Simulated HTTP server returned a valid page, JSON API and live stream events
  following sensor updates. Actual hardware/Wi-Fi needs testing on your Pico W.
