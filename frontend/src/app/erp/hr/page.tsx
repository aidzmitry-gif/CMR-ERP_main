import { AppShell } from "@/components/app-shell";
import Link from "next/link";
import { FunnelBoard } from "@/components/funnel/funnel-board";
import { FUNNEL_EXTRAS } from "@/lib/funnel-configs";

export default function HrPage() {
  return (
    <AppShell crumbs={["ERP", "HR · Подбор"]} headerActions={<Link href="/erp/hr/employees" className="rounded-xl border border-line px-4 py-2 text-sm">Карточки сотрудников</Link>}>
      <FunnelBoard
        title="HR · Подбор персонала"
        subtitle="Воронка подбора: от новой вакансии до найма."
        boardPath="/hr/board"
        createPath="/hr/candidates"
        patchPath="/hr/candidates"
        showSum={false}
        fields={[
          { key: "name", label: "Кандидат" },
          { key: "position", label: "Должность" },
          { key: "salary", label: "Зарплата, ₽", type: "number", default: 0 },
        ]}
        showChannels
        showFocusPills
        {...FUNNEL_EXTRAS.hr}
      />
    </AppShell>
  );
}
