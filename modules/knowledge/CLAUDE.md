# Модуль knowledge — контекст для Claude

**Тип:** in-tree папка основного репозитория (не submodule)
**API-префикс:** `/knowledge`
**Схема БД:** `knowledge`
**Статус:** частично наполнен (одна таблица + CRUD + канбан-доска; без AI/RAG)

## Назначение
«База знаний» здесь = программа **обучения сотрудников** в виде канбана. Курсы
(видео/тест/документ/практика) распределены по разделам онбординга: тестовая неделя,
знакомство с компанией, испытательный срок, ИИ-обучение, развитие. У курса есть
прогресс прохождения (%). Это НЕ RAG-база документов: pgvector/эмбеддинги в коде
не используются (поиск/семантика отсутствуют).

## Файлы
- `module.py` — `KnowledgeModule(ModuleContract)`, фабрика `get_module()`.
- `routes.py` — HTTP-API (`router`, tag `knowledge`); маппер `_to_card` курс → `FunnelCard`.
- `models.py` — ORM-модель `Course` в схеме `knowledge`.
- `schemas.py` — Pydantic: `CourseCreate`, `CourseOut`, `StageUpdate`.
- `stages.py` — `STAGES`: 5 разделов программы (порядок = колонки доски).
- `__init__.py` — докстринг пакета.

## Что регистрирует в ядре (register())
- **Роуты:** `core.include_router(routes.router, prefix="/knowledge")`.
- **Виджеты:** `core.register_widget(Widget("knowledge", "База знаний", source="knowledge.courses"))`.
- Подписок, workflow, permissions, ролей, telegram — НЕ регистрирует.

## События
- **Публикует**: ничего (event_bus не вызывается).
- **Подписан на**: ничего (`core.subscribe` не используется).

## Модель данных (таблицы схемы)
- `knowledge.course` (ORM `Course`): `id` (PK), `number` (код, авто-`КУРС-NNN`),
  `title`, `description`, `kind` (тип контента, дефолт «Документ»), `duration` (минут),
  `progress` (%), `audience`, `stage` (id раздела, дефолт `trial`), `created_at`.
  Связей (FK) нет. **Vector-колонок / эмбеддингов нет.**

## API-эндпоинты (ключевые)
- `GET /knowledge/courses` — плоский список курсов (сорт. по `id` убыв.).
- `GET /knowledge/board` — канбан обучения: курсы сгруппированы по `STAGES`
  через общий `build_board` (`core/runtime/funnel.py`). Статус/кнопка карточки
  выводятся из `progress`: ≥100 → «Пройдено/Повторить», ≤0 → «Не начат/Начать»,
  иначе «В процессе/Продолжить →».
- `POST /knowledge/courses` — создать курс; `number` генерируется, если пуст.
- `PATCH /knowledge/courses/{id}` — переместить курс в другой раздел (`StageUpdate.stage`).

## Межмодульные связи и зависимости
- Зависит от ядра: `core.runtime.contract` (`ModuleContract`, `Widget`),
  `core.runtime.core.Core`, `core.runtime.deps.get_session`, `core.db.base.Base`,
  и переиспользуемой воронки `core.runtime.funnel` (`FunnelCard`, `FunnelBoardOut`,
  `build_board`) — тот же паттерн доски, что у `sales`.
- К внутренностям других модулей не обращается. Включён в `ENABLED_MODULES`
  (`config/modules.py`).

## Подводные камни / детали
- Несмотря на название «база знаний», pgvector/RAG/AI-интеграции тут НЕТ — это
  канбан онбординга/обучения. Если по дорожной карте появится семантический поиск
  по документам, его нужно добавлять (vector-колонка + эмбеддинги + поиск).
- Роуты сами вызывают `session.commit()` (в отличие от паттерна «репозитории не
  коммитят» — здесь CRUD идёт напрямую в роуте, без `core/db/repository.py`).
- `id` раздела (`stage`) не валидируется против `STAGES`: `PATCH`/`POST` примут
  любую строку; курс с неизвестным `stage` просто не попадёт ни в одну колонку доски.
- Сумма стадии в доске всегда 0 (`FunnelCard.amount` не заполняется) — обучение без денежного агрегата.