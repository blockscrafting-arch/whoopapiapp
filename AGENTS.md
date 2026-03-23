# WHOOP PWA (пакет «Стандарт»)

## Назначение

Web-приложение (PWA) с OAuth 2.0 к WHOOP API v2: Recovery, сон, Strain, тренировки, история 7 дней, рекомендации на русском, PostgreSQL, кеш ответов WHOOP.

## Стек

- Backend: FastAPI, SQLAlchemy 2 async, asyncpg, Alembic, httpx, itsdangerous (сессии), Fernet (шифрование токенов в БД)
- Frontend: vanilla JS, CSS, manifest + service worker
- БД: PostgreSQL
- Инфраструктура: Timeweb Cloud (Ubuntu), Nginx, systemd, Certbot (HTTPS)
- Репозиторий: `https://github.com/blockscrafting-arch/whoopapiapp.git` (ветка `main`)

## Архитектура

- Токены WHOOP только на backend, в БД в зашифрованном виде
- Сессия пользователя: signed cookie (Starlette SessionMiddleware), в cookie хранится только `user_id` (UUID)
- **Safari / iOS (OAuth callback)**: при `DEBUG=False` (прод) — `same_site="none"` и `https_only=True` (Secure), иначе после редиректа с WHOOP сессия не доходит и падает проверка `state` (CSRF). При `DEBUG=True` (локально) — `same_site="lax"`, `https_only=False`, чтобы работал `http://localhost`.
- **JSON и кириллица**: middleware в `main.py` дописывает `charset=utf-8` к `Content-Type` для `application/json` (Safari при «сыром» JSON без charset показывал mojibake).
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

- **ОС / хостинг**: Ubuntu 22.04 / 24.04, Timeweb Cloud; для стабильного SSH и HTTP с большинства сетей нужен **выделенный IPv4** (IPv6-only даёт `Connection timed out` у части клиентов).
- **Каталог на VPS**: `/var/www/whoop-pwa` — не использовать без правок пути `/opt/whoop-pwa/...` из шаблона `deploy/whoop-pwa.service`; в unit выровнять `WorkingDirectory`, `EnvironmentFile`, `ExecStart` под реальный `backend/` и `.venv/bin/uvicorn`.
- **systemd**: сообщения `Failed to load environment files` / `Failed to spawn 'start' task` / `Result: resources` чаще всего значат неверный путь к `.env`, к `uvicorn` или права пользователя `User=` (например `www-data`); после правок — `daemon-reload` и `restart`.
- **PostgreSQL**: БД `whoop_pwa`, пользователь `whoop`; на PostgreSQL 15+ выдать в этой БД `GRANT ALL ON SCHEMA public TO whoop`, иначе Alembic падает с `permission denied for schema public`.
- **Alembic**: `alembic/env.py` импортирует `app.config` — до `alembic upgrade head` в `backend/.env` должны быть все обязательные поля `Settings`, включая **`TOKEN_ENCRYPTION_KEY`** и **`SESSION_SECRET_KEY`**.
- **Nginx + TLS**: не ссылаться в конфиге на `ssl_certificate` / `ssl_certificate_key`, пока нет каталога `/etc/letsencrypt/live/<домен>/`; сначала только `listen 80` и прокси на `127.0.0.1:8000`, затем `certbot --nginx`.
- **DNS**: для прод-домена и Let’s Encrypt нужна **A-запись** на IPv4 сервера; один только **AAAA** резолвит в IPv6 и может не совпасть с доступностью сервера/файрвола.
- **Прод-домен заказчика**: `prowhoop.ru` — redirect URI WHOOP и `WHOOP_REDIRECT_URI` в `.env` должны совпадать с реальным HTTPS-URL после выдачи сертификата.
- **Доступ по SSH**: ключи `ed25519`; в клиентах импортировать **полный** приватный ключ (с `BEGIN OPENSSH PRIVATE KEY` / `END`).
- **Стек сервисов**: приложение слушает `127.0.0.1:8000` (uvicorn под systemd), снаружи — Nginx reverse proxy.
- **Обновление**: `git pull origin main` → `systemctl restart whoop-pwa`.
- **PWA-кеш**: Service Worker (`frontend/sw.js`) использует стратегию **Network First** + `CACHE = "whoop-pwa-v2"`. При выкатке новой версии достаточно сделать `git pull` + `systemctl restart` — SW подхватит новый контент при следующем визите пользователя. Для принудительного обновления кеша на клиентах увеличьте `CACHE` до `"whoop-pwa-v3"`.
- **Nginx Cache-Control**: `sw.js` — `no-store` (браузер не кэширует SW); `index.html` и `/api/…` — `no-store`; статика (CSS/JS/PNG) — `max-age=3600`. Это предотвращает показ старого UI после деплоя.

## Важные файлы

- `backend/app/main.py` — приложение, static, SessionMiddleware (Safari OAuth), JSON charset, middleware
- `backend/app/deps.py` — `CurrentUser` с `selectinload(User.token)` (без lazy-load в async)
- `backend/app/routers/auth.py` — OAuth (`is_new` + токены), `/auth/status` проверяет `is_active` в БД, disconnect
- `backend/app/services/whoop_client.py` — token (JSON+form), GET, revoke
- `backend/app/services/whoop_fetch.py` — 401/retry, пагинация коллекций
- `backend/app/services/token_manager.py` — refresh + advisory lock; `is_active=False` только при 400/401/403 от WHOOP при refresh; 429/5xx → временная ошибка (не разлогинивать)
- `backend/app/services/whoop_fetch.py` — перехват временной ошибки refresh → 503
- `backend/app/database.py` — `get_db`: commit только при успехе, иначе rollback
- `backend/app/services/cache_service.py` — UPSERT-кеш (нет race condition при параллельных запросах)
- `backend/app/routers/workouts.py` — тренировки через `get_json_collection` (пагинация, max 200 записей)
- `frontend/js/app.js` — экраны, `escapeHtml`, обработка `oauth_error`, retry при сетевой ошибке
- `frontend/js/api.js` — при 401: редирект на главную + reload; ожидание выгрузки страницы (без `null` после `fetch`)
- `frontend/sw.js` — Service Worker, Network First, версия кеша `whoop-pwa-v2`
- `deploy/nginx.conf` — Cache-Control: sw.js=no-store, index.html=no-store, статика=1h

## Документация WHOOP (официальная)

- OAuth: https://developer.whoop.com/docs/developing/oauth  
- OpenAPI: https://api.prod.whoop.com/developer/doc/openapi.json  
