/** Shared labels and appearance for call history and linked customer records. */
export const CALL_STATUS: Record<string, { label: string; cls: string }> = {
  ringing: { label: "Звонит", cls: "bg-emerald-50 text-emerald-600" },
  answered: { label: "Разговор", cls: "bg-blue-50 text-blue-600" },
  ended: { label: "Завершён", cls: "bg-sunken text-muted" },
  missed: { label: "Пропущен", cls: "bg-red-50 text-red-600" },
  busy: { label: "Занято", cls: "bg-amber-50 text-amber-600" },
  failed: { label: "Сбой", cls: "bg-red-50 text-red-600" },
};
