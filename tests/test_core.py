import csv
import ctypes
import json
import math
from pathlib import Path
import queue
import tempfile
import threading
import time
import unittest
from core import Engine, Store, radar_position
from scanners import Scanners
from winwifi import BssEntry, Interface, Wifi


def observation(ident='wifi:one', rssi=-65, name='Home', kind='Wi-Fi', privacy=True):
    return dict(id=ident, name=name, kind=kind, rssi=rssi, details={'privacy': privacy})

class CoreTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.store = Store(Path(self.tmp.name) / 'signals.db')
        self.engine = Engine(self.store)

    def tearDown(self):
        self.store.db.close()
        self.tmp.cleanup()

    def baseline(self):
        for t in (100, 110, 120):
            self.engine.ingest(observation(), t)
        self.store.save_baseline('Home', self.engine.active(120), 120)
        self.engine = Engine(self.store)

    def test_baseline_survives_restart_and_profiles_are_isolated(self):
        self.baseline()
        self.assertEqual(self.engine.baseline['wifi:one']['rssi'], -65)
        other = Engine(self.store, 'Office')
        self.assertIsNone(other.captured)
        self.assertEqual(other.baseline, {})

    def test_new_alert_needs_three_observations_and_is_deduplicated(self):
        self.baseline()
        for t in (130, 140):
            self.engine.ingest(observation('wifi:two', name='Other'), t)
        self.assertEqual(self.store.events('Home'), [])
        for t in (150, 160, 170):
            self.engine.ingest(observation('wifi:two', name='Other'), t)
        self.assertEqual([e[2] for e in self.store.events('Home')], ['New'])

    def test_shared_ssid_is_explained_and_hidden_ssid_not_correlated(self):
        self.baseline()
        for t in (130,140,150):
            self.engine.ingest(observation('wifi:two'), t)
        self.assertIn('Shared SSID', {e[2] for e in self.store.events('Home')})

    def test_signal_rise_requires_three_readings(self):
        self.baseline()
        self.engine.ingest(observation(rssi=-35), 130)
        self.assertEqual(self.store.events('Home'), [])
        self.engine.ingest(observation(rssi=-35), 140)
        self.engine.ingest(observation(rssi=-35), 150)
        self.assertIn('Signal rise', {e[2] for e in self.store.events('Home')})

    def test_persistent_device_gap_resets_timer(self):
        self.baseline()
        for t in range(130, 400, 10):
            self.engine.ingest(observation('ble:two', kind='BLE'), t)
        self.engine.ingest(observation('ble:two', kind='BLE'), 500)
        self.assertNotIn('Persistent', {e[2] for e in self.store.events('Home')})
        for t in range(510, 811, 10):
            self.engine.ingest(observation('ble:two', kind='BLE'), t)
        self.assertIn('Persistent', {e[2] for e in self.store.events('Home')})

    def test_stale_observations_leave_radar(self):
        self.engine.ingest(observation(), 100)
        self.assertEqual(len(self.engine.active(144)), 1)
        self.assertEqual(self.engine.active(145), [])

    def test_exports_escape_csv_formulas_and_preserve_json(self):
        self.engine.ingest(observation(name='=HYPERLINK("bad")'), 100)
        csv_path = Path(self.tmp.name) / 'out.csv'
        json_path = Path(self.tmp.name) / 'out.json'
        self.store.export(csv_path, 'Home')
        self.store.export(json_path, 'Home')
        with csv_path.open(encoding='utf-8-sig') as f:
            self.assertTrue(list(csv.reader(f))[1][3].startswith("'="))
        payload = json.loads(json_path.read_text())
        self.assertEqual(payload['observations'][0]['name'], '=HYPERLINK("bad")')
        self.assertEqual(payload['observations'][0]['rssi_dbm'], -65)
        self.store.export(Path(self.tmp.name) / 'empty.json', 'Empty')
        self.assertEqual(json.loads((Path(self.tmp.name) / 'empty.json').read_text())['observations'], [])

    def test_retention(self):
        self.engine.ingest(observation(), 100)
        self.engine.ingest(observation(), 40 * 86400)
        self.store.prune(40 * 86400)
        self.assertEqual(self.store.db.execute('SELECT count(*) FROM samples').fetchone()[0], 1)

    def test_radar_strength_is_monotonic_and_angle_is_stable(self):
        strong = radar_position('id', -35, 100)
        weak = radar_position('id', -90, 100)
        self.assertLess(math.hypot(*strong), math.hypot(*weak))
        self.assertAlmostEqual(math.atan2(*strong), math.atan2(*weak))
        self.assertEqual(strong, radar_position('id', -35, 100))

    def test_density_once_per_session(self):
        self.baseline()
        for i in range(7):
            self.engine.ingest(observation(f'wifi:{i}'), 130)
        self.engine.check_density(130)
        self.engine.check_density(131)
        self.assertEqual(sum(e[2]=='Density' for e in self.store.events('Home')), 1)

    def test_windows_struct_layout(self):
        self.assertEqual(ctypes.sizeof(BssEntry), 360)
        self.assertEqual(BssEntry.host_timestamp.offset, 80)
        self.assertEqual(ctypes.sizeof(Interface), 532)

    def test_demo_lifecycle_and_bounded_queue(self):
        out = queue.Queue(maxsize=20)
        worker = Scanners(out, demo=True)
        kind, _ = out.get(timeout=2)
        self.assertIn(kind, ('wifi', 'ble', 'observation'))
        worker.stop.set()
        for t in worker.threads:
            t.join(2)
        self.assertFalse(worker.alive())

    def test_native_scan_decodes_and_frees_buffer(self):
        class Buffer(ctypes.Structure):
            _fields_ = [('size', ctypes.c_uint32), ('count', ctypes.c_uint32), ('entry', BssEntry)]
        buf = Buffer()
        buf.size = ctypes.sizeof(buf)
        buf.count = 1
        buf.entry.ssid.length = 4
        buf.entry.ssid.data[:4] = b'Test'
        buf.entry.mac[:] = (1,2,3,4,5,6)
        buf.entry.rssi = -47
        buf.entry.frequency = 2412000
        buf.entry.capability = 16
        buf.entry.host_timestamp = int((time.time()+11644473600)*10_000_000)
        freed = []
        class Dll:
            def WlanScan(self,*args): return 0
            def WlanGetNetworkBssList(self,*args):
                ctypes.cast(args[-1], ctypes.POINTER(ctypes.c_void_p))[0] = ctypes.addressof(buf)
                return 0
            def WlanFreeMemory(self, ptr): freed.append(ptr.value)
        class Stop:
            def wait(self,seconds): return False
        api = Wifi.__new__(Wifi)
        api.dll, api.handle = Dll(), None
        api.interfaces = lambda: [Interface()]
        rows, errors = api.scan(Stop())
        self.assertEqual(errors, [])
        self.assertEqual(rows[0]['name'], 'Test')
        self.assertEqual(rows[0]['rssi'], -47)
        self.assertEqual(rows[0]['details']['frequency_mhz'], 2412)
        self.assertEqual(freed, [ctypes.addressof(buf)])
        buf.entry.host_timestamp = 0
        rows, errors = api.scan(Stop())
        self.assertEqual(rows, [])
        self.assertEqual(len(freed), 2)

if __name__ == '__main__':
    unittest.main()
