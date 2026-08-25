# Воркер: sales-e2e-board — e2e доски сделок (drag-drop / фильтры / воронки)

## Цель (Goal-Driven)
Добавить Playwright e2e для доски сделок `/crm/deals`: перенос карточки drag-and-drop между
стадиями, фильтры (приоритет + «Только висяки»), переключение воронки. Критерий готовности:
`npm run e2e` (headless, каталог `frontend/e2e/`) = зелёный, `tsc --noEmit` = OK, никаких
регрессий в поведении доски (`deals-workspace.tsx` не меняет логику, только точечные
`data-testid`).

## Контекст
РАБОЧАЯ ДИРЕКТОРИЯ: твой worktree (spawn_workers поставил cwd). НЕ упоминай путь главного
репо, НЕ делай `cd` туда.

- Playwright УЖЕ настроен: `frontend/playwright.config.ts` (testDir `./e2e`, projects
  `setup`→`chromium` с переиспользованием `storageState: "e2e/.auth/state.json"`, поднимает
  оба сервера сам — backend `uvicorn main:app --port 8000` на SQLite `e2e.db` + `npm run dev`
  на :3000). `@playwright/test` уже в `frontend/package.json` (devDependencies) — установка
  зависимости НЕ нужна, только `npx playwright install chromium`, если браузер не стоит.
- Каталог `frontend/e2e/` уже существует с тремя спеками — используй их как образец стиля:
  - `e2e/auth.setup.ts` — dev-логин: `page.goto("/login")` →
    `page.getByRole("button", { name: "Войти" }).click()` (кнопка активна с преднастроенным
    первым сотрудником — Директор, полный доступ) → `waitForURL("**/crm/deals")` → сохраняет
    `storageState`. Твои specs НЕ логинятся сами — они наследуют состояние через
    `dependencies: ["setup"]` в конфиге. НЕ трогай `auth.setup.ts` без необходимости.
  - `e2e/deal-card.spec.ts` — создание сделки: `form.shadow-pop`, плейсхолдеры
    `"CRM-2024-0200"`, `"ООО ..."`, `"Поставка ..."`, кнопка `"Создать"`.
  - `e2e/navigation.spec.ts` — простой пример перехода по сайдбару.
- ⚠️ SSE: `/crm/*` держат постоянное SSE-соединение (`app-shell.tsx` открывает `EventSource`
  на всё время жизни страницы). Playwright сам не виснет на этом (события — не блокирующий
  fetch), но НЕ жди `networkidle` для `/crm/deals` — SSE никогда не «затихает», так что
  `waitForLoadState("networkidle")` зависнет. Используй точечные `expect(locator).toBeVisible()`
  / `waitForURL` как в существующих specs, не `networkidle`.
- Реальная доска — `frontend/src/components/kanban/deals-workspace.tsx` (компонент
  `DealsWorkspace`), НЕ `funnel-board.tsx` (это used для других модулей — закупки/HR/etc, но
  НЕ для `/crm/deals`). Страница — `frontend/src/app/crm/deals/page.tsx`.
- Drag-and-drop реализован через `@dnd-kit/core`: колонки — `useDroppable({ id: stage.id })`,
  карточки — `useDraggable({ id: deal.id })`, сенсор `PointerSensor` с
  `activationConstraint: { distance: 8 }` — то есть простой `dragTo()` может не долетать до
  порога активации. Используй `page.mouse.move/down/move/up` с промежуточным шагом >8px перед
  финальным drop (типичный паттерн для `@dnd-kit` в Playwright), либо `locator.dragTo()` с
  доп. `steps` — проверь, что drag реально проходит порог (просядь через шаг move на пару px,
  потом на целевую колонку).
- Реальные id стадий (см. `frontend/src/lib/sales-stages.ts`, `STAGE_BY_ID`): `new`, `qual`,
  `price_req`, `has_price`, `meeting`, `invoice`, `protected`, `contract`, `won`, `cond_lost`,
  `lost`. Заголовки колонок — `stage.title` (напр. «Новая заявка», «Квалифицирован», «Успех»,
  «Отказ»). ⚠️ Drop в колонку `lost` («Отказ») НЕ двигает карточку напрямую — открывает
  `LoseDealModal` (нужна причина отказа). Для e2e стадии-move используй drop в обычную стадию
  (напр. `qual` или `meeting`), не в `lost`/`won` (won — тоже финальная, но без доп. модалки).
- Фильтры — тулбар доски в `deals-workspace.tsx`: кнопка «Фильтры» (`SlidersHorizontal`,
  toggle `filterOpen`) раскрывает ряд с приоритетами `["Все", "Высокий", "Средний", "Низкий"]`
  (кнопки без `data-testid`, различай по тексту через `getByRole("button", { name: "Высокий" })`
  и т.п.). Кнопка «Только висяки» (`Clock`) — toggle `stuckOnly`, подсвечивается
  `border-amber-400` при активации.
- Переключатель воронок — `frontend/src/components/kanban/funnel-tabs.tsx` (`FunnelTabs`),
  рендерится в `page.tsx` через `funnelTabs={<FunnelTabs active={activeFunnel} />}`.
  ⚠️ ГОТЧА: компонент рендерит `null`, пока `/sales/funnels` не вернёт **≥2** воронки — если
  в SQLite dev/e2e базе настроена только одна воронка (`new_clients`), таб-переключатель НЕ
  появится и e2e упадёт на несуществующий элемент. Перед тем как писать funnel-switch спек,
  ПРОВЕРЬ фактический ответ `/sales/funnels` на поднятом backend (`curl` или через сам
  Playwright `page.request.get`) — если воронка одна, тест обязан либо (a) сначала завести
  вторую воронку через API/seed для e2e-окружения, либо (b) если заводить воронку вне
  зоны ответственности (см. scope — только `frontend/e2e/**`), пометить сценарий
  `test.skip`/условно и явно написать в комментарии спека, что таб появляется только при ≥2
  воронках, со ссылкой на `funnel-tabs.tsx`. НЕ выдумывай моки — списки воронок реальные с
  бэка через `webServer` конфига.
- Test-id: в проде их сейчас нет (`grep data-testid` по `src/` находит только vitest-моки в
  `*.test.tsx`, не сами компоненты). Добавляй МИНИМАЛЬНО в реальных компонентах, где текстовые
  локаторы ненадёжны (drag-хендл карточки, колонка-дропзона по `stage.id`, кнопка «Фильтры»/
  «Только висяки» уже опознаются по тексту — testid им не обязателен). Рекомендуемые точки:
  - `frontend/src/components/kanban/deals-workspace.tsx`: на `<Column>` — `data-testid={`stage-column-${stage.id}`}` на корневой droppable `<div ref={setNodeRef}>`; на `<DraggableDeal>` — `data-testid={`deal-card-${deal.id}`}` на корневом draggable `<div ref={setNodeRef}>`.
  - Не трогай другую разметку/поведение — только добавляешь атрибут.

## Шаг 1 — подтвердить/донастроить playwright + dev-login helper
- Убедись, что `npx playwright install chromium` выполнен (если браузер не установлен — CI/
  свежий воркер могли не ставить бинарник).
- НЕ переписывай `auth.setup.ts` — он рабочий и переиспользуется всеми specs. Если тебе
  нужен дополнительный helper (напр. для проверки `/sales/funnels`), добавь отдельный
  небольшой файл `e2e/helpers.ts` (или инлайн в спеке) — не плоди абстракций сверх
  необходимого (лестница лени — см. корневой CLAUDE.md).
- Проверь, что `npm run e2e` вообще стартует зелёным на существующих трёх specs ДО того как
  добавлять свои — если что-то уже красное, разберись, это не твой баг, но не должен мешать.

## Шаг 2 — новый спек `e2e/deals-board.spec.ts`
Три сценария (можно отдельными `test(...)` в одном файле — доска общая, стейт независим
благодаря `fullyParallel: false, workers: 1`):
1. **Drag-and-drop смена стадии.** Открыть `/crm/deals`, найти существующую карточку в стадии
   `new` (или создать свою через форму «Создать сделку», как в `deal-card.spec.ts`, чтобы
   спек был самодостаточным на пустой доске CI), перетащить в колонку `qual` через
   pointer-путь с промежуточным шагом >8px (порог `PointerSensor`), проверить что карточка
   реально оказалась в целевой колонке (по `data-testid="stage-column-qual"` содержит
   карточку, либо счётчик карточек в колонке обновился).
2. **Фильтры.** Открыть «Фильтры», выбрать «Высокий» — проверить, что видимые карточки все
   с пометкой приоритета «Высокий» (или что число карточек уменьшилось/колонки перерисовались
   без «Средний»/«Низкий»); вернуть «Все». Отдельно — включить «Только висяки», проверить
   визуальную индикацию активного состояния кнопки (класс/aria, не только отсутствие ошибок).
3. **Переключение воронки.** Только если `/sales/funnels` реально возвращает ≥2 воронки (см.
   готчу выше) — кликнуть по второй вкладке, проверить смену `?funnel=` в URL и что колонки
   доски перезагрузились (напр. другой набор `stage-column-*` либо смена заголовка первой
   колонки). Если воронка одна — задокументировать в спеке через `test.skip(condition, reason)`
   с понятным reason, не заглушать молча.

## Шаг 3 — headless, без зависаний на SSE
- Прогони `npm run e2e` (по умолчанию headless; `--headed` только для локальной отладки, не
  коммитить флаг в конфиг/скрипты).
- Убедись, что ни один твой `expect`/`waitFor` не использует `networkidle` или неограниченный
  таймаут — SSE-соединение на `/crm/*` не даёт странице "успокоиться" в сетевом смысле.
- Если тест на CI должен переиспользовать уже поднятые сервера — конфиг уже это делает
  (`reuseExistingServer: !process.env.CI`), твой спек ничего дополнительно поднимать не должен.

## Запуск
```powershell
cd frontend
npm install                      # если ещё не ставили в этом worktree
npx playwright install chromium  # один раз, если бинарник браузера отсутствует
npm run e2e                      # = playwright test; сам поднимает backend (:8000, SQLite e2e.db) + next dev (:3000)
npx tsc --noEmit
```
Backend, который поднимает конфиг сам (`E2E_BACKEND_CMD` не задан — дефолт):
```
python -m uvicorn main:app --port 8000
```
с env `AIOS_DATABASE_URL=sqlite+aiosqlite:///./e2e.db`, `AIOS_AI_ENABLED=true`,
`PYTHONPATH=.` (см. `frontend/playwright.config.ts`, секция `webServer`) — воркеру НЕ нужно
поднимать его вручную, Playwright это делает сам при `npm run e2e`.

## DoD
- `npm run e2e` зелёный headless (все specs, включая три новых сценария плюс три существующих
  не сломаны).
- `npx tsc --noEmit` в `frontend/` чисто.
- Никаких изменений логики/поведения `deals-workspace.tsx` — только добавленные
  `data-testid` атрибуты (диф по этому файлу — только атрибуты, ни строки JSX-логики,
  ни импортов не тронуто).
- Коммит: e2e-специфичные файлы — в суперпроекте (frontend НЕ submodule, обычный коммит
  в текущем worktree). НЕ пушить.
- `STATE: COMPLETE` в `coordination/sales-e2e-board-status.md`.
- НЕ трогать backend/migrations/other modules — это чисто frontend e2e-полоса.
