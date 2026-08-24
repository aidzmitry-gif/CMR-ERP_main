# deals-board-fe — scope

## Задача (уровень 2: касаемые файлы + верификация)

Реализовать на канбан-доске сделок CRM три блока ТЗ «Сделки 2.0»: **SALES-40** (стадия
«Закрыто: Отказ» + модалка причины), **SALES-43** (дни в стадии + фильтр «висяки»),
**SALES-44** (вероятность + взвешенная сумма) — строго по проверенному макету
`mockup_Сделки_2.0.html` и контракту ниже. Только фронтенд. Бэкенд (`modules/sales`)
делает оператор отдельно — твой клиент должен соответствовать контракту и **не падать,
если backend недоступен** (graceful fallback на mock, как уже сделано в `fetchBoardStages`).

Проверка: `npx vitest run src/lib/board.test.ts` зелёный + `npm run lint` чисто по тронутым
файлам + доска рендерится с fallback. Подробное ТЗ — в first-msg.

## LOOP CONTRACT

```yaml
scope:
  include:
    - frontend/src/components/kanban/**
    - frontend/src/lib/board.ts
    - frontend/src/lib/board.test.ts
    - frontend/src/lib/api.ts
    - frontend/src/lib/types.ts
  exclude:
    - frontend/src/components/chats-panel.tsx   # чужой воркер (chats-panel-fe)
    - frontend/src/components/funnel/**
    - frontend/src/components/sidebar.tsx
    - frontend/src/components/app-shell.tsx
    - frontend/src/lib/format.ts                # общий: читать можно, менять нельзя
    - frontend/src/lib/funnel*.ts
    - frontend/src/app/crm/owner/**             # экран РОПа — вне scope (другое окно)
    - frontend/src/app/erp/**                   # чужие воркеры (logistics/office/crypto)
    - modules/**                                # submodule, в worktree не выкачан
    - migrations/**
    - "**/*.py"
permissions:
  repo: write-branch
  db: none
  llm: enabled
budget:
  max_iterations: 6
  max_runtime_minutes: 45
  max_files_changed: 14
  max_consecutive_test_failures: 3
stop:
  - same_failure_seen_twice
  - file_touched_outside_scope
  - need_to_modify_shared_file        # format.ts/funnel/sidebar/chats-panel → NEEDS-ORCHESTRATOR-ANSWER
  - product_behavior_ambiguous
report:
  destination: coordination/deals-board-fe-status.md
```

## Acceptance gate

- [ ] Чистая логика в `lib/board.ts` (список стадий вкл. `lost`, сумма взвешенного, фильтр «висяки»)
      покрыта co-located vitest в `board.test.ts`, был RED до реализации (TDD).
- [ ] `npx vitest run src/lib/board.test.ts` → 0 фейлов.
- [ ] `npm run lint` — нет новых ошибок в тронутых файлах.
- [ ] **SALES-40:** на доске есть колонка «Закрыто: Отказ» (красная `#EF4444`); перевод карточки
      в отказ открывает модалку с **обязательным** выбором причины (+ необязательный коммент);
      без причины закрыть нельзя; на проигранной карточке — плашка причины.
- [ ] **SALES-43:** на карточке бейдж «🕒 N дн.» (из `stage_changed_at`, если есть; иначе скрыт);
      висяки (≥ порога) подсвечены; в тулбаре фильтр «Только висяки».
- [ ] **SALES-44:** на карточке бейдж вероятности и «≈ X ₽» взвешенно; в шапке колонки строка
      «взвешенно: X»; поля `probability`/`expected_close_date` проброшены в тип `Deal` и `mapDeal`.
- [ ] Доска рендерится при лежащем backend (graceful fallback), деньги — `formatMoney` (₽).
- [ ] НЕ запускался `npm run build` (известно сломан на `crypto/page.tsx` вне скоупа) — проверка vitest+lint.
- [ ] Тронуты только include-файлы; six-layer в теле коммита; status заканчивается `STATE: COMPLETE`.

## Anticipated failure modes
- Хочется править общий `format.ts`/`funnel`/`sidebar`/`chats-panel.tsx` — НЕ делай; если правда
  нужно — STOP, `NEEDS-ORCHESTRATOR-ANSWER`.
- `frontend/node_modules` отсутствует в worktree → перед vitest/lint один раз `npm install` в `frontend/`.
- `npm run build` падает на чужом `crypto/page.tsx` (Class D) — не гейтись на build, используй vitest+lint.
- Бэкенд-эндпоинтов ещё нет (404) — это ОК: UI строится по контракту, верификация без живого бэка.

## API-контракт (бэкенд сделает оператор; клиент должен совпасть)

Базовый клиент — как в существующем `lib/api.ts` (`BASE = BACKEND_URL`, `roleHeaders`, `cache:"no-store"`,
try/catch с fallback). Новые поля/эндпоинты:

- `GET /sales/board` → `BoardOut`: в `stages` теперь есть стадия `{"id":"lost","title":"Закрыто: Отказ","color":"#EF4444"}`.
  Каждый `DealRead` дополнен: `probability:int|null`, `expected_close_date:str|null`,
  `stage_changed_at:str|null`, `lost_reason_code:str|null`, `lost_comment:str|null`.
- `GET /sales/loss-reasons` → `[{code:str,title:str}]` (для выпадашки; при недоступности — локальный fallback-список причин).
- `POST /sales/deals/{id}/lose` body `{reason_code:str, comment?:str}` → `DealRead` (ставит стадию `lost`).
- `POST /sales/deals/{id}/win` → `DealRead` (ставит стадию `won`).
- `PATCH /sales/deals/{id}` — дополнительно принимает `{probability, expected_close_date}`.
- `GET /sales/deals?stuck_days=N` → `DealRead[]` (опционально; фильтр «висяки» можно считать и на клиенте по `stage_changed_at`).

Дефолты вероятности по стадии (если `probability` не задан): new 10, qual 30, prop 50, appr 75, won 100, lost 0.
Взвешенно = `amount * probability / 100`.

## Образец визуала
`mockup_Сделки_2.0.html` в корне репо — эталон вёрстки (цвета, бейджи, колонка отказа, модалка,
взвешенно в шапке колонки). Тумблер «Подсветить новое» показывает, что именно новое.
