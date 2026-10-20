# Altegio Cohort Analyzer

Локальный портал когортного анализа / LTV с обновлением данных из Altegio **без AI-токенов**.

## Быстрый старт

1. Скопируйте `.env.example` → `.env` и заполните ключи.
2. Получите User Token (один раз):

```powershell
python scripts/auth_user_token.py
```

3. Запустите сервер:

```powershell
python scripts/server.py
```

4. Откройте http://127.0.0.1:8765/dashboards/index.html  
5. Нажмите **Обновить данные** — Python ходит в Altegio API и пересобирает `data/portal.json`.

## Переменные `.env`

| Ключ | Описание |
|------|----------|
| `ALTEGIO_PARTNER_TOKEN` | Partner Token из Developer Account |
| `ALTEGIO_USER_TOKEN` | User Token (через `auth_user_token.py`) |
| `ALTEGIO_LOCATION_ID` | ID филиала (Casa House = `764940`) |
| `ALTEGIO_PARTNER_ID` | Partner ID (опционально) |

`.env` не коммитится в git.

## API сервера

- `GET /api/health` — статус и наличие токенов
- `GET /api/data` — текущий snapshot портала
- `POST /api/sync` — синхронизация с Altegio (0 AI-токенов)

Ручной sync из терминала:

```powershell
python scripts/sync_from_altegio.py
```

## Важно

- Ключи API — секреты. Не публикуйте их в чат/репозиторий.
- Если токен уже светился в чате, лучше перевыпустить Partner Token в Developer Account.
