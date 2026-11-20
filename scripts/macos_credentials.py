"""Store Altegio credentials in the current user's macOS Keychain."""

import ctypes as ct
import hashlib
import json
from contextlib import ExitStack


class KeychainStore:
    not_found = -25300

    def __init__(self, folder):
        self.account = hashlib.sha256(str(folder.resolve()).encode('utf-8')).hexdigest().encode('ascii')
        self.security = ct.CDLL('/System/Library/Frameworks/Security.framework/Security')
        self.foundation = ct.CDLL('/System/Library/Frameworks/CoreFoundation.framework/CoreFoundation')
        pointer = ct.c_void_p
        out_pointer = ct.POINTER(pointer)
        functions = (
            (self.security, 'SecItemCopyMatching', [pointer, out_pointer], ct.c_int32),
            (self.security, 'SecItemUpdate', [pointer, pointer], ct.c_int32),
            (self.security, 'SecItemAdd', [pointer, out_pointer], ct.c_int32),
            (self.security, 'SecItemDelete', [pointer], ct.c_int32),
            (self.foundation, 'CFStringCreateWithCString', [pointer, ct.c_char_p, ct.c_uint32], pointer),
            (self.foundation, 'CFDictionaryCreate', [pointer, out_pointer, out_pointer, ct.c_long, pointer, pointer], pointer),
            (self.foundation, 'CFDataCreate', [pointer, ct.c_char_p, ct.c_long], pointer),
            (self.foundation, 'CFDataGetLength', [pointer], ct.c_long),
            (self.foundation, 'CFDataGetBytePtr', [pointer], pointer),
            (self.foundation, 'CFRelease', [pointer], None),
        )
        for library, name, arguments, result in functions:
            function = getattr(library, name)
            function.argtypes = arguments
            function.restype = result

    def _constant(self, name):
        return ct.c_void_p.in_dll(self.security, name).value

    def _own(self, stack, value):
        if not value:
            raise RuntimeError('Не удалось обратиться к Связке ключей macOS.')
        stack.callback(self.foundation.CFRelease, value)
        return value

    def _query(self, stack):
        def string(raw):
            value = self.foundation.CFStringCreateWithCString(None, raw, 0x08000100)
            return self._own(stack, value)

        return {
            'kSecClass': self._constant('kSecClassGenericPassword'),
            'kSecAttrService': string(b'Altegio Analytics Client'),
            'kSecAttrAccount': string(self.account),
        }

    def _dictionary(self, stack, fields):
        pointers = ct.c_void_p * len(fields)
        keys = pointers(*(self._constant(name) for name in fields))
        values = pointers(*fields.values())
        key_callbacks = ct.addressof(ct.c_byte.in_dll(self.foundation, 'kCFTypeDictionaryKeyCallBacks'))
        value_callbacks = ct.addressof(ct.c_byte.in_dll(self.foundation, 'kCFTypeDictionaryValueCallBacks'))
        value = self.foundation.CFDictionaryCreate(None, keys, values, len(fields), key_callbacks, value_callbacks)
        return self._own(stack, value)

    @staticmethod
    def _check(status):
        if status:
            raise OSError(f'Связка ключей macOS вернула ошибку {status}. Проверьте доступ к связке ключей входа.')

    def read(self):
        with ExitStack() as stack:
            query = self._query(stack)
            query['kSecReturnData'] = ct.c_void_p.in_dll(self.foundation, 'kCFBooleanTrue').value
            result = ct.c_void_p()
            status = self.security.SecItemCopyMatching(self._dictionary(stack, query), ct.byref(result))
            if status == self.not_found:
                return {}
            self._check(status)
            data = self._own(stack, result.value)
            raw = ct.string_at(self.foundation.CFDataGetBytePtr(data), self.foundation.CFDataGetLength(data))
            return json.loads(raw)

    def write(self, value):
        raw = json.dumps(value).encode('utf-8')
        with ExitStack() as stack:
            query = self._query(stack)
            data = self._own(stack, self.foundation.CFDataCreate(None, raw, len(raw)))
            change = {'kSecValueData': data}
            status = self.security.SecItemUpdate(self._dictionary(stack, query), self._dictionary(stack, change))
            if status == self.not_found:
                status = self.security.SecItemAdd(self._dictionary(stack, {**query, **change}), None)
            self._check(status)

    def clear(self):
        with ExitStack() as stack:
            status = self.security.SecItemDelete(self._dictionary(stack, self._query(stack)))
            if status != self.not_found:
                self._check(status)
