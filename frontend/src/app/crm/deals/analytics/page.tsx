import Link from "next/link";
import { ArrowLeft } from "lucide-react";
import { AppShell } from "@/components/app-shell";
import { PipelineAnalytics } from "@/components/pipeline-analytics";

/** Аналитика воронки сделок (П7 ТЗ) — воронкообразная визуализация + плитки. */
export default async function DealsAnalyticsPage({
  searchParams,
}: {
  searchParams: Promise<{ funnel?: string }>;
}) {
  const { funnel } = await searchParams;
  return (
    <AppShell crumbs={["CRM", "Сделки", "Аналитика"]}>
      <main className="flex-1 overflow-y-auto bg-canvas text-ink">
        {/* pr увеличен против стандартных 22px: плавающая рейка чатов/уведомлений (AppShell,
            absolute right-0, не резервирует место в layout) перекрывает крайние ~68px контента
            на узких viewport — двухколоночный график конверсии/времени тянется до края шире,
            чем доска (та не задевает рейку из-за horizontal-scroll колонок канбана). */}
        <div className="mx-auto max-w-[1200px] pb-10 pl-[22px] pr-24 pt-[18px]">
          <Link
            href="/crm/deals"
            className="mb-3 inline-flex items-center gap-1 text-[12.5px] font-semibold text-muted hover:text-ink"
          >
            <ArrowLeft size={14} /> К доске
          </Link>
          <h1 className="mb-1 text-[19px] font-extrabold text-ink">Аналитика воронки</h1>
          <p className="mb-4 text-[12.5px] text-muted">
            Стадии, конверсия, взвешенный прогноз и средний цикл успехов. Деньги — бел. руб. (BYN).
          </p>
          <PipelineAnalytics initialFunnel={funnel ?? "new_clients"} />
        </div>
      </main>
    </AppShell>
  );
}
