"""Pack the Windows executable and the portable Mac client into one ZIP."""

import hashlib
from pathlib import Path
from zipfile import ZIP_DEFLATED, ZIP_STORED, ZipFile, ZipInfo

from client_desktop import ClientDesktopApplication


ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / 'data/raw'
RUNTIMES = {
    'aarch64': '7a2384641584ab9984221fcb0fc9265df465922af71be71410529e2a9c3f0540',
    'x86_64': 'd27d59a722db9f69926eb6d9564071247221f45a04da920ea7f3001c97e32f9b',
}
MAC_SCRIPTS = (
    'client_macos.py', 'client_desktop.py', 'desktop.py', 'local_credentials.py',
    'macos_credentials.py', 'local_mcp.py', 'local_report_data.py',
)
INSTRUCTIONS = '''Altegio Analytics для Windows и macOS

Полностью распакуйте ZIP в отдельную папку.

Windows (x64)
Откройте AltegioAnalyticsClient.exe. Оставьте окно приложения открытым.

Mac (Apple Silicon или Intel)
Откройте Start macOS.command. Отчёт откроется в браузере.
Оставьте окно Терминала открытым. Для завершения нажмите Ctrl+C.
При первом запуске приложение распакует встроенный Python в папку кэша.
Папка macOS должна оставаться рядом с файлом Start macOS.command.

В открывшемся отчёте нажмите «Войти через Altegio». Войдите своим аккаунтом
на странице Altegio, разрешите чтение и выберите филиал. Если в выгрузке нужны
телефоны клиентов, отметьте соответствующую галочку перед входом.

В приложении два отчёта: «Когортный анализ» и «Возможности допродаж».
Возможности допродаж можно выгрузить в CSV. Для получения свежей истории
нажмите «Обновить данные». Первый сбор истории может занять несколько минут.

Отчёты хранятся на вашем компьютере. Для подключения нужен интернет.
Отдельно устанавливать Python или получать API-ключи не требуется.
Запуски Windows и macOS не подписаны издателем.

Встроенный Python для Mac: Python Build Standalone, релиз 20261110.
https://github.com/astral-sh/python-build-standalone/releases/tag/20261110
'''


def main():
    executable = OUTPUT / 'desktop-dist-client/AltegioAnalyticsClient.exe'
    if not executable.is_file():
        raise FileNotFoundError('Сначала соберите Windows EXE: python scripts/build_desktop.py --client')

    runtimes = {}
    for target, expected in RUNTIMES.items():
        name = f'python-{target}.tar.gz'
        path = OUTPUT / 'macos-runtime' / name
        with path.open('rb') as source:
            if hashlib.file_digest(source, 'sha256').hexdigest() != expected:
                raise ValueError(f'Контрольная сумма не совпала: {name}')
        runtimes[name] = path

    archive = OUTPUT / 'AltegioAnalyticsClient-Mac-Windows.zip'
    draft = archive.with_suffix('.tmp')
    try:
        with ZipFile(draft, 'w', ZIP_DEFLATED) as bundle:
            bundle.write(executable, executable.name)
            bundle.writestr('START_HERE_RU.txt', INSTRUCTIONS.encode('utf-8-sig'))
            launcher = ZipInfo('Start macOS.command')
            launcher.create_system = 3
            launcher.external_attr = 0o100755 << 16
            launcher_text = (ROOT / 'scripts/start_macos.command').read_text(encoding='utf-8')
            bundle.writestr(launcher, launcher_text)
            for name in MAC_SCRIPTS:
                bundle.write(ROOT / 'scripts' / name, f'macOS/scripts/{name}')
            for name in sorted(ClientDesktopApplication.public_assets):
                if name == 'index.html':
                    bundle.writestr(f'macOS/dashboards/{name}', ClientDesktopApplication.dashboard_template())
                else:
                    bundle.write(ROOT / 'dashboards' / name, f'macOS/dashboards/{name}')
            for name, path in runtimes.items():
                bundle.write(path, f'macOS/runtime/{name}', compress_type=ZIP_STORED)
        draft.replace(archive)
    finally:
        draft.unlink(missing_ok=True)
    print(archive)


if __name__ == '__main__':
    main()
