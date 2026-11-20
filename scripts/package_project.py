"""Build a runnable local app archive without credentials or salon snapshots."""
import argparse
import json
import re
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RUNTIME = (
    'altegio_client.py', 'auth_user_token.py', 'env_loader.py', 'branch_access.py',
    'server.py', 'sync_from_altegio.py', 'upsell_categories.py', 'mailing_campaigns.py',
    'automation_worker.py', 'install_automation_startup.ps1', 'open_dashboard.ps1',
)


def package(destination):
    files = [ROOT / name for name in ('.env.example', '.gitignore', 'README.md', 'requirements.txt', 'get-token.bat', 'Open Dashboard.bat')]
    files += [ROOT / 'scripts' / name for name in RUNTIME]
    files += [ROOT / 'dashboards' / name for name in ('index.html', 'campaign-comparison.js', 'monthly-budgets.js', 'upsell.js', 'mailings.js')]
    files += [ROOT / 'dashboards' / 'automation-sandbox' / name for name in
              ('index.html', 'styles.css', 'catalog.js', 'engine.js', 'app.js')]
    html = (ROOT / 'dashboards/index.html').read_text(encoding='utf-8')
    match = re.search(r'^let DB=(.*);$', html, re.M)
    dataset = json.loads(match.group(1))
    if dataset.get('clients') or dataset.get('location'):
        raise ValueError('Dashboard must start without a salon or client data')
    # Compare against actual local credentials without putting them in output.
    from env_loader import get_env
    secrets = [get_env(key) for key in ('ALTEGIO_PARTNER_TOKEN', 'ALTEGIO_USER_TOKEN')]
    for file in files:
        text = file.read_text(encoding='utf-8-sig')
        if any(secret and len(secret) > 8 and secret in text for secret in secrets):
            raise ValueError('Credential detected in ' + file.name)
    destination = Path(destination)
    destination.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(destination, 'w', zipfile.ZIP_DEFLATED) as archive:
        for file in files:
            archive.write(file, 'altegio-analytics/' + file.relative_to(ROOT).as_posix())
        archive.writestr('altegio-analytics/START_HERE_RU.md', '''# Подключение своего салона

1. Установите Python 3.10 или новее и распакуйте архив.
2. Скопируйте .env.example в .env и заполните собственные Partner Token и User Token.
   Получить User Token можно командой: python scripts/auth_user_token.py
3. ALTEGIO_LOCATION_ID можно оставить пустым: список филиалов будет загружен из вашего аккаунта.
4. Дважды щёлкните Open Dashboard.bat — локальный сервер запустится скрыто, затем откроется отчёт.
5. Автоматизация категорий доступна в боковом меню. Сначала проверьте правила на примерах.
   Она выключена по умолчанию. Для работы нужны права редактирования карточек клиентов.
7. Чтобы сервер запускался после входа в Windows, один раз выполните в PowerShell:
   powershell -ExecutionPolicy Bypass -File scripts/install_automation_startup.ps1

Без подключения отчёт пуст. Чужие ключи, снимки, данные клиентов и демо-салон в архив не входят.
Авторизация в Altegio в соседней вкладке браузера сама по себе не подключает этот отчёт.
HTML-файл нельзя открывать двойным кликом: нужен локальный сервер.
Настройки и журнал автоматизации хранятся локально в data/automation. Включение правил
изменяет категории клиентов в Altegio; read-only Windows EXE эту возможность не имеет.
''')
    with zipfile.ZipFile(destination) as archive:
        assert archive.testzip() is None
        assert not any('/data/' in name or name.endswith('/.env') for name in archive.namelist())
    print(json.dumps({'archive': str(destination.resolve()), 'files': len(files) + 1}))


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('destination', type=Path)
    package(parser.parse_args().destination)
