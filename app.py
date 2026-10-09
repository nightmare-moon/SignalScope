"""SignalScope: an independent Windows radio-awareness desktop application."""
import argparse
import json
import os
from pathlib import Path
import queue
import sys
import time
import tkinter as tk
from tkinter import ttk, messagebox, filedialog
from core import Store, Engine, radar_position, utc
from scanners import Scanners

BG = '#0b1220'
PANEL = '#111e30'
FG = '#e5edf7'
MUTED = '#8da2ba'
CYAN = '#47d9de'
BLUE = '#79a7ff'
AMBER = '#ffc56b'

class App:
    def __init__(self, root, demo=False, data_dir=None):
        self.root, self.demo = root, demo
        base = Path(data_dir or os.environ.get('LOCALAPPDATA', Path.home())) / 'SignalScope'
        base.mkdir(parents=True, exist_ok=True)
        self.base = base
        self.store = Store(base / ('demo.sqlite3' if demo else 'signals.sqlite3'))
        self.store.prune(time.time())
        self.engine = Engine(self.store)
        self.worker = None
        self.out = queue.Queue(maxsize=3000)
        self.closing = False
        self.selected = None
        self.dot_positions = []
        self.mode = tk.StringVar(value='All signals')
        self.query = tk.StringVar()
        self.profile = tk.StringVar(value='Home')
        self.wifi = tk.BooleanVar(value=True)
        self.ble = tk.BooleanVar(value=True)
        self.stats = tk.StringVar(value='Ready to scan')
        self.status_wifi = tk.StringVar(value='Wi-Fi: stopped')
        self.status_ble = tk.StringVar(value='BLE: stopped')
        self.baseline_label = tk.StringVar()
        self.last_prune = time.time()
        self.build()
        self.baseline_text()
        self.root.protocol('WM_DELETE_WINDOW', self.close)
        self.root.after(250, self.tick)

    def build(self):
        root = self.root
        root.title('SignalScope • Windows signal awareness' + (' • DEMO' if self.demo else ''))
        root.geometry('1280x860')
        root.minsize(1050, 760)
        root.configure(bg=BG)
        style = ttk.Style()
        style.theme_use('clam')
        style.configure('.', background=BG, foreground=FG, font=('Segoe UI', 10))
        style.configure('TFrame', background=BG)
        style.configure('TLabel', background=BG, foreground=FG)
        style.configure('Muted.TLabel', foreground=MUTED)
        style.configure('Title.TLabel', font=('Segoe UI', 24, 'bold'))
        style.configure('Stats.TLabel', font=('Segoe UI', 14, 'bold'), foreground=CYAN)
        style.configure('TButton', background='#203650', padding=(12, 8), borderwidth=0)
        style.map('TButton', background=[('active', '#315372')], foreground=[('disabled', '#657488')])
        style.configure('TCheckbutton', background=BG, foreground=FG)
        style.map('TCheckbutton', background=[('active', BG)])
        style.configure('TEntry', fieldbackground=PANEL, foreground=FG, insertcolor=FG)
        style.configure('TCombobox', fieldbackground=PANEL, foreground=FG, arrowcolor=CYAN)
        style.map('TCombobox', fieldbackground=[('readonly', PANEL)], foreground=[('readonly', FG)])
        style.configure('Treeview', background=PANEL, fieldbackground=PANEL, foreground=FG,
                        rowheight=29, borderwidth=0)
        style.configure('Treeview.Heading', background='#203650', foreground=FG, padding=7)
        style.map('Treeview', background=[('selected', '#284b65')])
        style.configure('TNotebook', background=BG, borderwidth=0)
        style.configure('TNotebook.Tab', background='#203650', padding=(16, 8))
        style.map('TNotebook.Tab', background=[('selected', '#315372')])
        main = ttk.Frame(root, padding=20)
        main.pack(fill='both', expand=True)
        head = ttk.Frame(main)
        head.pack(fill='x')
        ttk.Label(head, text='SIGNALSCOPE', style='Title.TLabel').pack(side='left')
        ttk.Label(head, text='DEMO • SIMULATED DATA' if self.demo else 'LOCAL • WINDOWS • NO CLOUD',
                  foreground=AMBER if self.demo else CYAN).pack(side='right')
        ttk.Label(main, text='Observe nearby signals. Learn a baseline. Review what changed.', style='Muted.TLabel').pack(anchor='w', pady=(2, 14))
        toolbar = ttk.Frame(main)
        toolbar.pack(fill='x')
        self.start_button = ttk.Button(toolbar, text='▶  Start', command=self.start)
        self.start_button.pack(side='left', padx=(0, 6))
        self.stop_button = ttk.Button(toolbar, text='■  Stop', command=self.stop, state='disabled')
        self.stop_button.pack(side='left', padx=(0, 12))
        self.wifi_check = ttk.Checkbutton(toolbar, text='Wi-Fi', variable=self.wifi)
        self.wifi_check.pack(side='left')
        self.ble_check = ttk.Checkbutton(toolbar, text='Bluetooth LE', variable=self.ble)
        self.ble_check.pack(side='left', padx=(0, 20))
        ttk.Button(toolbar, text='Export CSV', command=lambda: self.export('csv')).pack(side='right', padx=4)
        ttk.Button(toolbar, text='Export JSON', command=lambda: self.export('json')).pack(side='right', padx=4)
        ttk.Button(toolbar, text='Help', command=self.help).pack(side='right', padx=4)
        profiles = ttk.Frame(main)
        profiles.pack(fill='x', pady=10)
        ttk.Label(profiles, text='Location profile').pack(side='left', padx=(0, 8))
        self.profile_box = ttk.Combobox(profiles, textvariable=self.profile, values=self.store.profiles(), width=18)
        self.profile_box.pack(side='left')
        self.load_button = ttk.Button(profiles, text='Load / new', command=self.load_profile)
        self.load_button.pack(side='left', padx=6)
        ttk.Button(profiles, text='Save current baseline', command=self.save_baseline).pack(side='left', padx=6)
        ttk.Label(profiles, textvariable=self.baseline_label, style='Muted.TLabel').pack(side='left', padx=8)
        ttk.Label(main, textvariable=self.stats, style='Stats.TLabel').pack(anchor='w', pady=(3, 10))
        body = ttk.Panedwindow(main, orient='horizontal')
        body.pack(fill='both', expand=True)
        left = ttk.Frame(body)
        right = ttk.Frame(body)
        body.add(left, weight=2)
        body.add(right, weight=3)
        left.columnconfigure(0, weight=1)
        left.rowconfigure(2, weight=1, minsize=100)
        ttk.Label(left, text='SIGNAL STRENGTH', foreground=CYAN).grid(row=0, column=0, sticky='w')
        ttk.Label(left, text='Stronger = nearer center • angle is only a display position', style='Muted.TLabel', wraplength=420).grid(row=1, column=0, sticky='w', pady=(3, 8))
        self.radar = tk.Canvas(left, bg=PANEL, highlightthickness=0, height=320, width=420)
        self.radar.grid(row=2, column=0, sticky='nsew', padx=(0, 14))
        self.radar.bind('<Button-1>', self.radar_click)
        legend = ttk.Frame(left)
        legend.grid(row=3, column=0, sticky='w', pady=6)
        for label, color in [('● Wi-Fi', CYAN), ('● BLE', BLUE), ('● Alert', AMBER)]:
            ttk.Label(legend, text=label, foreground=color).pack(side='left', padx=(0, 14))
        self.details = tk.Text(left, height=7, wrap='word', bg=PANEL, fg=FG,
                               font=('Consolas', 10), relief='flat', padx=10, pady=10)
        self.details.grid(row=4, column=0, sticky='ew', padx=(0, 14))
        self.details.insert('1.0', 'Select a radar dot or a table row for details.\n\nNo direction or physical distance is inferred.')
        self.details.configure(state='disabled')
        self.history = tk.Canvas(left, bg=PANEL, highlightthickness=0, height=90)
        self.history.grid(row=5, column=0, sticky='ew', padx=(0, 14), pady=(8, 0))
        filters = ttk.Frame(right)
        filters.pack(fill='x', pady=(0, 8))
        box = ttk.Combobox(filters, textvariable=self.mode, values=['All signals', 'Wi-Fi', 'BLE', 'Alerts'], state='readonly', width=13)
        box.pack(side='left', padx=(0, 8))
        ttk.Entry(filters, textvariable=self.query, width=23).pack(side='left', fill='x', expand=True)
        ttk.Label(filters, text=' Search name / ID', style='Muted.TLabel').pack(side='left')
        self.tabs = ttk.Notebook(right)
        self.tabs.pack(fill='both', expand=True)
        signals = ttk.Frame(self.tabs)
        events = ttk.Frame(self.tabs)
        self.tabs.add(signals, text='Recent signals')
        self.tabs.add(events, text='Event timeline')
        self.table = self.make_table(signals, [('kind', 'Type', 55), ('name', 'Name', 170),
            ('rssi', 'dBm', 48), ('state', 'Baseline / alerts', 145), ('age', 'Age', 50)])
        self.table.bind('<<TreeviewSelect>>', self.select_row)
        self.events = self.make_table(events, [('time', 'Time (UTC)', 145), ('rule', 'Rule', 85), ('message', 'Explanation', 360)])
        self.events.bind('<<TreeviewSelect>>', self.select_event)
        ttk.Label(main, textvariable=self.status_wifi, style='Muted.TLabel', wraplength=1180).pack(anchor='w', pady=(12, 2))
        ttk.Label(main, textvariable=self.status_ble, style='Muted.TLabel', wraplength=1180).pack(anchor='w')
        ttk.Label(main, text='Wi-Fi scanning may transmit probes. BLE uses passive mode. Changes are observations, not proof of a threat.',
                  style='Muted.TLabel').pack(anchor='w', pady=(8, 0))

    def make_table(self, parent, columns):
        parent.rowconfigure(0, weight=1)
        parent.columnconfigure(0, weight=1)
        tree = ttk.Treeview(parent, columns=[c[0] for c in columns], show='headings', selectmode='browse')
        for key, label, width in columns:
            tree.heading(key, text=label)
            tree.column(key, width=width, minwidth=40, stretch=key in ('name', 'message', 'state'))
        tree.grid(row=0, column=0, sticky='nsew')
        bar = ttk.Scrollbar(parent, orient='vertical', command=tree.yview)
        bar.grid(row=0, column=1, sticky='ns')
        horizontal = ttk.Scrollbar(parent, orient='horizontal', command=tree.xview)
        horizontal.grid(row=1, column=0, sticky='ew')
        tree.configure(yscrollcommand=bar.set, xscrollcommand=horizontal.set)
        return tree

    def baseline_text(self):
        self.baseline_label.set(f'{len(self.engine.baseline)} saved identifiers' if self.engine.captured is not None else 'No baseline saved')

    def load_profile(self):
        if self.worker:
            return
        name = self.profile.get().strip()[:80]
        if not name:
            return
        self.profile.set(name)
        self.store.db.execute('INSERT OR IGNORE INTO profiles VALUES (?,NULL)', (name,))
        self.store.db.commit()
        self.engine = Engine(self.store, name)
        self.profile_box.configure(values=self.store.profiles())
        self.selected = None
        self.baseline_text()

    def save_baseline(self):
        active = self.engine.active(time.time())
        if not active:
            messagebox.showinfo('Baseline', 'Start scanning and wait for signals before saving a baseline.')
            return
        if not messagebox.askyesno('Save baseline', f'Save {len(active)} recent identifiers for {self.engine.profile}?\n\nThis replaces its previous baseline. Let scanning run for a minute first.\nDevices absent now will not be in this baseline.'):
            return
        self.store.save_baseline(self.engine.profile, active, time.time())
        self.engine.captured, self.engine.baseline = self.store.baseline(self.engine.profile)
        self.engine.fired.clear()
        for d in self.engine.devices.values():
            d['flags'].clear()
        self.baseline_text()

    def start(self):
        if self.worker or (not self.wifi.get() and not self.ble.get() and not self.demo):
            return
        self.load_profile()
        self.out = queue.Queue(maxsize=3000)
        self.worker = Scanners(self.out, self.wifi.get(), self.ble.get(), self.demo)
        self.start_button.configure(state='disabled')
        self.stop_button.configure(state='normal')
        for widget in (self.profile_box, self.load_button, self.wifi_check, self.ble_check):
            widget.configure(state='disabled')
        self.status_wifi.set('Wi-Fi: starting…' if self.wifi.get() or self.demo else 'Wi-Fi: disabled')
        self.status_ble.set('BLE: starting…' if self.ble.get() or self.demo else 'BLE: disabled')

    def stop(self):
        if self.worker:
            self.worker.stop.set()
            self.stop_button.configure(state='disabled')

    def visible(self, now):
        needle = self.query.get().casefold()
        mode = self.mode.get()
        return sorted([d for d in self.engine.active(now)
            if (mode == 'All signals' or d['kind'] == mode or (mode == 'Alerts' and d['flags']))
            and needle in (d['name'] + ' ' + d['id']).casefold()], key=lambda d: -d['rssi'])

    def tick(self):
        try:
            for _ in range(600):
                try:
                    kind, value = self.out.get_nowait()
                except queue.Empty:
                    break
                if kind == 'observation':
                    self.engine.ingest(value, time.time())
                elif kind == 'wifi':
                    self.status_wifi.set('Wi-Fi: ' + value)
                elif kind == 'ble':
                    self.status_ble.set('BLE: ' + value)
            now = time.time()
            self.engine.check_density(now)
            self.store.db.commit()
            if now - self.last_prune > 600:
                self.store.prune(now)
                self.last_prune = now
            if self.worker and not self.worker.alive():
                stopped = self.worker.stop.is_set()
                self.worker = None
                self.start_button.configure(state='normal')
                self.stop_button.configure(state='disabled')
                for widget in (self.profile_box, self.load_button, self.wifi_check, self.ble_check):
                    widget.configure(state='normal')
                if stopped:
                    self.status_wifi.set('Wi-Fi: stopped; recent observations age out after 45s')
                    self.status_ble.set('BLE: stopped')
            if self.closing:
                if self.worker:
                    self.root.after(100, self.tick)
                else:
                    self.store.db.close()
                    self.root.destroy()
                return
            self.render(now)
        except Exception as e:
            self.stop()
            self.status_wifi.set(f'Application error: {e}. Scanning stopped; see console for details.')
            import traceback
            traceback.print_exc()
        self.root.after(500, self.tick)

    def render(self, now):
        active = self.engine.active(now)
        wifi = sum(d['kind'] == 'Wi-Fi' for d in active)
        alerts = sum(bool(d['flags']) for d in active)
        state = 'SCANNING' if self.worker and not self.worker.stop.is_set() else 'STOPPED'
        self.stats.set(f'{state}   •   {wifi} Wi-Fi   /   {len(active)-wifi} BLE identifiers   /   {alerts} flagged   •   {self.engine.profile}')
        rows = self.visible(now)
        wanted = {d['id'] for d in rows}
        for ident in self.table.get_children():
            if ident not in wanted:
                self.table.delete(ident)
        for index, d in enumerate(rows):
            values = (d['kind'], d['name'], d['rssi'], ', '.join(sorted(d['flags'])) or
                      ('Known' if d['id'] in self.engine.baseline else 'Unbaselined'), f'{int(now-d["last"])}s')
            if self.table.exists(d['id']):
                self.table.item(d['id'], values=values)
                self.table.move(d['id'], '', index)
            else:
                self.table.insert('', index, iid=d['id'], values=values)
        event_rows = self.store.events(self.engine.profile)
        signature = repr(event_rows)
        if getattr(self, 'event_signature', None) != signature:
            self.event_signature = signature
            self.event_rows = event_rows
            self.events.delete(*self.events.get_children())
            for index, (t, ident, rule, message) in enumerate(event_rows):
                self.events.insert('', 'end', iid=str(index), values=(utc(t)[5:19].replace('T', ' '), rule, f'{ident}: {message}'))
        self.draw_radar(rows)
        self.show_details()

    def draw_radar(self, rows):
        c = self.radar
        c.delete('all')
        w, h = c.winfo_width(), c.winfo_height()
        x, y = w / 2, h / 2
        radius = max(25, min(w, h) / 2 - 30)
        for fraction, label in ((1, '-100'), (2/3, '-75'), (1/3, '-50')):
            r = radius * fraction
            c.create_oval(x-r, y-r, x+r, y+r, outline='#28435d')
            c.create_text(x+5, y-r+10, text=label+' dBm', fill=MUTED, anchor='w', font=('Segoe UI', 8))
        c.create_line(x-radius, y, x+radius, y, fill='#1c3147')
        c.create_line(x, y-radius, x, y+radius, fill='#1c3147')
        self.dot_positions = []
        for d in rows:
            dx, dy = radar_position(d['id'], d['rssi'], radius)
            px, py = x + dx, y + dy
            color = AMBER if d['flags'] else CYAN if d['kind'] == 'Wi-Fi' else BLUE
            r = 7 if d['id'] == self.selected else 5
            c.create_oval(px-r, py-r, px+r, py+r, fill=color,
                outline=FG if d['id'] == self.selected else PANEL, width=2)
            self.dot_positions.append((px, py, d['id']))
        if not rows:
            c.create_text(x, y+20, text='Waiting for signals' if self.worker else 'Press Start to scan', fill=MUTED)

    def radar_click(self, event):
        matches = sorted((((x-event.x)**2 + (y-event.y)**2, ident) for x,y,ident in self.dot_positions))
        if matches and matches[0][0] < 225:
            self.selected = matches[0][1]
            if self.table.exists(self.selected):
                self.table.selection_set(self.selected)
                self.table.see(self.selected)
            self.show_details()

    def select_row(self, _event):
        selected = self.table.selection()
        if selected:
            self.selected = selected[0]
            self.show_details()

    def select_event(self, _event):
        selection = self.events.selection()
        if selection:
            t, ident, rule, message = self.event_rows[int(selection[0])]
            messagebox.showinfo(rule, f'{utc(t)}\n{ident}\n\n{message}')

    def show_details(self):
        d = self.engine.devices.get(self.selected)
        if not d:
            self.details.configure(state='normal')
            self.details.delete('1.0', 'end')
            self.details.insert('1.0', 'Select a radar dot or table row for details.\n\nNo direction or physical distance is inferred.')
            self.details.configure(state='disabled')
            self.history.delete('all')
            return
        text = (f'{d["name"]}  |  {d["kind"]}  |  {d["rssi"]} dBm\n{d["id"]}\n'
                f'First this session: {utc(d["first"])}\nLast: {utc(d["last"])}\n'
                f'Flags: {", ".join(sorted(d["flags"])) or "none"}\n' + json.dumps(d['details'], ensure_ascii=False, indent=2))
        view = self.details.yview()[0]
        self.details.configure(state='normal')
        self.details.delete('1.0', 'end')
        self.details.insert('1.0', text)
        self.details.yview_moveto(view)
        self.details.configure(state='disabled')
        c = self.history
        c.delete('all')
        w, h = c.winfo_width(), c.winfo_height()
        c.create_text(8, 10, text='RSSI history • last 5 minutes', fill=MUTED, anchor='w', font=('Segoe UI', 9))
        history = d['history']
        if len(history) >= 2:
            end = time.time()
            points = []
            for t, rssi in history:
                points.extend((10 + (t-end+300)/300*(w-20), 28 + min(1,max(0,(-rssi-25)/75))*(h-35)))
            c.create_line(*points, fill=CYAN, width=2)

    def export(self, extension):
        filename = filedialog.asksaveasfilename(defaultextension='.'+extension,
            initialfile=f'SignalScope-{time.strftime("%Y%m%d-%H%M%S")}.{extension}',
            filetypes=[(extension.upper(), '*.'+extension)])
        if filename:
            try:
                self.store.db.commit()
                self.store.export(filename, self.engine.profile)
                messagebox.showinfo('Export complete', 'Saved observations for this location profile.\nJSON also contains the baseline and latest 300 events.')
            except Exception as e:
                messagebox.showerror('Export failed', str(e))

    def help(self):
        messagebox.showinfo('SignalScope help',
            '1. Enable Wi-Fi and Bluetooth in Windows.\n'
            '2. Choose a location profile, then Start.\n'
            '3. Let scanning run for a minute. Save current baseline.\n'
            '4. Review amber dots and Event timeline for changes.\n\n'
            'Radar radius = RSSI; angle is deterministic layout, not direction.\n'
            'Wi-Fi scans may send probes. BLE listens passively. No pairing or connecting is performed.\n'
            'Location permission may be required for Wi-Fi.\n'
            'BLE identifiers can rotate; counts do not equal physical devices.\n'
            'Shared SSID alerts can be normal mesh networks.\n'
            'Open Wi-Fi uses the privacy bit, not a full security audit.\n'
            'No hidden-camera, owner, tracker-brand, or location identification is claimed.\n\n'
            'History is stored locally for up to 30 days / 200,000 rows per table.\n'
            f'Data folder: {self.base}\n\n'
            'Demo data uses a separate database. See README.md for setup and troubleshooting.')

    def close(self):
        self.closing = True
        self.stop()
        self.stats.set('Stopping scanners and saving history…')

if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--demo', action='store_true')
    parser.add_argument('--data-dir', help='Override local data parent folder')
    parser.add_argument('--smoke-test', action='store_true', help=argparse.SUPPRESS)
    args = parser.parse_args()
    root = tk.Tk()
    app = App(root, args.demo, args.data_dir)
    if args.smoke_test:
        app.start()
        root.after(3500, app.close)
    root.mainloop()
