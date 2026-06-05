import { AppShell } from "@/components/app-shell";
import { FunnelBoard } from "@/components/funnel/funnel-board";
import { FUNNEL_EXTRAS } from "@/lib/funnel-configs";

export default function HrPage() {
  return (
    <AppShell crumbs={["ERP", "HR · Подбор"]}>
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
