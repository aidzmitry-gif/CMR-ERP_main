import { AppShell } from "@/components/app-shell";
import { FunnelBoard } from "@/components/funnel/funnel-board";
import { FUNNEL_EXTRAS } from "@/lib/funnel-configs";

export default function ProductionPage() {
  return (
    <AppShell crumbs={["ERP", "Производство"]}>
      <FunnelBoard
        title="Производство"
        subtitle="Канбан цеха: от очереди до готовности. «Готово → склад» создаёт приход на склад."
        boardPath="/production/board"
        createPath="/production/orders"
        patchPath="/production/orders"
        showSum={false}
        fields={[
          { key: "product", label: "Изделие" },
          { key: "qty", label: "Кол-во", type: "number", default: 1 },
        ]}
        detailExtras={{
          operations: [
            { name: "Раскрой", plan: "04.06", fact: "04.06", status: "ok" },
            { name: "Сварка шин", plan: "05.06", fact: "05.06", status: "ok" },
            { name: "Монтаж BMS", plan: "06.06", fact: "—", status: "bad" },
            { name: "Тест", plan: "06.06", fact: "—", status: "warn" },
          ],
          risk: {
            percent: 64,
            notes: ["Дефицит BMS 16S — 36 шт", "Поступление BMS — 04.06", "Перегрузка участка теста (118%)"],
          },
          bom: [
            { name: "LiFePO4 3.2V 100Ah", need: 1920, stock: 1920 },
            { name: "BMS 16S 48V", need: 120, stock: 84 },
            { name: "Корпус АКБ", need: 120, stock: 120 },
            { name: "Шины медные", need: 480, stock: 460 },
          ],
          equipment: [
            { name: "Сборочный пост A", load: 88 },
            { name: "Обжимной пресс", load: 72 },
            { name: "Тест-стенд", load: 46 },
          ],
        }}
        {...FUNNEL_EXTRAS.production}
      />
    </AppShell>
  );
}
