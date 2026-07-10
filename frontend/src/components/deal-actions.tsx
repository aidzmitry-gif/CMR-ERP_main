"use client";

import { Flag, Star } from "lucide-react";
import { useState } from "react";
import { updateDeal } from "@/lib/api";

const PRIORITY_CYCLE = ["Высокий", "Средний", "Низкий"];
const PRIORITY_TONE: Record<string, string> = {
  Высокий: "bg-red-50 text-red-600",
  Средний: "bg-amber-50 text-amber-600",
  Низкий: "bg-sunken text-muted",
};

export function DealActions({
  dealId,
  starred: initStarred,
  priority: initPriority,
}: {
  dealId: string;
  starred: boolean;
  priority: string;
}) {
  const [starred, setStarred] = useState(initStarred);
  const [priority, setPriority] = useState(initPriority);
  const [busy, setBusy] = useState(false);

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
    <div className="mt-4 grid grid-cols-2 gap-3">
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
