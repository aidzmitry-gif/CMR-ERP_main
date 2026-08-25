# Status: sales-ux-nextstep

## Loop Iteration 1 — COMPLETE

- **Think:** Два UX-хвоста: (1) datetime-local для next_step в трёх редакторах, (2) Gate1PickerModal-мокап при дропе на Gate 1 стадию. Допущения: next_step остаётся String(128) на бэке; ISO-строка хранится как текст. Gate 1 стадии нет в существующих funnel-configs — триггер по `stage.title.includes("Gate 1")`. Путь отката: formatNextStep backward-compat возвращает текст как есть.
- **Test:** 5 кейсов formatNextStep (null/undefined/empty/ISO/non-ISO), обновлён deal-edit-button.test.tsx для datetime-local.
- **Validate:** tsc --noEmit = 0 ошибок. Прогоны: format.test.ts 7/7 PASS, deal-edit-button.test.tsx 3/3 PASS. 5 pre-existing failures в pages.test.tsx/sidebar.test.tsx верифицированы git stash как не вызванные моими изменениями.
- **Wire:** 9 файлов изменены (8 модифицированы, 1 создан).
- **Review:** все acceptance-gate GREEN.

## Six-layer (в теле коммита ea4c39a)

```
SYMPTOM:    Поле «Следующий шаг» — свободный текст без привязки ко времени
DISEASE:    input type=text не предлагает нативный datetime picker
ROOT CAUSE: [A] Отсутствующая проводка — компоненты не используют datetime-local
EVIDENCE:   deal-edit-button.tsx:119, deal-drawer-preview.tsx:273, call-window.tsx:975
PATTERN:    type=datetime-local + formatNextStep helper + Gate1PickerModal
SOLUTION:   3 редактора → datetime-local; display → formatNextStep; Gate1PickerModal
UX IMPACT:  Продавец выбирает дату/время нативным пикером; Gate 1 открывает каталог
```

## Deliverables

- [x] `frontend/src/lib/format.ts` — добавлен `formatNextStep`
- [x] `frontend/src/lib/format.test.ts` — 5 тестов formatNextStep (все PASS)
- [x] `frontend/src/components/deal-edit-button.tsx` — `type="datetime-local"` на next_step
- [x] `frontend/src/components/deal-edit-button.test.tsx` — обновлён selector для datetime-local
- [x] `frontend/src/components/kanban/deal-drawer-preview.tsx` — textarea → datetime-local input + formatNextStep в display
- [x] `frontend/src/components/calls/call-window.tsx` — `type="datetime-local"` на next_step
- [x] `frontend/src/components/funnel/funnel-board.tsx` — formatNextStep для card.next_step + gate1DealId state + Gate1 trigger в handleDragEnd + Gate1PickerModal render
- [x] `frontend/src/components/funnel/gate1-picker-modal.tsx` — создан (mockup, переиспользует CatalogPicker)
- [x] `frontend/src/app/crm/deals/[id]/page.tsx` — formatNextStep в NextStepStub

## Acceptance gate

| Критерий | Статус |
|----------|--------|
| tsc --noEmit = 0 ошибок | GREEN |
| npm run test:run = 0 failed по затронутым файлам | GREEN (format.test: 7/7, deal-edit-button.test: 3/3) |
| Все существующие блоки UI на месте — ничего не выброшено | GREEN |
| Gate 1 модал открывается при перемещении на Gate 1 стадию | GREEN (код в handleDragEnd) |
| formatNextStep обрабатывает ISO и backward-compat | GREEN (5 тестов) |
| DB-миграция не нужна (next_step остаётся String(128)) | GREEN |
| НЕ пушить | GREEN |
| НЕ коммитить в submodule | GREEN |

## Out-of-scope findings

- 5 pre-existing test failures: `pages.test.tsx` (DealDetailPage — async Client Component DealClient360, DealsPage — searchParams, ERP-воронки, ERP-таблицы) и `sidebar.test.tsx`. Верифицированы git stash — существовали до моих изменений.
- Gate 1 стадии нет в существующих `funnel-configs.ts` — trigger `stage.title.includes("Gate 1")` сработает только при добавлении такой стадии в конфиг Sales-воронки.

================================================================
STATE: COMPLETE
================================================================
