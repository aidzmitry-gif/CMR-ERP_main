# Модуль legal — контекст для Claude

**Тип:** in-tree папка основного репозитория (не submodule)
**API-префикс:** `/legal`
**Схема БД:** `legal`
**Статус:** заглушка-каркас (CRUD + канбан, без событий/прав)

## Назначение
Юридический отдел: ведение дел/документов по этапам контроля договоров и взыскания
задолженности — от поступивших документов до судебного взыскания, канбан-воронкой.

## Файлы
- `module.py` — `LegalModule`; в `register` только роутер + виджет `Widget("legal","Юр. отдел",source="legal.cases")`.
- `models.py` — ORM `LegalCase` (схема `legal`).
- `schemas.py` — `LegalCaseCreate/Out`, `StageUpdate`.
- `routes.py` — эндпоинты `/legal`; в `_to_card` для стадии `claim` считает неустойку (пени) = 8% от суммы долга (демо-логика отображения).
- `stages.py` — 6 стадий: `inbox → contract → claim → writ → court → done`.

## Что регистрирует в ядре (register())
- Роуты `/legal` + виджет. Событий/подписок/workflow/permissions/ролей/telegram — **нет**.

## Модель данных (схема `legal`)
- `legal_case` (`LegalCase`): number, company, title, amount(Numeric), urgency(`Обычный`),
  owner, **stage**(`inbox`), next_step, due_date, created_at.

## API-эндпоинты
- `GET /legal/cases`, `POST /legal/cases` (201, авто-номер `ДЕЛО-2026-NNNN`).
- `GET /legal/board` — воронка через `core/runtime/funnel.build_board(STAGES, rows, _to_card)`.
- `PATCH /legal/cases/{id}` — смена стадии (`StageUpdate.stage`).

## Межмодульные связи и зависимости
- Проверка контрагентов по УНП в реестре ЕГР доступна через `core.services.registry`
  (наполняет модуль `integrations`, эндпоинт `GET /integrations/egr/{unp}`), но сам legal
  его пока не вызывает — связь только потенциальная.

## Подводные камни / детали
- Роуты сами `commit`; `core/db/repository.py` не используется; `stage` в PATCH не валидируется.
- Расчёт пени 8% и формат денег (`_fmt_money`, символ ₽) — захардкожены для демо-отображения карточки.
- Канбан — общий механизм `core/runtime/funnel.py`.
