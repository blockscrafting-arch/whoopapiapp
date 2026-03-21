# WHOOP PWA (пакет «Стандарт»)

## Назначение

Web-приложение (PWA) с OAuth 2.0 к WHOOP API v2: Recovery, сон, Strain, тренировки, история 7 дней, рекомендации на русском, PostgreSQL, кеш ответов WHOOP.

## Стек

- Backend: FastAPI, SQLAlchemy 2 async, asyncpg, Alembic, httpx, itsdangerous (сессии), Fernet (шифрование токенов в БД)
- Frontend: vanilla JS, CSS, manifest + service worker
- БД: PostgreSQL

## Архитектура

- Токены WHOOP только на backend, в БД в зашифрованном виде
- Сессия пользователя: signed cookie (Starlette SessionMiddleware), в cookie хранится только `user_id` (UUID)
- OAuth: authorization code → обмен на access/refresh; scope `offline` обязателен для refresh
- WHOOP API base: `https://api.prod.whoop.com/developer` (OpenAPI: `https://api.prod.whoop.com/developer/doc/openapi.json`)
- **Refresh и несколько воркеров**: WHOOP инвалидирует refresh при каждом успешном обновлении. Используется **короткая транзакция** с `pg_advisory_xact_lock(int,int)` + `SELECT ... FOR UPDATE` на строке `whoop_tokens` (см. `token_manager.py`). Блокировка снимается на COMMIT — безопасно при **нескольких процессах** uvicorn/gunicorn.
- **Token endpoint** (оф. WHOOP): в доке приведён JSON-тело; RFC 6749 часто использует `application/x-www-form-urlencoded`. Реализация: **сначала JSON**, fallback **form** (`whoop_client._post_token`).
- **Пагинация коллекций**: query `nextToken`, ответ `next_token` (OpenAPI). История и тренировки собирают до 8 страниц × 25 записей, максимум 200 записей на тип (`whoop_fetch.get_json_collection`).

## Безопасность и приватность

- При **«Отключить WHOOP»**: при наличии access — `DELETE /v2/user/access`, затем **`DELETE` строки `users`** (FK `ON DELETE CASCADE` убирает **`whoop_cache`** и **`whoop_tokens`**). Локальные PII (email, имя) не остаются на сервере.
- OAuth: при редиректе с `error` / `error_description` — редирект на `/?oauth_error=...`, фронт показывает toast и убирает query из URL.
- Фронт: пользовательские строки в DOM через **`escapeHtml`** (снижение XSS).
- Nginx-пример: `X-Frame-Options`, `nosniff`, HSTS, `Referrer-Policy`, `Permissions-Policy` (`deploy/nginx.conf`).

## Пороги рекомендаций (согласовано с заказчиком)

- Recovery &lt; 40% → отдых / лёгкая нагрузка
- Recovery ≥ 70% → позитивное сообщение о готовности к нагрузке
- Сон &lt; 6 ч (сумма light + SWS + REM из API) → недостаток сна
- Strain ≥ 14 → высокая нагрузка  

Доп. правило «увеличить нагрузку» (strain &lt; 10 + recovery &gt; 60) **убрано**, чтобы не расходиться с ТЗ.

## Переменные окружения

См. `backend/.env.example`. Обязательны: `DATABASE_URL`, `DATABASE_URL_SYNC`, `WHOOP_*`, `SESSION_SECRET_KEY`, `TOKEN_ENCRYPTION_KEY`.

## Команды

```bash
cd backend
python -m venv .venv
.venv\Scripts\activate   # Windows
pip install -r requirements.txt
alembic upgrade head
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

Иконки PWA (опционально):

```bash
python scripts/generate_icons.py
```

## Деплой

См. `deploy/nginx.conf`, `deploy/whoop-pwa.service`, `README.md`.

## Важные файлы

- `backend/app/main.py` — приложение, static, middleware
- `backend/app/routers/auth.py` — OAuth, ошибки callback, disconnect (revoke + удаление `users`)
- `backend/app/services/whoop_client.py` — token (JSON+form), GET, revoke
- `backend/app/services/whoop_fetch.py` — 401/retry, пагинация коллекций
- `backend/app/services/token_manager.py` — refresh + PostgreSQL advisory lock
- `backend/app/database.py` — `get_db`: commit только при успехе, иначе rollback
- `frontend/js/app.js` — экраны, `escapeHtml`, обработка `oauth_error`

## Документация WHOOP (официальная)

- OAuth: https://developer.whoop.com/docs/developing/oauth  
- OpenAPI: https://api.prod.whoop.com/developer/doc/openapi.json  
