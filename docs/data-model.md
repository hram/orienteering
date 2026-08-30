# Модель данных

Источник истины — `SCHEMA` в `portal/db.py` (строки 14–149) плюс миграции
в `_migrate_schema` (добавляют колонки к уже существующим таблицам «на
лету» при каждом старте, без версионированных миграционных файлов —
эквивалент Django/Alembic migrations здесь нет). БД — один файл SQLite
(`aiosqlite`), без внешнего сервера.

Общие соглашения:

- Все `*_id` — `TEXT`, генерируются как `uuid4().hex` (`portal/db.py`,
  `uuid4().hex` в местах `INSERT`).
- `created_at`/`updated_at`/`reviewed_at` — ISO 8601 UTC-строки
  (`utc_now_iso()`), не SQLite `DATETIME`.
- Поля с суффиксом «`_json`» в этом документе физически хранятся как
  `TEXT` в схеме и (де)сериализуются функциями `serialize_json` /
  `deserialize_json`.

## `users`

Фиксированный список пользователей портала, без регистрации и без пароля.

| Поле | Тип | Описание |
| --- | --- | --- |
| `user_id` | TEXT PK | |
| `username` | TEXT UNIQUE | логин, используется для автовхода и авто-сопоставления с участником протокола |
| `display_name` | TEXT | отображаемое имя |
| `is_admin` | INTEGER (bool) | админ видит все тренировки/протоколы всех и управляет `/settings/*` |
| `created_at` | TEXT | |

Сеется при старте (`_seed_default_users`, `portal/db.py:214`): два
обычных пользователя и один админ, жёстко прописанные в `DEFAULT_USERS`
(в этом документе имена и логины заменены на обезличенные `user1`/`user2`/
`admin` — в самом коде используются настоящие имена владельца портала).
Добавлять/удалять пользователей можно только
через `/settings/users` (только админ; самого админа редактировать/удалять
нельзя — `portal/routers/settings.py`).

## `maps` + `map_georeferences`

Legacy-пара «одна карта — одна геопривязка» на тренировку, до появления
многослойных карт. Продолжает заполняться при каждой финализации
драфта — зеркалит **первый полный слой** из `map_layers` (см.
`finalize_import_draft` в `portal/db.py`), чтобы старый код,
читающий `trainings.map_id`, не ломался.

`maps`: `map_id` PK, `title`, `image_path`, `image_width`/`image_height`
(колонки заведены, но нигде не заполняются — всегда `NULL`), `created_at`.

`map_georeferences` (PK = `map_id`, 1:1 с `maps`): `method` (всегда
`"affine"` на сейчас), `control_points` (JSON списка `{pixel_x, pixel_y,
lat, lon}`), `transform` (JSON `AffineTransform.to_dict()` — 6
коэффициентов `lon_a..lon_c`, `lat_a..lat_c`), `residuals` (JSON ошибок
подгонки в метрах по каждой точке), `created_at`.

## `trainings`

Основная сущность — тренировка или старт с треком.

| Поле | Тип | Описание |
| --- | --- | --- |
| `training_id` | TEXT PK | |
| `title` | TEXT | |
| `date` | TEXT | дата тренировки (`YYYY-MM-DD`, из формы) |
| `training_type` | TEXT | `run` (по умолчанию для старых записей) / `rogaine` / другие — влияет на разметку КП (см. `course_control_label`) |
| `discipline` | TEXT | backfill'ится значением `'run'` при миграции, если было пусто |
| `location` | TEXT | |
| `map_id` | TEXT FK → `maps.map_id` | legacy-зеркало первого слоя карты, может быть `NULL` |
| `gpx_path` | TEXT | путь к исходному загруженному GPX-файлу |
| `notes` | TEXT | |
| `course_controls` | JSON | зеркало `course_controls` первого/основного слоя карты (для обратной совместимости) |
| `track_points` | JSON | список точек трека `{lat, lon, ele, time}` (после возможной обрезки в плеере) |
| `map_layers` | JSON | **источник истины** — список слоёв карты, см. ниже |
| `created_at` | TEXT | |

### Форма элемента `map_layers[i]` (см. `_normalize_map_layer`, `portal/db.py:352`)

```json
{
  "id": "map-1",
  "title": "Карта 1",
  "image_path": "data/uploads/imports/<draft_id>/map.jpg",
  "image_filename": "scan.jpg",
  "georef_method": "affine",
  "georef_control_points": [{"pixel_x": 120.0, "pixel_y": 40.0, "lat": 55.7, "lon": 37.6}, "..."],
  "georef_transform": {"lon_a": 0.0, "lon_b": 0.0, "lon_c": 0.0, "lat_a": 0.0, "lat_b": 0.0, "lat_c": 0.0},
  "georef_residuals": [{"pixel_x": 120.0, "pixel_y": 40.0, "lat_error": 0.0, "lon_error": 0.0, "meters": 0.0}],
  "course_controls": [{"index": 1, "label": "С", "kind": "start", "map_layer_id": "map-1", "...": "координаты КП, формат зависит от места создания (пиксели/lat-lon)"}]
}
```

### Разметка КП (`course_control_label` / `course_control_kind`, `portal/db.py:404`)

Для обычной дистанции (`is_rogaine=False`, ≥3 точек): индекс `0` → `"С"`
(старт), индекс `1` → `"К"` (точка начала ориентирования / «маркированная
точка»), последняя → `"Ф"` (финиш), остальные — порядковые номера КП
(`1, 2, 3, ...`, со сдвигом на -1 из-за точки `"К"`). Для рогейна
(`is_rogaine=True`) точки нумеруются подряд без выделенной точки «К».

## `training_import_drafts`

Черновик мастера создания/редактирования тренировки — все шаги (карта,
геопривязка, КП, трек, детали) пишут в одну запись здесь, пока пользователь
не нажмёт «Завершить» (`finalize_import_draft`). Содержит почти те же поля,
что и `trainings`, плюс:

| Поле | Описание |
| --- | --- |
| `edit_training_id` | если черновик открыт для **редактирования** существующей тренировки — id тренировки |
| `finalized_training_id` | после финализации — id созданной/обновлённой тренировки (повторный вызов finish идемпотентен для create-режима) |
| `subject_user_id` | пользователь, которому будет видна созданная тренировка (используется в `_seed_training_visibility`) |
| `track_gpx_path` / `track_gpx_filename` | исходный загруженный GPX до его разбора в `track_points` |

Три способа создать черновик (`portal/db.py`): `create_import_draft`
(с нуля), `create_edit_import_draft` (копия существующей тренировки для
правки), `create_clone_import_draft` (копия как основа для новой записи).

## `race_results`

Один импортированный протокол соревнования (или его группа/дисциплина).

| Поле | Тип | Описание |
| --- | --- | --- |
| `race_result_id` | TEXT PK | |
| `training_id` | TEXT FK → `trainings.training_id`, nullable | протокол можно сохранить сам по себе, без привязки к тренировке/треку |
| `race_date` | TEXT | дата старта; при миграции бэкафилливается из `event_meta`/URL, если не задана (`_backfill_race_dates`) |
| `source_url` | TEXT | исходный URL импорта |
| `event_name` / `event_meta` | TEXT | название и доп. описание события |
| `group_name` / `group_subtitle` | TEXT | группа/дистанция внутри события |
| `controls` | JSON | список КП протокола (коды, дистанции между ними, если есть) |
| `participants` | JSON | список участников со сплитами — структура зависит от `kind`, см. `race_protocol.py` (`_parse_participant` для `course`, `_parse_score_participant` для `score`) и `race_results.py` (`_parse_orgeo_participant` для Orgeo) |
| `self_row_index` | INTEGER | индекс строки «своего» участника среди `participants`, выбранного пользователем при импорте |
| `kind` | TEXT | `"course"` (классическая дистанция с фиксированными этапами КП, включая эстафетные `lap`-варианты) или `"score"` (рогейн/score-O — набор КП без фиксированного порядка, штраф за опоздание) |
| `created_at` | TEXT | |

## `training_visibility` / `race_result_visibility`

Простые связи «кому видна эта запись» (композитный PK
`(training_id, user_id)` / `(race_result_id, user_id)`). Заполняются
автоматически один раз:

- для тренировки — по `subject_user_id` драфта плюс все админы
  (`_seed_training_visibility`);
- для протокола — по совпадению имени участника с `username`/`display_name`
  пользователя (casefold, вхождение подстроки) плюс все админы
  (`_seed_race_result_visibility`). Это эвристика, а не точное сопоставление
  ФИО — при однофамильцах/неполном совпадении имени может не сработать.

Явного UI для ручного управления видимостью **не найдено** — только
автосидинг при создании/импорте.

## `error_reasons`

Настраиваемый (только админом, `/settings/error-reasons`) справочник
причин потери времени на сплите.

| Поле | Описание |
| --- | --- |
| `reason_id` | TEXT PK |
| `label` | текст причины |
| `is_active` | можно «выключить» причину без удаления (перестаёт предлагаться в новых обзорах, старые записи сохраняются) |
| `sort_order` | порядок в выпадающем списке |

Значения по умолчанию (`DEFAULT_ERROR_REASONS`, `portal/db.py:180`):
«Ошибка направления», «Плохой выбор пути», «Долгий вход в КП», «Остановка
на чтение карты», «Потеря контакта с картой», «Ошибка реализации
варианта», «Низкий темп без ошибки», «Техническая проблема GPS/карты»,
«Другое».

## `split_error_reviews`

Разбор одного проблемного сплита: сохранённая причина потери времени.
Уникальность — `UNIQUE (training_id, race_result_id, split_label,
from_control_label, to_control_label)` (плюс отдельный уникальный индекс
без `race_result_id` в составе, добавленный миграцией —
`split_error_reviews_training_split_unique`; после миграции старые
дублирующиеся записи схлопываются функцией `_deduplicate_split_error_reviews`).

| Поле | Описание |
| --- | --- |
| `review_id` | TEXT PK |
| `training_id` / `race_result_id` | к какому сплиту какой тренировки относится |
| `split_label`, `from_control_label`, `to_control_label` | идентификация конкретного перегона по меткам КП (а не по индексу — устойчиво к пересчёту сплитов) |
| `reason_id` | FK → `error_reasons`, либо `NULL` |
| `custom_reason` | свободный текст, если стандартной причины нет |
| `reviewed_at` | момент сохранения ответа (пусто, пока не сохранён) |

## `ai_analysis` — **не используется**

Таблица заведена в схеме (`training_id` PK → `trainings`, `analysis` JSON,
`created_at`) и есть `DELETE FROM ai_analysis` при удалении тренировки, но
ни одного места, где в неё что-то `INSERT`/`UPDATE`, в кодовой базе не
нашлось. AI-тренер (см. [`ai-coach.md`](./ai-coach.md)) работает без
сохранения истории на сервере — вся история диалога живёт в памяти
браузера на время открытого диалога. **Требует уточнения**: задел на
будущее или остаток более ранней реализации.
