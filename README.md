# WHOOP PWA (Стандарт)

MVP+: PWA + WHOOP OAuth 2.0 + PostgreSQL + кеш + тренировки + профиль.

## Требования

- Python 3.11+
- PostgreSQL 14+

## Быстрый старт (локально)

1. Создайте БД и пользователя PostgreSQL.
2. Скопируйте `backend/.env.example` → `backend/.env`, заполните переменные.
3. В WHOOP Developer Dashboard создайте приложение, scopes: `offline`, `read:profile`, `read:recovery`, `read:sleep`, `read:cycles`, `read:workout`. Redirect URI = ваш `WHOOP_REDIRECT_URI` (HTTPS).
4. Сгенерируйте `TOKEN_ENCRYPTION_KEY`:
   ```bash
   python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
   ```
5. Установка и миграции:
   ```bash
   cd backend
   python -m venv .venv
   .venv\Scripts\activate
   pip install -r requirements.txt
   alembic upgrade head
   ```
6. Иконки (опционально):
   ```bash
   python scripts/generate_icons.py
   ```
7. Запуск:
   ```bash
   uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
   ```
8. Откройте `http://localhost:8000` (для OAuth с WHOOP нужен публичный HTTPS — ngrok или сразу VPS).

## Деплой

- Настройте nginx по примеру `deploy/nginx.conf` (замените `server_name` и пути).
- systemd: `deploy/whoop-pwa.service` — скопируйте в `/etc/systemd/system/`, поправьте `User`, `WorkingDirectory`, `EnvironmentFile`.
- `certbot --nginx` для HTTPS.

## Структура

- `backend/app` — FastAPI
- `frontend/` — статика + PWA
- `deploy/` — примеры nginx и systemd

Подробности: [AGENTS.md](AGENTS.md).

## Поведение OAuth и данных

- Отказ пользователя или ошибка WHOOP на шаге авторизации → редирект с `?oauth_error=...` и сообщение на главной.
- **Отключить WHOOP**: отзыв access у WHOOP (если возможно) и **удаление локальной строки пользователя** в БД вместе с токенами и кешем (CASCADE).
- История / тренировки: при большом числе событий за период ответ может быть **усечён**; в JSON есть `pagination.*_truncated` / `pagination.truncated`, на фронте показывается подсказка.
- Refresh токена сериализуется через **PostgreSQL advisory lock** (несколько воркеров uvicorn допустимы). См. [AGENTS.md](AGENTS.md).

