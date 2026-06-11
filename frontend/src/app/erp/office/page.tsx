import { AppShell } from "@/components/app-shell";
import { OfficeView } from "@/components/erp/office-view";
import { FunnelBoard } from "@/components/funnel/funnel-board";
import { FUNNEL_EXTRAS } from "@/lib/funnel-configs";

export default function OfficePage() {
  return (
    <AppShell crumbs={["ERP", "Офис-менеджер"]}>
      <OfficeView
        board={
          <FunnelBoard
            title="Офис-менеджер"
            subtitle="Документы по сделкам: готово к отгрузке → отгружено → документы → оплата."
            boardPath="/office/board"
            createPath="/office/docs"
            patchPath="/office/docs"
            fields={[
              { key: "company", label: "Компания" },
              { key: "title", label: "Описание" },
              { key: "amount", label: "Сумма, BYN", type: "number", default: 0 },
            ]}
            showChannels
            showFocusPills
            {...FUNNEL_EXTRAS.office}
          />
        }
      />
    </AppShell>
  );
}
