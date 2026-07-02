import { AppShell } from "@/components/app-shell";
import { KnowledgeEnrollmentsView } from "@/components/erp/knowledge-enrollments-view";

export default function KnowledgeEnrollmentsPage() {
  return (
    <AppShell crumbs={["ERP", "База знаний", "Учёт курсов"]}>
      <KnowledgeEnrollmentsView />
    </AppShell>
  );
}
