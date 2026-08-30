# Деплой

В репозитории нет CI-конфигурации (`.github/workflows` и т.п.) и нет
явного файла конфигурации Coolify — деплой описан только через `Dockerfile`,
`.dockerignore` и `.env.production.example`, добавленные коммитом «Add
Coolify deployment config» (25.05.2026). Судя по названию и по формату
переменных (`/data/orienteering/...`) — тот же паттерн, что и у соседнего
`running-portal`: сборка образа из `Dockerfile` силами Coolify по пушу в
Git, с персистентным томом, смонтированным в `/data/orienteering`.
Домен/адрес конкретного деплоя, сеть Coolify и способ триггера сборки —
*не в этом репозитории, требует уточнения из инфраструктурной
документации/дашборда Coolify*.

## Dockerfile — multi-stage сборка

```dockerfile
FROM node:22-bookworm-slim AS claude-cli
RUN npm install -g @anthropic-ai/claude-code@latest && npm cache clean --force

FROM python:3.12-slim
# ... переменные окружения (см. таблицу ниже) ...
COPY --from=claude-cli /usr/local/bin/node /usr/local/bin/node
COPY --from=claude-cli /usr/local/bin/claude /usr/local/bin/claude
COPY --from=claude-cli /usr/local/lib/node_modules/@anthropic-ai /usr/local/lib/node_modules/@anthropic-ai
# ... pip install . ...
```

Первый стейдж ставит **Claude Code CLI** через `npm install -g`, второй
(рабочий) стейдж — Python 3.12-slim с самим порталом; из первого стейджа
копируются только `node`, `claude` и модуль `@anthropic-ai` — сам Node.js
образ в финальный слой не попадает целиком. Это осознанная зависимость
образа портала от npm-пакета Claude Code — без неё AI-тренер
(`/api/split-analysis/chat`) не сможет запустить CLI и будет отвечать
«Claude CLI не найден: …» на каждый запрос (см. [`ai-coach.md`](./ai-coach.md)).

Ключевые детали образа:

- Непривилегированный пользователь `app` (`addgroup --system app` /
  `adduser --system`), `USER app` перед запуском — процесс не работает от
  root.
- `HEALTHCHECK` — `GET /` каждые 30 с (5 с таймаут, старт через 20 с,
  3 попытки) простым `urllib.request` внутри контейнера.
- `CMD` перед запуском `uvicorn` сам создаёт директории для БД, загрузок
  и карт (`mkdir -p "$(dirname "$ORIENTEERING_PORTAL_DB_PATH")" ...`) —
  нужно на свежем/пустом персистентном томе, чтобы `StaticFiles`-монтирование
  `/uploads` не падало на отсутствующей директории.
- `apt-get install curl` — оставлен в образе (вероятно, для ручной
  диагностики/healthcheck-совместимости), не используется кодом портала
  напрямую.

## Переменные окружения продакшена (`.env.production.example`)

| Переменная | Значение в примере | Комментарий |
| --- | --- | --- |
| `PORT` | `8000` | порт `uvicorn` внутри контейнера |
| `ORIENTEERING_PORTAL_DB_PATH` | `/data/orienteering/orienteering.sqlite3` | на персистентном томе |
| `ORIENTEERING_PORTAL_UPLOAD_DIR` | `/data/orienteering/uploads` | сканы карт, GPX, снимки сплитов для AI-тренера |
| `ORIENTEERING_PORTAL_MAP_DIR` | `/data/orienteering/maps` | создаётся, но не используется кодом на деле (см. [`architecture.md`](./architecture.md#пограничныеустаревшие-части-замечено-при-чтении-кода)) |
| `ORIENTEERING_PORTAL_AUTO_LOGIN` | (пусто) | если задать — вход через `/login` не требуется, все запросы идут от имени указанного пользователя |
| `HOME` | `/data/orienteering` | чтобы Claude CLI хранил свои креды (`HOME/.claude`) на персистентном томе, а не терял их при пересоздании контейнера |
| `CLAUDE_CLI_PATH` | `/usr/local/bin/claude` | путь внутри образа, куда CLI скопирован из билд-стейджа |
| `ANTHROPIC_API_KEY` | (пусто в примере) | резервная авторизация CLI |

Файл — только *пример* (`.env.production.example`), не подключается
автоматически; реальные значения задаются в настройках сервиса в Coolify
(или эквивалентной среде), а не читаются из этого файла в рантайме.

## Данные и бэкапы

`data/` в репозитории (dev-режим) уже содержит рабочую SQLite-базу и её
резервные копии (`data/backups/orienteering-20260607-223807.sqlite3`,
`orienteering.sqlite3.before-review-dedupe-20260516-112011` — снята вручную
перед миграцией `_deduplicate_split_error_reviews`). Автоматизированного
расписания бэкапов в коде портала нет — файл БД просто лежит на
персистентном томе; ответственность за резервное копирование тома — вне
этого репозитория (инфраструктура Coolify/dev-server, как и у
`running-portal`, — *не задокументировано здесь, см. память
пространства/`home`-документацию инфраструктуры при необходимости*).

## Чек-лист для новой инсталляции

1. Смонтировать персистентный том в `/data/orienteering` (или свой путь —
   тогда синхронно поменять все три `ORIENTEERING_PORTAL_*_DIR`/`_PATH`).
2. Задать `HOME=/data/orienteering`, чтобы креды Claude CLI переживали
   пересоздание контейнера.
3. Авторизовать Claude CLI внутри контейнера (интерактивный
   `claude auth login` или готовый `HOME/.claude`/`ANTHROPIC_API_KEY`) —
   готового автоматизированного пути для этого в репозитории **нет**
   (в отличие от `/claude-auth` в `running-portal`); без этого шага
   AI-тренер не работает, остальной портал работает нормально.
4. Первый запуск сам создаст схему SQLite и засеет пользователей
   (двух обычных и одного админа, под реальными именами владельца портала)
   и справочник причин ошибок — см. [`data-model.md`](./data-model.md).
   Изменить набор пользователей можно только через `/settings/users`
   после первого входа под админом.
