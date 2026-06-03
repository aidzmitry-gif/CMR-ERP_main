"use client";

import { Flag, Star, Target } from "lucide-react";
import { useState } from "react";
import { updateDeal } from "@/lib/api";

const PRIORITY_CYCLE = ["Высокий", "Средний", "Низкий"];
const PRIORITY_TONE: Record<string, string> = {
  Высокий: "bg-red-50 text-red-600",
  Средний: "bg-amber-50 text-amber-600",
  Низкий: "bg-slate-100 text-slate-600",
};

export function DealActions({
  dealId,
  focus: initFocus,
  starred: initStarred,
  priority: initPriority,
}: {
  dealId: string;
  focus: boolean;
  starred: boolean;
  priority: string;
}) {
  const [focus, setFocus] = useState(initFocus);
  const [starred, setStarred] = useState(initStarred);
  const [priority, setPriority] = useState(initPriority);
  const [busy, setBusy] = useState(false);

  async function toggleFocus() {
    const next = !focus;
    setFocus(next);
    setBusy(true);
    await updateDeal(dealId, { focus: next });
    setBusy(false);
  }

  async function toggleStar() {
    const next = !starred;
    setStarred(next);
    setBusy(true);
    await updateDeal(dealId, { starred: next });
    setBusy(false);
  }

  async function cyclePriority() {
    const idx = PRIORITY_CYCLE.indexOf(priority);
    const next = PRIORITY_CYCLE[(idx + 1) % PRIORITY_CYCLE.length];
    setPriority(next);
    setBusy(true);
    await updateDeal(dealId, { priority: next });
    setBusy(false);
  }

  return (
    <div className="mt-4 grid grid-cols-3 gap-3">
      <button
        onClick={toggleFocus}
        disabled={busy}
        className={`flex items-center justify-center gap-2 rounded-xl py-3 font-medium disabled:opacity-60 ${
          focus ? "bg-brand text-white" : "bg-blue-50 text-brand-600"
        }`}
      >
        <Target size={18} /> Фокус
      </button>
      <button
        onClick={cyclePriority}
        disabled={busy}
        title="Сменить приоритет"
        className={`flex items-center justify-center gap-2 rounded-xl py-3 font-medium disabled:opacity-60 ${
          PRIORITY_TONE[priority] ?? "bg-amber-50 text-amber-600"
        }`}
      >
        <Flag size={18} /> {priority}
      </button>
      <button
        onClick={toggleStar}
        disabled={busy}
        className={`flex items-center justify-center gap-2 rounded-xl py-3 font-medium disabled:opacity-60 ${
          starred ? "bg-amber-400 text-white" : "bg-amber-50 text-amber-600"
        }`}
      >
        <Star size={18} className={starred ? "fill-current" : ""} />
        {starred ? "В избранном" : "В избранное"}
      </button>
    </div>
  );
}
