"""User-scoped Windows DPAPI storage. Never ship a developer's credentials."""
import ctypes
import json
import os
from pathlib import Path
from ctypes import wintypes


class Blob(ctypes.Structure):
    _fields_ = [('size', wintypes.DWORD), ('data', ctypes.POINTER(ctypes.c_byte))]


def _blob(raw):
    buffer = ctypes.create_string_buffer(raw)
    return Blob(len(raw), ctypes.cast(buffer, ctypes.POINTER(ctypes.c_byte))), buffer


def protect(raw, decrypt=False):
    if os.name != 'nt':
        raise RuntimeError('Эта сборка предназначена для Windows.')
    crypt = ctypes.WinDLL('crypt32', use_last_error=True)
    kernel = ctypes.WinDLL('kernel32', use_last_error=True)
    kernel.LocalFree.argtypes = [ctypes.c_void_p]
    kernel.LocalFree.restype = ctypes.c_void_p
    source, keep = _blob(raw)
    entropy, keep_entropy = _blob(b'AltegioAnalyticsLocal.v1')
    result = Blob()
    if decrypt:
        function = crypt.CryptUnprotectData
        function.argtypes = [ctypes.POINTER(Blob), ctypes.c_void_p, ctypes.POINTER(Blob), ctypes.c_void_p, ctypes.c_void_p, wintypes.DWORD, ctypes.POINTER(Blob)]
        arguments = (ctypes.byref(source), None, ctypes.byref(entropy), None, None, 1, ctypes.byref(result))
    else:
        function = crypt.CryptProtectData
        function.argtypes = [ctypes.POINTER(Blob), wintypes.LPCWSTR, ctypes.POINTER(Blob), ctypes.c_void_p, ctypes.c_void_p, wintypes.DWORD, ctypes.POINTER(Blob)]
        arguments = (ctypes.byref(source), 'Altegio Analytics', ctypes.byref(entropy), None, None, 1, ctypes.byref(result))
    function.restype = wintypes.BOOL
    if not function(*arguments):
        raise ctypes.WinError(ctypes.get_last_error())
    try:
        return ctypes.string_at(result.data, result.size)
    finally:
        kernel.LocalFree(ctypes.cast(result.data, ctypes.c_void_p))


class CredentialStore:
    def __init__(self, folder):
        self.folder = Path(folder)
        self.folder.mkdir(parents=True, exist_ok=True)
        self.path = self.folder / 'connection.bin'

    def read(self):
        if not self.path.exists():
            return {}
        try:
            return json.loads(protect(self.path.read_bytes(), decrypt=True))
        except (OSError, ValueError):
            return {}

    def write(self, value):
        temporary = self.path.with_suffix('.tmp')
        temporary.write_bytes(protect(json.dumps(value).encode('utf-8')))
        os.replace(temporary, self.path)

    def clear(self):
        self.path.unlink(missing_ok=True)
