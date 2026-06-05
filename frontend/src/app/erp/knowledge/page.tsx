import { AppShell } from "@/components/app-shell";
import { FunnelBoard } from "@/components/funnel/funnel-board";
import { FUNNEL_EXTRAS } from "@/lib/funnel-configs";

export default function KnowledgePage() {
  return (
    <AppShell crumbs={["ERP", "База знаний"]}>
      <FunnelBoard
        title="База знаний · Обучение"
        subtitle="Программа обучения: тестовая неделя → знакомство → испытательный срок → развитие."
        boardPath="/knowledge/board"
        createPath="/knowledge/courses"
        patchPath="/knowledge/courses"
        showSum={false}
        fields={[
          { key: "title", label: "Название курса" },
          { key: "description", label: "Описание" },
          { key: "duration", label: "Длительность, мин", type: "number", default: 30 },
        ]}
        boardTabs={["Все курсы", "Новые сотрудники", "Текущие сотрудники", "Обязательные"]}
        {...FUNNEL_EXTRAS.knowledge}
      />
    </AppShell>
  );
}
