"""Build a Windows executable with a strict public-asset allowlist."""
import argparse
import hashlib
import json
import subprocess
import sys
import zipfile
from pathlib import Path

from desktop import DesktopApplication
from client_desktop import ClientDesktopApplication

ROOT=Path(__file__).resolve().parents[1]

CLIENT_INSTRUCTIONS = '''Altegio Analytics для Windows

1. Распакуйте архив и откройте AltegioAnalyticsClient.exe.
2. Нажмите «Войти через Altegio» и войдите в свой аккаунт на странице Altegio.
3. Разрешите чтение, выберите филиал и нажмите «Загрузить мой отчёт».

Когортный анализ показывает выручку, LTV, возвращаемость и окупаемость по месяцам.
В разделе «Возможности допродаж» выберите услуги и пороги визитов. Скачайте
общий список клиентов или CSV для отдельной категории или услуги.
Если в CSV нужны телефоны, отметьте соответствующую галочку перед входом.

Первый сбор истории может занять несколько минут. Для повторной загрузки
нажмите «Обновить данные». Оставляйте окно приложения открытым во время работы.

Python и отдельные API-ключи не нужны. У приложения доступ к Altegio на чтение.
История хранится на этом компьютере в %LOCALAPPDATA%/AltegioAnalyticsClient.
Данные для входа защищены средствами Windows для текущего пользователя.
Сборка не имеет цифровой подписи издателя.
'''


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--client', action='store_true', help='Build the client edition.')
    client = parser.parse_args().client
    app = ClientDesktopApplication if client else DesktopApplication
    suffix = '-client' if client else ''
    destination=ROOT/f'data/raw/desktop-dist{suffix}'
    work=ROOT/f'data/raw/desktop-build{suffix}'
    command=[sys.executable,'-m','PyInstaller','--noconfirm','--clean','--onefile','--windowed','--name',app.profile_name,
             '--distpath',str(destination),'--workpath',str(work),'--specpath',str(work),'--paths',str(ROOT/'scripts')]
    for name in sorted(app.public_assets):
        source = ROOT/'dashboards'/name
        if client and name == 'index.html':
            source = work/'assets'/name
            source.parent.mkdir(parents=True, exist_ok=True)
            source.write_text(app.dashboard_template(), encoding='utf-8')
        command+=['--add-data',str(source)+';dashboards']
    if client:
        command+=['--exclude-module','desktop_mailings']
    command.append(str(ROOT/'scripts'/('client_desktop.py' if client else 'desktop.py')))
    subprocess.run(command,check=True,cwd=ROOT)
    exe=destination/f'{app.profile_name}.exe'
    subprocess.run([str(exe),'--smoke-test'],check=True,timeout=60)
    instructions='''Altegio Analytics — локальное приложение для Windows

1. Распакуйте архив и откройте AltegioAnalytics.exe.
2. Нажмите «Войти через Altegio». Введите пароль только на официальной странице Altegio.
3. Разрешите чтение выбранных филиалов, выберите филиал и нажмите «Загрузить мой отчёт».

Python, .env, API-ключи и ИИ-чат не нужны.
Первый сбор истории может занять несколько минут; прогресс виден в отчёте.
Дальше используйте кнопку «Обновить данные». Для работы оставляйте окно приложения открытым.
Пароль приложение не сохраняет. Доступ шифруется Windows для текущего пользователя.
Отчёты сохраняются в %LOCALAPPDATA%/AltegioAnalytics только на этом компьютере.
Данные Altegio читаются через MCP: когорты, бюджеты, подбор клиентов и CSV.
Рассылки создаются локально; их записи, покупки, конверсия и выручка обновляются через MCP.
Кнопка «Обновить результаты» получает свежие данные по всем отправленным рассылкам.
Изменение категорий клиентов через текущий read-only MCP недоступно; можно скачать выбранных клиентов для работы в кабинете Altegio.
Вход в новый аккаунт отделяет его снимки от предыдущего.

Это тестовая сборка без цифровой подписи издателя. Изменять настройки безопасности Windows для запуска не нужно.
'''
    if client:
        instructions = CLIENT_INSTRUCTIONS
    archive=ROOT/f'data/raw/{app.profile_name}-Windows.zip'
    with zipfile.ZipFile(archive,'w',zipfile.ZIP_DEFLATED) as bundle:
        bundle.write(exe,exe.name);bundle.writestr('START_HERE_RU.txt',instructions)
    digest=hashlib.sha256(exe.read_bytes()).hexdigest()
    (destination/'SHA256.txt').write_text(digest+'  '+exe.name+'\n')
    print(json.dumps({'exe':str(exe),'archive':str(archive),'sha256':digest}))


if __name__=='__main__':main()
