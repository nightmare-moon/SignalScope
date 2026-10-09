# SignalScope for Windows 11 — v0.1

An independent local desktop app inspired by the signal-strength display and workflow in the supplied SOPHIA references. It does not use SOPHIA code, branding, classifiers, or proprietary rules.

## Start here

1. Extract this ZIP completely to a writable folder, for example `C:\SignalScope`.
2. Install **64-bit Python 3.12 or newer** from https://www.python.org/downloads/windows/ if needed. Include the Python launcher and Tcl/Tk support. If you already have Python 3.12 or 3.14 installed, you can use it.
3. Double-click **Setup.cmd**. It creates a private `.venv` folder and downloads the Bluetooth dependency. Internet is needed for this initial installation.
4. Double-click **Start.cmd**. Keep its console open while the app runs; diagnostic errors appear there.
5. Turn on Wi-Fi and Bluetooth in Windows. Click **Start** in the app.
6. Let it scan for about a minute, then click **Save current baseline**.

**Demo.cmd** runs simulated signals with a prominent DEMO label and a separate database. It never starts the radio scanners. Two additional simulated identifiers appear after about 30 seconds, so save a baseline early to try change alerts.

The supplied app is runnable Python source, not a prebuilt EXE. **Build_EXE.cmd** optionally installs PyInstaller and builds `dist\SignalScope\SignalScope.exe` on your Windows PC. Copy the whole generated folder together. This packaging step has not been tested on Windows in the authoring environment.

## What works in this first version

- Windows native WLAN scanning: SSID, BSSID, measured RSSI in dBm, frequency, link quality and privacy capability bit.
- Passive Bluetooth LE advertisement scanning through Bleak 3.0.2: names where advertised, addresses, RSSI, manufacturer data and service data. No BLE connections or pairing.
- A resizable dark dashboard with radar, searchable device table, event timeline, device details and five-minute RSSI chart.
- Stable angular placement by identifier. Stronger RSSI plots nearer the center. Angles do **not** show direction, and radius does **not** show meters.
- Separate named location baselines (Home, Office, etc.). Stop scanning to change location profile.
- Local SQLite history and CSV / JSON export for the selected profile.
- Dedicated demo mode. No silent substitution of demo data for failed hardware scans.

Wi-Fi and BLE switches are chosen before starting. Stop, change switches, then start again. The scanner uses available Wi-Fi adapters and combines identical BSSIDs by strongest reading; it does not provide manual adapter selection in v0.1.

## Radar and tables

Cyan dots are Wi-Fi; blue dots are BLE; amber dots have one or more session flags. Click a dot or row for details. Scroll the detail panel with the mouse wheel to inspect advertisement fields. Selecting an event opens its complete explanation.

The display includes observations received within the last 45 seconds. After stopping, these age out rather than remaining falsely marked live. Historic observations remain available through export. Table first/last times and signal charts describe the current scanning session.

BLE addresses can rotate. Multiple access points can share an SSID. Counts are identifiers, not necessarily unique physical devices.

## Baselines and rules

Saving a baseline replaces the selected profile's baseline with the currently recent identifiers. Each stored RSSI is the median of up to five minutes of readings for that identifier. Profiles and baselines survive app restarts. Saving a baseline clears current session flags; the event timeline remains.

Rules are deliberately explainable and fixed in v0.1:

| Rule | Trigger |
|---|---|
| New | Identifier is absent from a saved baseline and has at least three observations in the session. |
| Persistent | New identifier remains observed for five minutes without a gap of 45 seconds. |
| Signal rise | Median of the last three readings is at least 18 dB above its baseline median. |
| Shared SSID | A new Wi-Fi BSSID uses a non-hidden SSID already in the baseline. Normal mesh networks can trigger this. |
| Open Wi-Fi | Wi-Fi privacy capability bit is not set. This is a prompt to review security, not a complete protocol/security assessment. |
| Density | Recent identifier count is at least twice baseline size and at least five above it. Rotating BLE addresses can inflate counts. |

Each rule is logged once per identifier per scanning session (or since saving a new baseline), avoiding repeated notifications. Density is a single environment event. These alerts appear in the app; v0.1 has no sound or Windows toast notifications.

A flag is a change to inspect. It does not establish malicious intent, identify an owner, or prove a tracker or hidden camera exists.

## Storage and exports

Live data: `%LOCALAPPDATA%\SignalScope\signals.sqlite3`.
Demo data: `%LOCALAPPDATA%\SignalScope\demo.sqlite3`.

The app performs no cloud uploads and has no account system. Data is stored in ordinary, unencrypted SQLite files under your Windows user profile. Close the app before copying or deleting the database and associated `-wal` / `-shm` files. Prefer CSV/JSON for sharing.

Retention is up to 30 days, with a cap of 200,000 rows each for observations and events. Cleanup runs at launch and every ten minutes while open; it bounds retained rows, not the physical SQLite file's high-water size. Baselines are retained until replaced. BLE samples are stored at most once every five seconds per address; Wi-Fi refresh cycles are approximately ten seconds. Wi-Fi cache entries older than 30 seconds are excluded.

CSV contains all retained observations for the selected profile. JSON contains those observations, its baseline and the latest 300 events. Timestamps are UTC. CSV names beginning with spreadsheet formula markers are prefixed with an apostrophe for safer spreadsheet import. Identifiers and names in exports may be sensitive; share them deliberately.

## Requirements and troubleshooting

- Windows 11, an enabled Wi-Fi adapter for Wi-Fi, and a BLE-capable Bluetooth adapter for BLE. The installed Bleak version targets Windows 11 (build 22000+).
- No Android phone, Termux, F-Droid, GPU, cloud service or administrator session is required for normal app operation.
- Windows WLAN access denied / error 5: open **Settings > Privacy & security > Location**, enable Location services and desktop-app location access as available, and accept any relevant Windows prompt. Stop/start scanning after changing settings. Organization policy may prevent this access.
- No adapter: enable the adapter in Windows or use compatible USB hardware.
- WLAN error 1062: the Windows **WLAN AutoConfig** service must be running.
- BLE stopped: ensure Bluetooth is enabled, run Setup.cmd successfully, and Stop/Start. Passive scanning may not expose names supplied only in active scan responses.
- No signals: verify the radios are on and some nearby devices are broadcasting. Most Bluetooth Classic devices will not appear as BLE advertisers.
- `py` not recognized: install Python with the Windows Python launcher, then rerun setup.
- The app starts but Bluetooth setup failed: uncheck Bluetooth LE and use Wi-Fi while correcting the dependency installation.
- Keep the computer awake while scanning. Resume scanning after sleep if the driver fails to recover.
- Offline operation means no internet connection is needed after setup. The radios must still be enabled. Wi-Fi scanning may send probe requests; passive BLE mode is not a guarantee that the entire computer is radio-silent.

## Scope limits

This first version does not implement Bluetooth Classic discovery, mDNS/SSDP/UPnP discovery, multiple-node aggregation, maps, GPS, raw 802.11 monitor-mode capture, MAC-rotation correlation, vendor/retail/vehicle classifiers, AirTag identification, or automatic identification of surveillance equipment. The PDF mixed present and planned features; this version implements the agreed core scanning/baseline/dashboard workflow.

## Validation and source layout

Validated in the authoring environment: Python syntax and 13 automated tests covering baseline/profile persistence, alert rules, stale data, retention, export safety, radar placement, demo thread shutdown, Windows structure offsets and a synthetic native WLAN response. Live Windows Wi-Fi/BLE scanning, Windows GUI rendering and EXE packaging still need testing on a Windows machine. No successful Windows hardware test is implied.

To run checks from this folder:

```bat
.venv\Scripts\python.exe -m unittest discover -s tests -v
```

- `app.py`: Tk desktop interface and main-thread data processing.
- `core.py`: SQLite history, baselines, rules and exports.
- `winwifi.py`: Windows WLAN API via ctypes.
- `scanners.py`: background Wi-Fi, BLE and demo workers.
- `tests/`: deterministic behavioral checks and synthetic WLAN decoding test.

Official API references:
- https://learn.microsoft.com/en-us/windows/win32/api/wlanapi/ns-wlanapi-wlan_bss_entry
- https://learn.microsoft.com/en-us/windows/win32/api/wlanapi/nf-wlanapi-wlangetnetworkbsslist
- https://learn.microsoft.com/en-us/windows/win32/nativewifi/wi-fi-access-location-changes
- https://bleak.readthedocs.io/en/latest/backends/windows.html
- https://pypi.org/project/bleak/3.0.2/

Bleak and other installed dependencies retain their respective licenses; setup downloads them from their package distributions.
