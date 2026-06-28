import Link from "next/link";
import { ArrowLeft } from "lucide-react";
import { AppShell } from "@/components/app-shell";
import { DealStageEditor } from "@/components/deal-stage-editor";

/** Редактор стадий воронки (CRUD sales.stage) — Сделки 2.0. */
export default function DealStagesPage() {
  return (
    <AppShell crumbs={["CRM", "Сделки", "Стадии"]}>
      <main className="flex-1 overflow-y-auto bg-canvas text-ink">
        <div className="mx-auto max-w-[1100px] px-[22px] pb-10 pt-[18px]">
          <Link
            href="/crm/deals"
            className="mb-3 inline-flex items-center gap-1 text-[12.5px] font-semibold text-muted hover:text-ink"
          >
            <ArrowLeft size={14} /> К доске
          </Link>
          <h1 className="mb-1 text-[19px] font-extrabold text-ink">Редактор стадий воронки</h1>
          <p className="mb-4 text-[12.5px] text-muted">
            Имя, порядок колонок, вероятность, тип и цвет стадий. Изменения сразу применяются к доске.
          </p>
          <DealStageEditor />
        </div>
      </main>
    </AppShell>
  );
}
