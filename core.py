"""Local storage and explainable signal-change rules; no networking."""
import csv
import hashlib
import json
import math
import sqlite3
from datetime import datetime, timezone
from statistics import median

STALE_SECONDS = 45

def utc(ts):
    return datetime.fromtimestamp(ts, timezone.utc).isoformat(timespec='seconds')

def radar_position(identifier, rssi, radius):
    angle = int.from_bytes(hashlib.sha256(identifier.encode()).digest()[:4], 'big') / 2**32 * math.tau
    distance = max(.12, min(1., (-rssi - 25) / 75)) * radius
    return math.cos(angle) * distance, math.sin(angle) * distance

def csv_safe(value):
    text = str(value)
    return "'" + text if text.lstrip().startswith(('=', '+', '-', '@', '\t', '\r')) else text

class Store:
    def __init__(self, path):
        self.db = sqlite3.connect(path)
        self.db.execute('PRAGMA journal_mode=WAL')
        self.db.executescript('''
        CREATE TABLE IF NOT EXISTS profiles(name TEXT PRIMARY KEY, captured REAL);
        CREATE TABLE IF NOT EXISTS baseline(profile TEXT, id TEXT, name TEXT, rssi REAL,
          PRIMARY KEY(profile,id));
        CREATE TABLE IF NOT EXISTS samples(profile TEXT, time REAL, id TEXT, kind TEXT,
          name TEXT, rssi INTEGER, details TEXT);
        CREATE INDEX IF NOT EXISTS samples_profile_time ON samples(profile,time);
        CREATE TABLE IF NOT EXISTS events(profile TEXT, time REAL, id TEXT, rule TEXT, message TEXT);
        CREATE INDEX IF NOT EXISTS events_profile_time ON events(profile,time);
        ''')
        self.db.execute('INSERT OR IGNORE INTO profiles VALUES (?,NULL)', ('Home',))
        self.db.commit()

    def profiles(self):
        return [r[0] for r in self.db.execute('SELECT name FROM profiles ORDER BY name')]

    def baseline(self, profile):
        row = self.db.execute('SELECT captured FROM profiles WHERE name=?', (profile,)).fetchone()
        values = {r[0]: {'name': r[1], 'rssi': r[2]} for r in self.db.execute(
            'SELECT id,name,rssi FROM baseline WHERE profile=?', (profile,))}
        return (row[0] if row else None), values

    def save_baseline(self, profile, devices, now):
        with self.db:
            self.db.execute('INSERT OR REPLACE INTO profiles VALUES (?,?)', (profile, now))
            self.db.execute('DELETE FROM baseline WHERE profile=?', (profile,))
            self.db.executemany('INSERT INTO baseline VALUES (?,?,?,?)', [
                (profile, d['id'], d['name'], median(v for t, v in d['history'])) for d in devices])

    def sample(self, profile, d, now):
        self.db.execute('INSERT INTO samples VALUES (?,?,?,?,?,?,?)',
            (profile, now, d['id'], d['kind'], d['name'], d['rssi'], json.dumps(d['details'])))

    def event(self, profile, now, identifier, rule, message):
        self.db.execute('INSERT INTO events VALUES (?,?,?,?,?)', (profile, now, identifier, rule, message))

    def events(self, profile):
        return list(self.db.execute('SELECT time,id,rule,message FROM events WHERE profile=? ORDER BY time DESC LIMIT 300', (profile,)))

    def prune(self, now):
        with self.db:
            for table in ('samples', 'events'):
                self.db.execute(f'DELETE FROM {table} WHERE time < ?', (now - 30 * 86400,))
                self.db.execute(f'DELETE FROM {table} WHERE rowid IN (SELECT rowid FROM {table} ORDER BY rowid DESC LIMIT -1 OFFSET 200000)')

    def export(self, filename, profile):
        if str(filename).lower().endswith('.csv'):
            with open(filename, 'w', newline='', encoding='utf-8-sig') as f:
                writer = csv.writer(f)
                writer.writerow(['time_utc', 'identifier', 'type', 'name', 'rssi_dbm', 'details_json'])
                for ts, ident, kind, name, rssi, details in self.db.execute(
                        'SELECT time,id,kind,name,rssi,details FROM samples WHERE profile=? ORDER BY time', (profile,)):
                    writer.writerow([utc(ts), csv_safe(ident), kind, csv_safe(name), rssi, csv_safe(details)])
        else:
            captured, baseline = self.baseline(profile)
            with open(filename, 'w', encoding='utf-8') as f:
                f.write(json.dumps({'format': 'SignalScope-1', 'profile': profile,
                    'baseline_captured_utc': utc(captured) if captured else None,
                    'baseline': baseline, 'events': [dict(time_utc=utc(t), identifier=i, rule=r, message=m)
                    for t, i, r, m in self.events(profile)]}, ensure_ascii=False)[:-1])
                f.write(', "observations": [')
                first = True
                for ts, ident, kind, name, rssi, details in self.db.execute(
                        'SELECT time,id,kind,name,rssi,details FROM samples WHERE profile=? ORDER BY time', (profile,)):
                    if not first:
                        f.write(',')
                    first = False
                    json.dump(dict(time_utc=utc(ts), identifier=ident, kind=kind, name=name,
                        rssi_dbm=rssi, details=json.loads(details)), f, ensure_ascii=False)
                f.write(']}')

class Engine:
    def __init__(self, store, profile='Home'):
        self.store, self.profile = store, profile
        self.devices = {}
        self.fired = set()
        self.captured, self.baseline = store.baseline(profile)

    def active(self, now):
        return [d for d in self.devices.values() if now - d['last'] < STALE_SECONDS]

    def alert(self, d, rule, message, now):
        key = (d['id'], rule)
        if key not in self.fired:
            self.fired.add(key)
            d['flags'].add(rule)
            self.store.event(self.profile, now, d['id'], rule, message)

    def ingest(self, observation, now):
        ident = observation['id']
        d = self.devices.get(ident)
        if d is None:
            d = dict(observation, first=now, last=now, since=now, count=0, flags=set(), history=[])
            self.devices[ident] = d
        if now - d['last'] >= STALE_SECONDS:
            d['since'] = now
        d.update(observation)
        d['last'] = now
        d['count'] += 1
        d['history'] = [(t, v) for t, v in d['history'] if now - t < 300][-119:] + [(now, d['rssi'])]
        self.store.sample(self.profile, d, now)
        if d['kind'] == 'Wi-Fi' and d['details'].get('privacy') is False:
            self.alert(d, 'Open Wi-Fi', 'Privacy bit not set; review network security before connecting.', now)
        if self.captured is not None and d['count'] >= 3:
            base = self.baseline.get(ident)
            if base is None:
                self.alert(d, 'New', 'Identifier absent from the saved baseline; seen at least three times.', now)
                if now - d['since'] >= 300:
                    self.alert(d, 'Persistent', 'Non-baseline identifier observed for at least five minutes without a 45-second gap.', now)
                if d['kind'] == 'Wi-Fi' and d['name'] != '(hidden SSID)' and any(
                        i.startswith('wifi:') and b['name'] == d['name'] for i, b in self.baseline.items()):
                    self.alert(d, 'Shared SSID', 'New access-point ID uses a baseline network name; mesh networks also do this.', now)
            elif len(d['history']) >= 3 and median(v for t, v in d['history'][-3:]) - base['rssi'] >= 18:
                self.alert(d, 'Signal rise', 'Median of last three readings is at least 18 dB above baseline.', now)
        # Retain live state for one hour; database retains historical observations.
        if len(self.devices) > 3000:
            self.devices = {i: x for i, x in self.devices.items() if now - x['last'] < 3600}
        return d

    def check_density(self, now):
        count = len(self.active(now))
        if self.captured is not None and self.baseline and count >= max(len(self.baseline) * 2, len(self.baseline) + 5):
            self.alert({'id': 'environment', 'flags': set()}, 'Density',
                f'{count} recent identifiers versus {len(self.baseline)} baseline identifiers; rotating BLE addresses can inflate this.', now)
