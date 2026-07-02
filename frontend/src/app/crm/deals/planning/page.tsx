import Link from "next/link";
import { ArrowLeft } from "lucide-react";
import { AppShell } from "@/components/app-shell";
import { DealPlanEditor } from "@/components/deal-plan-editor";
import { currentRole } from "@/lib/role-server";

/**
 * Экран встречного планирования (П9 ТЗ).
 *
 * Без HR-связки на фронте берём `?owner_id=` из URL (для dev/демо). Когда появится
 * персональный логин с employee_id — заменим на сервер-резолв. ponytail: пока owner_id
 * передаётся параметром, чтобы не блокировать поток встречного планирования.
 */
export default async function DealsPlanningPage({
  searchParams,
}: {
  searchParams: Promise<{ owner_id?: string }>;
}) {
  const { owner_id } = await searchParams;
  const role = await currentRole();
  const ownerId = Number.parseInt(owner_id ?? "1", 10) || 1;
  return (
    <AppShell crumbs={["CRM", "Сделки", "План"]}>
      <main className="flex-1 overflow-y-auto bg-canvas text-ink">
        <div className="mx-auto max-w-[1100px] px-[22px] pb-10 pt-[18px]">
          <Link
            href="/crm/deals"
            className="mb-3 inline-flex items-center gap-1 text-[12.5px] font-semibold text-muted hover:text-ink"
          >
            <ArrowLeft size={14} /> К доске
          </Link>
          <h1 className="mb-1 text-[19px] font-extrabold text-ink">План продавца — встречное согласование</h1>
          <p className="mb-4 text-[12.5px] text-muted">
            Заполните цели → отправьте РОПу на согласование. Деньги — бел. руб. (BYN).
          </p>
          <DealPlanEditor ownerId={ownerId} role={role} />
        </div>
      </main>
    </AppShell>
  );
}
