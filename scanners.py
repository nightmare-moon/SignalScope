import asyncio
import queue
import threading
import time
import math
from winwifi import Wifi

class Scanners:
    def __init__(self, out, wifi=True, ble=True, demo=False):
        self.out, self.demo = out, demo
        self.stop = threading.Event()
        self.threads = []
        for target in ([self.demo_loop] if demo else
                       ([self.wifi_loop] if wifi else []) + ([self.ble_loop] if ble else [])):
            t = threading.Thread(target=target, daemon=True)
            self.threads.append(t)
            t.start()

    def send(self, kind, value):
        try:
            self.out.put_nowait((kind, value))
        except queue.Full:
            # Backpressure: discard rather than grow memory without bound.
            pass

    def alive(self):
        return any(t.is_alive() for t in self.threads)

    def wifi_loop(self):
        api = None
        try:
            api = Wifi()
            while not self.stop.is_set():
                try:
                    rows, errors = api.scan(self.stop)
                    if self.stop.is_set():
                        break
                    for row in rows:
                        self.send('observation', row)
                    self.send('wifi', '; '.join(errors) if errors else f'{len(rows)} fresh access points; refresh every 10s')
                except Exception as e:
                    self.send('wifi', str(e))
                if self.stop.wait(5.5):
                    break
        except Exception as e:
            self.send('wifi', str(e))
        finally:
            if api:
                api.close()

    def ble_loop(self):
        try:
            asyncio.run(self.ble_async())
        except ImportError:
            self.send('ble', 'BLE dependency missing. Run Setup.cmd; Wi-Fi works without it.')
        except Exception as e:
            self.send('ble', f'BLE stopped: {e}. Check Bluetooth is enabled, then Stop / Start.')

    async def ble_async(self):
        from bleak import BleakScanner
        last = {}
        def callback(device, advertisement):
            now = time.monotonic()
            if self.stop.is_set() or now - last.get(device.address, -100) < 5:
                return
            last[device.address] = now
            if len(last) > 5000:
                stale = [k for k, t in last.items() if now - t > 300]
                for key in stale:
                    del last[key]
            self.send('observation', dict(id='ble:' + device.address, kind='BLE',
                name=advertisement.local_name or device.name or '(unnamed BLE)',
                rssi=advertisement.rssi, details={
                    'address': device.address,
                    'service_uuids': advertisement.service_uuids,
                    'manufacturer_data': {str(k): v.hex() for k, v in advertisement.manufacturer_data.items()},
                    'service_data': {str(k): v.hex() for k, v in advertisement.service_data.items()},
                    'tx_power': advertisement.tx_power}))
        async with BleakScanner(detection_callback=callback, scanning_mode='passive'):
            self.send('ble', 'Listening for BLE advertisements; saved at most once per ID every 5s')
            while not self.stop.is_set():
                await asyncio.sleep(.25)

    def demo_loop(self):
        self.send('wifi', 'DEMO: simulated Wi-Fi observations')
        self.send('ble', 'DEMO: simulated BLE observations')
        tick = 0
        while not self.stop.is_set():
            count = 7 if tick < 15 else 9
            for i in range(count):
                kind = 'Wi-Fi' if i % 2 == 0 else 'BLE'
                self.send('observation', dict(id=f'{"wifi" if kind == "Wi-Fi" else "ble"}:DE:00:00:00:00:{i:02X}',
                    name=['Home network', 'Headphones', 'Office', 'Fitness band', 'Guest Wi-Fi', 'Beacon', 'Printer', 'New beacon', 'New AP'][i],
                    kind=kind, rssi=int(-38 - i * 6 + math.sin(tick / 3 + i) * 5),
                    details={'demo': True, 'privacy': i != 4} if kind == 'Wi-Fi' else {'demo': True}))
            tick += 1
            self.stop.wait(2)
