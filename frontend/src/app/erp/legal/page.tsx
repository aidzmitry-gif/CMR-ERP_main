import { AppShell } from "@/components/app-shell";
import { FunnelBoard } from "@/components/funnel/funnel-board";
import { FUNNEL_EXTRAS } from "@/lib/funnel-configs";

export default function LegalPage() {
  return (
    <AppShell crumbs={["ERP", "Юр. отдел"]}>
      <FunnelBoard
        title="Юр. отдел"
        subtitle="Контроль документов: договоры → претензии → исполнительная надпись → суд → взыскание."
        boardPath="/legal/board"
        createPath="/legal/cases"
        patchPath="/legal/cases"
        fields={[
          { key: "company", label: "Компания" },
          { key: "title", label: "Документ / дело" },
          { key: "amount", label: "Сумма к взысканию, ₽", type: "number", default: 0 },
        ]}
        showFocusPills
        {...FUNNEL_EXTRAS.legal}
      />
    </AppShell>
  );
}
