"use client";

import { useEffect, useRef, useState } from "react";
import {
  PICKER_COLUMNS, PICKER_COLUMNS_KEY, pickerColumnDefaults, readPickerColumns,
  movePickerColumn, orderedPickerColumns,
  type PickerColumnId, type PickerColumnSettings,
} from "@/lib/catalog-picker-table";

export function usePickerColumns() {
  const [columns, setColumns] = useState(() => {
    try { return readPickerColumns(localStorage.getItem(PICKER_COLUMNS_KEY)); } catch { return pickerColumnDefaults(); }
  });
  const dragCleanup = useRef<(() => void) | null>(null);
  useEffect(() => {
    return () => dragCleanup.current?.();
  }, []);

  function update(next: PickerColumnSettings) {
    setColumns(next);
    try { localStorage.setItem(PICKER_COLUMNS_KEY, JSON.stringify(next)); } catch { /* Layout remains usable. */ }
  }
  function resize(id: PickerColumnId, width: number) {
    update(readPickerColumns(JSON.stringify({ ...columns, [id]: { ...columns[id], width } })));
  }
  function startResize(id: PickerColumnId, event: React.PointerEvent) {
    event.preventDefault();
    dragCleanup.current?.();
    const x = event.clientX, width = columns[id].width;
    const move = (e: PointerEvent) => resize(id, width + e.clientX - x);
    const stop = () => {
      window.removeEventListener("pointermove", move);
      window.removeEventListener("pointerup", stop);
      window.removeEventListener("pointercancel", stop);
      dragCleanup.current = null;
    };
    dragCleanup.current = stop;
    window.addEventListener("pointermove", move);
    window.addEventListener("pointerup", stop);
    window.addEventListener("pointercancel", stop);
  }
  return { columns, update, resize, startResize };
}

export function PickerColumnsControl({ columns, update, resize }: ReturnType<typeof usePickerColumns>) {
  return <details className="relative text-[12px]">
    <summary className="cursor-pointer rounded-lg border border-line px-2.5 py-1.5 font-semibold text-ink">Столбцы</summary>
    <div className="absolute right-0 top-full z-20 mt-1 max-h-[60vh] w-80 max-w-[85vw] overflow-y-auto rounded-xl border border-line bg-surface p-3 shadow-pop">
      <p className="mb-2 text-[11px] text-muted">Стрелки меняют порядок столбцов. Ширину можно задать здесь или перетянуть границу заголовка. Настройки сохраняются в этом браузере.</p>
      {orderedPickerColumns(columns).map((c, index) => <div key={c.id} className="mb-3 space-y-1">
        <div className="flex items-center gap-2">
        <label className="flex min-w-0 flex-1 items-center gap-2">
          <input type="checkbox" checked={columns[c.id].visible} disabled={c.required}
            onChange={(e) => update({ ...columns, [c.id]: { ...columns[c.id], visible: e.target.checked } })} />
          {c.label}
        </label>
          <button type="button" aria-label={`Выше: ${c.label}`} disabled={index === 0}
            className="h-6 w-7 rounded border border-line disabled:opacity-30" onClick={() => update(movePickerColumn(columns, c.id, -1))}>↑</button>
          <button type="button" aria-label={`Ниже: ${c.label}`} disabled={index === PICKER_COLUMNS.length - 1}
            className="h-6 w-7 rounded border border-line disabled:opacity-30" onClick={() => update(movePickerColumn(columns, c.id, 1))}>↓</button>
        </div>
        <div className="flex items-center gap-2">
          <input type="range" min={c.min} max={c.max} value={columns[c.id].width}
            aria-label={`Ширина: ${c.label}`} className="min-w-0 flex-1"
            onChange={(e) => resize(c.id, Number(e.target.value))} />
          <input key={`${c.id}-${columns[c.id].width}`} type="number" min={c.min} max={c.max} defaultValue={columns[c.id].width}
            aria-label={`Ширина в пикселях: ${c.label}`} className="w-16 rounded border border-line bg-surface px-1 py-0.5 text-right tabular-nums"
            title="Введите ширину и нажмите Enter или перейдите к другому полю"
            onBlur={(e) => resize(c.id, e.target.valueAsNumber)}
            onKeyDown={(e) => { if (e.key === "Enter") e.currentTarget.blur(); }} />
          <span className="text-muted">px</span>
        </div>
      </div>)}
      <button type="button" className="text-accent-ink underline" onClick={() => update(pickerColumnDefaults())}>Сбросить столбцы</button>
    </div>
  </details>;
}
