"use client";

import { Sparkles } from "lucide-react";
import { useState } from "react";
import { aiAssist } from "@/lib/api";

export function DealAiAssistant({ dealId }: { dealId: string }) {
  const [text, setText] = useState<string | null>(null);
  const [busy, setBusy] = useState<string | null>(null);

  async function run(kind: string) {
    setBusy(kind);
    setText(null);
    const res = await aiAssist(dealId, kind);
    setBusy(null);
    setText(res ?? "AI-слой выключен (feature-flag)");
  }

  return (
    <div className="mt-4 rounded-xl border border-indigo-100 bg-indigo-50/40 p-4">
      <div className="flex items-center gap-2 font-semibold text-ink">
        <Sparkles size={18} className="text-indigo-500" /> AI-ассистент
      </div>
      <div className="mt-3 flex flex-wrap gap-2">
        <button
          onClick={() => run("summary")}
          disabled={!!busy}
          className="rounded-lg border border-indigo-200 bg-surface px-3 py-1.5 text-sm font-medium text-indigo-600 hover:bg-indigo-50 disabled:opacity-60"
        >
          {busy === "summary" ? "Анализ…" : "Резюме сделки"}
        </button>
        <button
          onClick={() => run("next_step")}
          disabled={!!busy}
          className="rounded-lg border border-indigo-200 bg-surface px-3 py-1.5 text-sm font-medium text-indigo-600 hover:bg-indigo-50 disabled:opacity-60"
        >
          {busy === "next_step" ? "Анализ…" : "Следующий шаг"}
        </button>
      </div>
      {text && <p className="mt-3 rounded-lg bg-surface p-3 text-sm text-muted">{text}</p>}
    </div>
  );
}
