"use client";

import { Sparkles } from "lucide-react";
import { useState } from "react";
import { fetchOwnerInsight } from "@/lib/api";

export function OwnerAiInsight() {
  const [text, setText] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  async function run() {
    setBusy(true);
    const res = await fetchOwnerInsight();
    setBusy(false);
    setText(res ?? "AI-слой выключен (feature-flag)");
  }

  return (
    <div className="mt-4 rounded-2xl border border-indigo-100 bg-indigo-50/40 p-5">
      <div className="flex items-center justify-between">
        <h2 className="flex items-center gap-2 font-semibold text-ink">
          <Sparkles size={18} className="text-indigo-500" /> AI-инсайт
        </h2>
        <button
          onClick={run}
          disabled={busy}
          className="rounded-lg border border-indigo-200 bg-surface px-3 py-1.5 text-sm font-medium text-indigo-600 hover:bg-indigo-50 disabled:opacity-60"
        >
          {busy ? "Анализ…" : "Сгенерировать"}
        </button>
      </div>
      {text && <p className="mt-3 rounded-lg bg-surface p-3 text-sm text-muted">{text}</p>}
    </div>
  );
}
