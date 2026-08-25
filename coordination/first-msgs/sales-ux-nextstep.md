# Воркер: sales-ux-nextstep — Следующий шаг datetime + Gate 1 подбор

## Цель (Goal-Driven)
Два UX-хвоста Sales-2.0:
1. **Следующий шаг** — заменить `<input type="text">` на `<input type="datetime-local">` во всех местах, где поле редактируется, с форматированием в отображении (дата + время).
2. **Gate 1 подбор** — экран-мокап каталог-пикера, встроенный в deal flow при переходе на стадию Gate 1.

Критерий готовности: `tsc --noEmit` = OK, `npm run test:run` (vitest) = 0 failed по затронутым тестам. Никаких бэкенд-миграций — работаем в рамках существующего строкового поля `next_step: string | null`. Если считаешь, что нужно менять тип колонки в БД — **флаги в `coordination/sales-ux-nextstep-status.md`** с формулировкой риска, не мигрируй сам.

## Контекст
- **CWD:** `D:\6 Проекты\CRM ERP\Сlaude CRM - проект`
- **Репо:** суперпроект (НЕ submodule). Весь фронт — в суперпроекте `frontend/src/`. Коммит только в суперпроект, submodule не трогать, gitlink не обновлять.
- **Рабочая ветка:** текущая (`sales-2.0-redesign`).
- **Нет миграций** — `next_step` остаётся `String(128)` в backend. Формат `datetime-local` (ISO `"YYYY-MM-DDTHH:mm"`) хранится как строка — это допустимо на текущем этапе.
- **Auth (не нужен для фронта):** для vitest тесты гоняются без backend.

## Ключевые файлы (прочитай перед правкой)

| Файл | Что там |
|------|---------|
| `frontend/src/components/deal-edit-button.tsx` | Основной редактор сделки, `next_step` как `<input type="text">` на строке ~119 |
| `frontend/src/components/kanban/deal-drawer-preview.tsx` | Инлайн-редактор `next_step` через `<textarea>` на строке ~254-307 |
| `frontend/src/app/crm/deals/[id]/page.tsx` | Отображение `nextStep` (display-only) на строке ~276-278 |
| `frontend/src/components/funnel/funnel-board.tsx` | Отображение `card.next_step` на строке ~673-678 |
| `frontend/src/components/calls/call-window.tsx` | Редактор `next_step` в окне звонка, строка ~970-981 |
| `frontend/src/lib/types.ts` | TypeScript-тип: `nextStep?: string` (Brief) / `nextStep: string` (Full) |
| `frontend/src/lib/api.ts` | Маппинг `next_step` → `nextStep` (строка ~65) |
| `frontend/src/components/catalog/catalog-picker.tsx` | Готовый каталог-пикер компонент (демо-данные, AI-поиск, склады) |
| `frontend/src/lib/funnel-configs.ts` | Конфиги воронок, стадии (Gate 1 и т.п.) |

## Шаг 1 — datetime-local во всех редакторах

### 1а — deal-edit-button.tsx (строка ~119)
Заменить:
```tsx
<input
  value={form.next_step}
  onChange={(e) => setForm({ ...form, next_step: e.target.value })}
  className={INPUT}
/>
```
На:
```tsx
<input
  type="datetime-local"
  value={form.next_step ?? ""}
  onChange={(e) => setForm({ ...form, next_step: e.target.value || null })}
  className={INPUT}
/>
```
Форма уже хранит `next_step` как `string | null` — тип не меняется. Значение ISO `"YYYY-MM-DDTHH:mm"` совместимо с `String(128)` на бэкенде.

### 1б — deal-drawer-preview.tsx (строка ~254-307)
Заменить `<textarea>` для `next_step` на `<input type="datetime-local">`. Сохранить весь остальной инлайн-UX (Ctrl+Enter если был, иконки, кнопки) — **не выкидывать существующие блоки**.

### 1в — call-window.tsx (строка ~970-981)
Заменить `<input type="text">` на `<input type="datetime-local">` аналогично 1а.

### 1г — Форматирование при отображении (display-only)
В `funnel-board.tsx` (~673-678) и `deals/[id]/page.tsx` (~276-278) `next_step` отображается как строка. Добавить хелпер форматирования в `frontend/src/lib/format.ts`:
```ts
/** Форматирует datetime-local строку ("YYYY-MM-DDTHH:mm") → "15 июл 14:30" или возвращает как есть */
export function formatNextStep(raw: string | null | undefined): string {
  if (!raw) return "—";
  const d = new Date(raw);
  if (isNaN(d.getTime())) return raw; // не ISO — показать как есть (обратная совместимость)
  return d.toLocaleString("ru-RU", { day: "numeric", month: "short", hour: "2-digit", minute: "2-digit" });
}
```
Подставить `formatNextStep(card.next_step)` вместо `card.next_step` в display-only местах.

## Шаг 2 — Gate 1 подбор: экран-мокап

### Что такое Gate 1
Gate 1 — это первая ключевая стадия воронки (переход из «Квалификация» в «Коммерческое предложение»). При переходе через Gate 1 продавец должен подобрать товарные позиции.

### 2а — Компонент gate1-picker-modal.tsx
Создать `frontend/src/components/funnel/gate1-picker-modal.tsx`.

Это **модальное окно-мокап** (честно промаркировать как мокап: `/* mockup — реальный API подбора в разработке */`). Основа — переиспользовать существующий `catalog-picker.tsx` (он уже готов с демо-данными, AI-поиском, складами).

```tsx
// frontend/src/components/funnel/gate1-picker-modal.tsx
"use client";
/* mockup — реальный API подбора в разработке */
import { X } from "lucide-react";
import CatalogPicker from "@/components/catalog/catalog-picker";

interface Gate1PickerModalProps {
  dealId: number;
  dealTitle: string;
  onClose: () => void;
  onConfirm: (items: unknown[]) => void;
}

export default function Gate1PickerModal({ dealTitle, onClose, onConfirm }: Gate1PickerModalProps) {
  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40">
      <div className="relative w-full max-w-4xl rounded-xl bg-surface shadow-2xl">
        <div className="flex items-center justify-between border-b border-line px-6 py-4">
          <div>
            <span className="text-xs font-medium uppercase tracking-wider text-muted">Gate 1 — подбор позиций</span>
            <h2 className="mt-0.5 text-base font-semibold text-ink">{dealTitle}</h2>
          </div>
          <button onClick={onClose} className="rounded p-1 hover:bg-sunken"><X size={18} /></button>
        </div>
        {/* Переиспользуем готовый каталог-пикер */}
        <div className="max-h-[70vh] overflow-y-auto p-4">
          <CatalogPicker />
        </div>
        <div className="flex items-center justify-end gap-3 border-t border-line px-6 py-4">
          <button onClick={onClose} className="rounded-lg px-4 py-2 text-sm text-muted hover:bg-sunken">Отмена</button>
          <button
            onClick={() => { onConfirm([]); onClose(); }}
            className="rounded-lg bg-accent px-4 py-2 text-sm font-medium text-white hover:bg-accent/90"
          >
            Добавить в сделку
          </button>
        </div>
      </div>
    </div>
  );
}
```

### 2б — Подключить в funnel-board.tsx
Найди в `funnel-board.tsx` обработчик перемещения карточки между стадиями (onDragEnd / handleDrop / moveCard). При перемещении в стадию с именем, содержащим "Gate 1" (или его конфиг-ключ из `funnel-configs.ts`), открывать `Gate1PickerModal`. Используй локальный state `gate1DealId: number | null`.

Пример интеграции (добавить к существующему обработчику, не заменять его):
```tsx
// в handleDrop / onDragEnd, ПОСЛЕ фактического перемещения:
if (targetStage.name.includes("Gate 1") || targetStage.gate === 1) {
  setGate1DealId(card.id);
}
```
Рендер модала в JSX воронки (рядом с другими модалами):
```tsx
{gate1DealId && (
  <Gate1PickerModal
    dealId={gate1DealId}
    dealTitle={cards.find(c => c.id === gate1DealId)?.title ?? ""}
    onClose={() => setGate1DealId(null)}
    onConfirm={() => setGate1DealId(null)}
  />
)}
```

**Если в funnel-board.tsx нет понятия Gate 1** (стадия называется иначе) — найди реальное название первой ключевой gate-стадии в `funnel-configs.ts` и используй его. Не выдумывай имена.

## Шаг 3 — Обновить тесты

В `frontend/src/lib/format.test.ts` (или рядом с `format.ts`) добавить тесты:
```ts
import { describe, it, expect } from "vitest";
import { formatNextStep } from "./format";

describe("formatNextStep", () => {
  it("returns — for null", () => expect(formatNextStep(null)).toBe("—"));
  it("formats ISO datetime", () => {
    const result = formatNextStep("2026-07-15T14:30");
    expect(result).toContain("14:30");
  });
  it("passes through non-ISO string unchanged", () => {
    expect(formatNextStep("Позвонить завтра")).toBe("Позвонить завтра");
  });
});
```

Если `deal-edit-button.test.tsx` проверяет рендер поля `next_step` — обновить ожидаемый `type="datetime-local"`.

## Запуск
```powershell
# Из D:\6 Проекты\CRM ERP\Сlaude CRM - проект\frontend
npm run test:run          # vitest однократно — 0 failed
npx tsc --noEmit          # typecheck
```

## DoD
- `tsc --noEmit` — 0 ошибок
- `npm run test:run` — 0 failed по затронутым файлам
- Все существующие блоки карточки/формы на месте — ничего не выброшено
- Gate 1 модал открывается при перемещении карточки на Gate-стадию
- `formatNextStep` обрабатывает ISO строку и backward-compat (старый текст)
- Если нужна DB-миграция (смена типа колонки) — только флаг в `coordination/sales-ux-nextstep-status.md`, не мигрировать
- Записать `STATE: COMPLETE` в `coordination/sales-ux-nextstep-status.md`
- **НЕ пушить** (пуш делает координатор)
- **НЕ коммитить в submodule** — это чисто суперпроект
