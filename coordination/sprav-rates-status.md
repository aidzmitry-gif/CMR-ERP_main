# sprav-rates — Status

## Worktree
Path: D:\6 Проекты\CRM ERP\crm-worker-sprav-rates
Branch: sprav-rates
Spawned at: 2026-06-15T14:52:52.521435+00:00
Completed at: 2026-06-15T18:50Z

## Karpathy 5-step loop

### Iteration 1

**Think:** Прочитал scope, common-контракт, reference-data.ts (целиком), preview-HTML.
Допущения:
- `addRateVersion("vat-rates", ...)` — payload-контракт не описан в scope → форма add для НДС не включена (только currency).
- Для as-of lookup `currencyRateAsOf(key, on)` требует `key = currency_code` — в scope явно описано.
- Backend может как закрывать предыдущую версию сразу (при добавлении future), так и оставлять её open. `versionStatus` корректен для обоих вариантов (проверяет `start_date > today` до `end_date IS NULL`).

**Test (написать файлы):**
- `lib/spravochniki-rates.ts` — чистые хелперы `versionStatus` + `formatDate`.
- `lib/spravochniki-rates.test.ts` — 10 vitest-тестов.
- `components/erp/spravochniki/sprav-rates.tsx` — "use client" компонент.
- `app/erp/spravochniki/rates/page.tsx` — SSR страница.

**Validate:**
- Ошибка tsc: `title` не является пропом `Clock` из lucide-react → убран.
- После фикса: `npx tsc --noEmit` → чисто (0 ошибок).
- `npx vitest run src/lib/spravochniki-rates.test.ts` → 10/10.

**Wire:** Коммит `eed06d3` — 4 файла, 697 строк.

**Review:** Acceptance gate проверен ниже.

## Acceptance gate

- [x] `/erp/spravochniki/rates` показывает версии курса/НДС, текущая выделена (`isActive = versionStatus === "current"`).
- [x] Версии отсортированы по убыванию даты (`sortVersionsDesc` из reference-data); as-of запрос (`currencyRateAsOf`) реализован в правой колонке.
- [x] Форма «добавить версию» зовёт `addRateVersion("currency-rates", ...)` с optimistic state update; graceful degrade при недоступном бэке (сообщение об ошибке).
- [x] Вид соответствует `spravochniki-versioned-preview.html`: таймлайн с цветными барами, таблица с бейджами статуса, тёмная SQL-карточка, SCD2-пояснение.
- [x] `npx tsc --noEmit` чисто; vitest 10/10. Только файлы scope. Six-layer в теле коммита. Без push.

## Six-layer commit body
Коммит `eed06d3` содержит: WHAT / WHY / HOW / TRADEOFFS / TESTS / SCOPE.

## PITFALLS-DISCOVERED

- `title` prop на lucide-react SVG-иконках (`<Clock title="...">`) → TS2322 (prop не существует в `LucideProps`). **ЛЕЧЕНИЕ:** убрать `title`, использовать обёртку `<span title="..."><Icon /></span>` если нужен тултип.

---

STATE: COMPLETE
