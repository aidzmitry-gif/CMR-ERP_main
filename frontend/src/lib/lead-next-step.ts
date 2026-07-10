// Пресеты «следующего шага продавцу» (Цикл 2 — экспресс-передача лида): чипы вместо
// ручного ввода даты/времени — один клик заполняет next_step_at/next_step_note.
// Общие для карточки канбана (экспресс-поповер) и drawer-preview (ручная раздача).

export interface NextStepPreset {
  key: string;
  label: string;
  /** ISO-подобная строка под <input type="datetime-local">, или "" — без шага. */
  at: () => string;
  note: string;
}

function pad(n: number): string {
  return String(n).padStart(2, "0");
}

// Локальное время в формате <input type="datetime-local"> (без секунд/зоны).
function localDatetimeInput(d: Date): string {
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}T${pad(d.getHours())}:${pad(d.getMinutes())}`;
}

function today(hours: number): string {
  const d = new Date();
  d.setHours(hours, 0, 0, 0);
  return localDatetimeInput(d);
}

function tomorrow(hours: number): string {
  const d = new Date();
  d.setDate(d.getDate() + 1);
  d.setHours(hours, 0, 0, 0);
  return localDatetimeInput(d);
}

export const NEXT_STEP_PRESETS: NextStepPreset[] = [
  { key: "today16", label: "Позвонить сегодня 16:00", at: () => today(16), note: "Позвонить" },
  { key: "tomorrow10", label: "Позвонить завтра 10:00", at: () => tomorrow(10), note: "Позвонить" },
  { key: "kp", label: "КП до завтра", at: () => tomorrow(18), note: "Подготовить и отправить КП" },
  { key: "none", label: "Без шага", at: () => "", note: "" },
];

// Пресет по умолчанию в экспресс-поповере — «Позвонить завтра 10:00» (2 клика: ⚡ → Передать).
export const DEFAULT_NEXT_STEP_PRESET_KEY = "tomorrow10";
