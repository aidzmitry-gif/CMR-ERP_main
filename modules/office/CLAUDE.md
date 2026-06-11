# Модуль office — контекст для Claude

**Тип:** in-tree папка основного репозитория (не submodule)
**API-префикс:** `/office`
**Схема БД:** `office`
**Статус:** заглушка-каркас (CRUD + канбан, без событий/прав)

## Назначение
Офис-менеджер: документооборот по сделкам после продажи — отгрузка → сбор документов →
оплата, в виде канбан-воронки. По сути постпродажный документальный конвейер.

## Файлы
- `module.py` — `OfficeModule`; в `register` только роутер + виджет `Widget("office","Офис-менеджер",source="office.docs")`.
- `models.py` — ORM `OfficeDoc` (схема `office`).
- `schemas.py` — `OfficeDocCreate/Out`, `StageUpdate`.
- `routes.py` — эндпоинты `/office`.
- `stages.py` — 5 стадий: `ready → shipped → docs → await_pay → paid`.

## Что регистрирует в ядре (register())
- Роуты `/office` + виджет. Событий/подписок/workflow/permissions/ролей/telegram — **нет**.

## Модель данных (схема `office`)
- `office_doc` (`OfficeDoc`): number, company, title, amount(Numeric), delivery, docs_status,
  priority(`Средний`), owner, **stage**(`ready`), next_step, op_date, created_at.

## API-эндпоинты
- `GET /office/docs`, `POST /office/docs` (201, авто-номер `ДОК-2026-NNNN`).
- `GET /office/board` — воронка через `core/runtime/funnel.build_board(STAGES, rows, _to_card)`.
- `PATCH /office/docs/{id}` — смена стадии (`StageUpdate.stage`).

## Подводные камни / детали
- Роуты сами `commit` (как и другие канбан-модули); `core/db/repository.py` не используется.
- `stage` в PATCH не валидируется против `STAGES`.
- Канбан — общий механизм `core/runtime/funnel.py` (см. также hr/legal/knowledge/procurement/production).
- Стадии воронки концептуально пересекаются с logistics/finance (отгрузка/оплата), но связь только смысловая — событий между ними нет.
