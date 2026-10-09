"""Native WLAN API. Fixed-width types preserve the Windows ABI on test hosts."""
import ctypes as C
import sys
import time

U32, I32, U16, U8 = C.c_uint32, C.c_int32, C.c_uint16, C.c_uint8
class GUID(C.Structure):
    _fields_ = [('a', U32), ('b', U16), ('c', U16), ('d', U8 * 8)]
class Interface(C.Structure):
    _fields_ = [('guid', GUID), ('description', U16 * 256), ('state', U32)]
class SSID(C.Structure):
    _fields_ = [('length', U32), ('data', U8 * 32)]
class RateSet(C.Structure):
    _fields_ = [('length', U32), ('rates', U16 * 126)]
class BssEntry(C.Structure):
    _fields_ = [('ssid', SSID), ('phy_id', U32), ('mac', U8 * 6),
        ('bss_type', U32), ('phy_type', U32), ('rssi', I32), ('quality', U32),
        ('in_reg_domain', U8), ('beacon_period', U16), ('timestamp', C.c_uint64),
        ('host_timestamp', C.c_uint64), ('capability', U16), ('frequency', U32),
        ('rates', RateSet), ('ie_offset', U32), ('ie_size', U32)]

class Wifi:
    def __init__(self):
        if sys.platform != 'win32':
            raise RuntimeError('Live Wi-Fi scanning requires Windows. Use Demo.cmd to preview.')
        self.dll = C.WinDLL('wlanapi.dll')
        P = C.c_void_p
        for name, args in {
            'WlanOpenHandle': [U32, P, C.POINTER(U32), C.POINTER(P)],
            'WlanCloseHandle': [P, P],
            'WlanEnumInterfaces': [P, P, C.POINTER(P)],
            'WlanScan': [P, C.POINTER(GUID), P, P, P],
            'WlanGetNetworkBssList': [P, C.POINTER(GUID), P, U32, I32, P, C.POINTER(P)],
            'WlanFreeMemory': [P],
        }.items():
            fn = getattr(self.dll, name)
            fn.argtypes = args
            fn.restype = None if name == 'WlanFreeMemory' else U32
        self.handle = P()
        version = U32()
        self.check(self.dll.WlanOpenHandle(2, None, C.byref(version), C.byref(self.handle)))

    @staticmethod
    def check(code):
        if code:
            hints = {5: 'Enable Windows Settings > Privacy & security > Location and allow desktop apps access.',
                     1062: 'Start the WLAN AutoConfig service.',
                     0x80342002: 'Turn Wi-Fi on and disable airplane mode.'}
            detail = C.FormatError(code).strip() if sys.platform == 'win32' else ''
            raise RuntimeError(f'Windows WLAN error {code}: {hints.get(code, detail)}')

    def interfaces(self):
        ptr = C.c_void_p()
        self.check(self.dll.WlanEnumInterfaces(self.handle, None, C.byref(ptr)))
        try:
            count = U32.from_address(ptr.value).value
            if count > 128:
                raise RuntimeError('Unexpected WLAN interface count')
            return [Interface.from_buffer_copy(C.string_at(ptr.value + 8 + i * C.sizeof(Interface),
                C.sizeof(Interface))) for i in range(count)]
        finally:
            self.dll.WlanFreeMemory(ptr)

    def scan(self, stop):
        interfaces = self.interfaces()
        if not interfaces:
            raise RuntimeError('No Wi-Fi adapter found. Enable an adapter or attach a USB Wi-Fi adapter.')
        usable, errors = [], []
        for item in interfaces:
            try:
                self.check(self.dll.WlanScan(self.handle, C.byref(item.guid), None, None, None))
                usable.append(item)
            except RuntimeError as e:
                errors.append(str(e))
        if not usable:
            raise RuntimeError('; '.join(errors))
        if stop.wait(4.5):
            return [], []
        rows = {}
        for item in usable:
            ptr = C.c_void_p()
            try:
                self.check(self.dll.WlanGetNetworkBssList(self.handle, C.byref(item.guid), None, 3, 0, None, C.byref(ptr)))
                size = U32.from_address(ptr.value).value
                count = U32.from_address(ptr.value + 4).value
                if size < 8 or count > (size - 8) // C.sizeof(BssEntry):
                    raise RuntimeError('Invalid WLAN response size')
                for i in range(count):
                    entry = BssEntry.from_address(ptr.value + 8 + i * C.sizeof(BssEntry))
                    if entry.ssid.length > 32:
                        continue
                    # Windows can retain old entries in its BSS cache. Never mark those as fresh sightings.
                    seen = entry.host_timestamp / 10_000_000 - 11644473600
                    if abs(time.time() - seen) > 30:
                        continue
                    name = bytes(entry.ssid.data[:entry.ssid.length]).decode('utf-8', 'replace') or '(hidden SSID)'
                    mac = ':'.join(f'{b:02X}' for b in entry.mac)
                    ident = 'wifi:' + mac
                    row = dict(id=ident, kind='Wi-Fi', name=name, rssi=int(entry.rssi), details={
                        'bssid': mac, 'frequency_mhz': entry.frequency / 1000,
                        'privacy': bool(entry.capability & 0x10),
                        'security_note': 'Privacy bit only; does not distinguish WEP/WPA/WPA2/WPA3.',
                        'quality_percent': int(entry.quality),
                        'adapter': bytes(item.description).decode('utf-16-le').split('\0')[0]})
                    if ident not in rows or row['rssi'] > rows[ident]['rssi']:
                        rows[ident] = row
            except RuntimeError as e:
                errors.append(str(e))
            finally:
                if ptr.value:
                    self.dll.WlanFreeMemory(ptr)
        return list(rows.values()), errors

    def close(self):
        if self.handle:
            self.dll.WlanCloseHandle(self.handle, None)
            self.handle = None
