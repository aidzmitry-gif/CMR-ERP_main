"use client";

import { useState } from "react";

import { DealPlanEditor } from "@/components/deal-plan-editor";
import { PlanConstructor } from "@/components/plan/plan-constructor";

type Tab = "build" | "approve";

/** Переключатель двух табов плана продавца: «Собрать план» (конструктор из источников,
 * П12) и «Согласование» (встречное планирование по PlanTarget, deal-plan-editor.tsx — не трогаем). */
export function PlanningTabs({ ownerId, role }: { ownerId: number; role: string }) {
  const [tab, setTab] = useState<Tab>("build");
  return (
    <div className="space-y-4">
      <div className="flex gap-1 rounded-xl bg-sunken p-1 text-sm font-semibold">
        <button
          type="button"
          onClick={() => setTab("build")}
          className={`flex-1 rounded-lg px-3 py-2 transition-colors ${
            tab === "build" ? "bg-surface text-ink shadow-card" : "text-muted hover:text-ink"
          }`}
        >
          Собрать план
        </button>
        <button
          type="button"
          onClick={() => setTab("approve")}
          className={`flex-1 rounded-lg px-3 py-2 transition-colors ${
            tab === "approve" ? "bg-surface text-ink shadow-card" : "text-muted hover:text-ink"
          }`}
        >
          Согласование
        </button>
      </div>
      {tab === "build" ? <PlanConstructor ownerId={ownerId} /> : <DealPlanEditor ownerId={ownerId} role={role} />}
    </div>
  );
}
