# LANGAME Telegram Bot

Operational Telegram bot for a LAN gaming club with exactly two roles: **Administrator** and **Владелец**.

## Foundation implemented

- secure Telegram access: unknown users are denied instead of becoming admins;
- Владелец bootstrap through `OWNER_TELEGRAM_IDS`;
- PostgreSQL + SQLAlchemy async;
- Alembic chain: `0001_initial` → `0002_clients_loyalty_mailing`;
- LANGAME client with persistent HTTP connection pool, timeout and normalized API errors;
- inventory domain: balances, immutable operations, write-offs, inventories and discrepancies;
- shifts and employee/club relations;
- salary domain;
- audit log;
- daily analytics tables;
- guests, loyalty groups, Telegram linking and marketing campaign foundation;
- Docker startup runs migrations before the bot.

## Source of truth

LANGAME remains the source of truth for its own operational data: employees/users, shifts, products, warehouse balances, product arrivals/sales, guest profiles and loyalty groups.

Our database owns the additional control layer: Telegram identities/roles, audit, inventory adjustments and write-offs, inventories, discrepancies, salary calculations, analytics aggregates, Telegram guest links/consent and marketing campaign state.

## LANGAME API

Base URL defaults to `https://sa-vlg1.langame.ru/public_api`.
Authentication uses the documented `X-Request-Token` header for the endpoints currently integrated by this project.

Integrated guest endpoints:
- `GET /guests/groups`;
- `POST /guests/search`.

The guest search payload intentionally preserves the field name `featues` from the supplied OpenAPI contract.

## Run

1. Copy `.env.example` to `.env`.
2. Fill `LANGAME_API_KEY`, `TELEGRAM_BOT_TOKEN`, `OWNER_TELEGRAM_IDS` and database settings.
3. Run `docker compose up --build`.
4. Migrations run automatically in the bot container (`alembic upgrade head`).

For local development, install the project dependencies and run `alembic upgrade head` before starting the bot.

## LANGAME read-only policy

The bot treats LANGAME as an external **read-only source of truth**. It can fetch and analyse users, shifts, clubs, products, stock, arrivals, sales, guest groups and guests, but it must not create, edit, delete or otherwise mutate LANGAME data.

Technical protection is enforced in `app/services/langame.py`: all mutating HTTP methods (`POST`, `PUT`, `PATCH`, `DELETE`) are blocked except `POST /guests/search`, which is an allowlisted read-only search endpoint from the LANGAME API contract. There is no generic write method exposed to the rest of the application.

`LANGAME_READ_ONLY=true` is mandatory by default. If it is set to `false`, the application refuses to start the LANGAME client.

The bot's own PostgreSQL database may still be changed for local business facts such as Telegram links, inventory checks, discrepancies, write-off requests/approvals and audit records. Those changes do **not** write back to LANGAME.

## Зарплата администраторов

- Смены читаются только из LANGAME через `GET /working_shifts/list`.
- Смены кэшируются в PostgreSQL и используются для расчёта часов.
- Базовое правило: почасовая ставка `hourly_rate`.
- Владелец задаёт ставку командой `/salary_rate 500`.
- Владелец синхронизирует смены: `/sync_shifts`.
- Владелец формирует расчётный период: `/salary_period YYYY-MM-DD YYYY-MM-DD`.
- Детализация: `/salary EMPLOYEE_ID YYYY-MM-DD YYYY-MM-DD`.
- Период можно подтвердить `/confirm_salary PERIOD_ID` и зарегистрировать выплату `/pay_salary PERIOD_ID [комментарий]`.
- Администратор видит свою текущую зарплату через `💰 Моя зарплата`.
- Выплата и подтверждение изменяют только PostgreSQL бота и не отправляют никаких изменений в LANGAME.


## Guest Telegram onboarding

- Владелец: `/guest_invite LANGAME_GUEST_ID` creates a one-time deep link valid for 7 days.
- Guest opens the link and Telegram is linked locally to the cached LANGAME guest.
- Guest explicitly grants or declines marketing consent.
- `/marketing_status` shows consent state.
- `/marketing_stop` revokes consent without unlinking Telegram.
- Consent and linking events are audited.
- No guest onboarding action writes to LANGAME.

## Analytics v1
меню владельца `📊 Аналитика` now provides a read-only dashboard for 7 days, 30 days and current month, plus focused views for sales, inventory, administrators, salary and clients. Sales are read directly from LANGAME; local data covers shifts, inventory, write-offs, discrepancies, salary and Telegram/marketing metrics. LANGAME remains read-only.

## Analytics v2 — administrators and shifts
Владелец → `📊 Аналитика` → `👥 Администраторы` shows a 30-day administrator ranking by product sales, hours, shift count and sales per hour. Selecting an administrator opens detailed shifts with sales attributed through LANGAME `working_shift_id`, cash difference, approved write-offs, discrepancies and overlapping salary periods.

Sales attribution uses the documented LANGAME `ProductsExpenseResponseDTO`: `working_shift_id`, `count`, `price_sale` and `cancel`. Cancelled checks are excluded. No sales are written back to LANGAME.


## Ежедневный отчёт владельцу

The bot can automatically send each Владелец a report for the previous calendar day in the configured timezone, followed by the corresponding Excel export. Configuration:
- `REPORT_TIMEZONE` (default `Europe/Moscow`);
- `REPORT_HOUR` (default `9`);
- `REPORT_MINUTE` (default `0`).

Delivery is idempotent per Владелец and report date and is recorded in `owner_daily_report_deliveries`. Failed deliveries are recorded for diagnostics.


## отчёт владельцу settings

Владелец → `⚙️ Настройки` → `📊 Ежедневный отчёт` позволяет включать/выключать ежедневный отчёт, менять время и IANA timezone, выбирать разделы отчёта и включать/выключать Excel. `➕ Добавить Владелец` добавляет второго/следующего Владелец в локальную БД без изменения LANGAME. Bootstrap owners из `OWNER_TELEGRAM_IDS` автоматически получают настройки по умолчанию.

## Владелец: управление доступом администраторов

В `⚙️ Настройки → 👤 Управление администраторами` владелец может:
- посмотреть текущую привязку Telegram и локальный доступ;
- заблокировать/разблокировать доступ администратора к боту;
- сменить привязанный Telegram ID;
- посмотреть последние действия по администратору.

Эти действия изменяют только локальную БД бота. Статус пользователя в LANGAME не изменяется. Все изменения доступа пишутся в `audit_log`.

## Stability v1.1

- LANGAME HTTP client is shared by all bot modules and is closed during shutdown.
- Владелец admin access binding is exclusive: rebinding a Telegram ID detaches any previous employee association.
- добавление владельца uses a dedicated FSM state instead of a global numeric-message handler.
- Administrator shift and personal statistics screens use synchronized local shift data and LANGAME product sales.
- User synchronization through `/users/list` follows pagination.
- Salary rate editing from the интерфейс владельца is backed by a dedicated FSM state.
- Duplicate mailing menu handlers were removed from the root router so the full mailing router receives those events.
- Migration `0009_cleanup_owner_report_index` removes a redundant unique index created by migration 0008 without rewriting an already-applied migration.

## v1.7 — контроль добросовестности и центр «Требует внимания»
- Добавлен раздел владельца `🔎 Контроль администраторов`.
- Анализируются повторяющиеся объективные сигналы: расхождения, списания, отмены продаж и ручные корректировки.
- Формируется объяснимый риск-скоринг 0–100 и причины срабатывания.
- Система не утверждает факт нарушения и не назначает виновного автоматически; итоговая проверка остаётся за владельцем.
- Панель владельца теперь показывает число профилей, требующих проверки, и включает их в центр `🔔 Требует внимания`.


## v1.10 — comparison with personal baseline
Owner can open a shift and use `📊 Сравнить с нормой`. The report compares the shift with up to 30 previous closed shifts of the same administrator over 90 days. Metrics: cancellation rate, bar/snacks sales per hour, approved writeoff units, discrepancy amount, and absolute cash difference. A warning is shown only with a sufficient history (5+ shifts), and the report explicitly treats deviations as review signals, not proof of misconduct.


## v1.12 — контроль и упрощение

- `🔎 Контроль администраторов` теперь является единой точкой входа для рейтинга риска; отдельный пользовательский пункт `🛡 Индекс риска администраторов` убран как дублирующий.
- Добавлено компактное `📁 Досье проверки`: индекс риска, причины, конкретные смены и связанные цепочки событий.
- Анализ личной нормы администратора больше не делает отдельный запрос LANGAME на каждую историческую смену: 90-дневные продажи читаются одним диапазоном и группируются по `working_shift_id`.
- Синхронизация остатков больше не затирает локальные списания/корректировки: к локальному контрольному остатку применяется только изменение между предыдущим и новым снимком LANGAME.
- Одобренные списания теперь сохраняют `shift_id` в `inventory_operations`, что улучшает расследование смен.
- Одобрение/отклонение списания дополнительно фиксируется в `audit_log`.

## Полный аудит системы

Система оставляет LANGAME источником истины для сотрудников, смен, каталога, склада, продаж, клиентов и групп лояльности. PostgreSQL используется как слой контроля, аудита, зарплаты, локальных инвентаризаций и маркетинга.

Сильные стороны: read-only защита LANGAME, две роли, аудит, неизменяемые локальные операции, привязка продаж к сменам, расследование смен, личные базовые линии и композитный риск.

Критичные зоны контроля: реальная интеграция Telegram/PostgreSQL/Docker ещё должна быть проверена на Windows; необходимо отдельно проверить корректность часовых поясов и реальные форматы ответов LANGAME на боевом стенде; клиентские группы синхронизируются ограниченно из-за состава `GuestDTO`; плановые рассылки пока не реализованы; `LangameSyncLog` существует как модель, но полноценное заполнение логами синхронизаций требует отдельного этапа.

В пользовательском интерфейсе убраны дублирующие пункты. Подробности оставлены только там, где они помогают владельцу принять решение или провести проверку.

## v1.17 — ночная уборка и бонус

При закрытии ночной смены администратор обязан подтвердить выполнение уборки помещения. За подтверждённую уборку начисляется фиксированный бонус 500 ₽.

Ночная смена определяется как смена, пересекающая полночь по часовому поясу Europe/Moscow. Бонус хранится в отчёте закрытия смены и автоматически учитывается при расчёте зарплатного периода. Повторное подтверждение не создаёт дополнительный бонус.

## v1.27 — реальные профили и привязка Telegram по username

Преднастроены 7 реальных профилей:
- Владельцы: Эдуард `@edonly_one`, Данил `@grda8`, Анатолий `@nemanikhin`.
- Администраторы: Иван `@Kenchik1786`, Анастасия `@nasyanasikova`, Вячеслав `@imapolzovatela28`, Юрий `@sigillcoree`.

Telegram ID заранее не хранятся и не угадываются. Пользователь с совпавшим username пишет `/start`, после чего создаётся заявка. Владелец подтверждает или отклоняет её в `🔗 Заявки на привязку`.

Для администраторов после синхронизации LANGAME профиль автоматически связывается с единственным активным сотрудником с совпадающим ФИО. Если совпадения нет, Telegram доступ можно подтвердить, но поле сотрудника останется пустым до последующей синхронизации/сопоставления.


## Telegram Native UI / Mini App

This version includes a Telegram-native navigation layer: OWNER and ADMIN top-level menus use Inline Keyboard callbacks, and an optional Telegram Mini App is served by the same application.

### Enable Mini App

1. Deploy the bot on a server with a public HTTPS hostname.
2. Set `MINI_APP_URL=https://your-domain.example/` in `.env`.
3. Set `WEB_PORT=8000` and expose port 8000 (the compose file already maps it).
4. Restart the bot. The bot will set its Telegram menu button to open the Mini App. Telegram also supports configuring the Main Mini App and menu button through @BotFather.

The Mini App validates Telegram `initData` server-side before exposing protected API data. It never treats frontend role information as authorization.

### Can the bot be configured without a computer?

Yes for **operational configuration after deployment**: owners can use the Telegram UI/Mini App to navigate and, where implemented, change business settings. @BotFather itself is also operated inside Telegram.

No for **initial deployment/code changes**: someone still needs a server/hosting environment and a public HTTPS URL for the Mini App. Once that infrastructure is running, day-to-day administration can be moved into Telegram.
