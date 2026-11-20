"""Run the client edition in the Mac user's default browser."""

import json
import os
from pathlib import Path
import sys
import webbrowser

from client_desktop import ClientDesktopApplication
from desktop import open_running_instance
from macos_credentials import KeychainStore


class MacClientApplication(ClientDesktopApplication):
    credential_store = KeychainStore

    @classmethod
    def dashboard_template(cls):
        return super().dashboard_template().replace('<body data-client-edition>',
                                                     '<body data-client-edition data-macos>')


def main():
    if sys.platform != 'darwin':
        raise RuntimeError('Этот файл запуска предназначен для macOS.')
    import fcntl

    os.umask(0o077)
    profile = Path.home() / 'Library' / 'Application Support' / MacClientApplication.profile_name
    profile.mkdir(parents=True, exist_ok=True)
    with (profile / 'instance.lock').open('a') as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            if not open_running_instance(profile, MacClientApplication.app_id):
                print('Altegio Analytics уже запускается.')
            return

        try:
            app = MacClientApplication(profile, port=MacClientApplication.preferred_port)
        except OSError as error:
            import errno
            if error.errno != errno.EADDRINUSE:
                raise
            app = MacClientApplication(profile)

        instance = profile / 'instance.json'
        try:
            instance.write_text(json.dumps({'origin': app.origin, 'nonce': app.nonce}), encoding='utf-8')
            print(f'Altegio Analytics · {app.origin}', flush=True)
            print('Оставьте это окно открытым. Для завершения нажмите Ctrl+C.', flush=True)
            webbrowser.open(app.origin)
            app.httpd.serve_forever()
        finally:
            app.httpd.server_close()
            instance.unlink(missing_ok=True)


if __name__ == '__main__':
    try:
        main()
    except KeyboardInterrupt:
        pass
    except (OSError, ValueError, RuntimeError) as error:
        sys.exit(str(error))
