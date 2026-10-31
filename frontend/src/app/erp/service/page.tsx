import { AppShell } from "@/components/app-shell";
import { ModuleBoard } from "@/components/erp/module-board";
import Link from "next/link";

export default function ServicePage() {
  return (
    <AppShell crumbs={["ERP", "Сервис и поддержка"]}>
      <div className="flex min-w-0 flex-1 flex-col">
        <nav aria-label="Разделы сервиса" className="px-6 pt-6">
          <Link href="/erp/service/requests" prefetch={false} className="inline-flex rounded-lg border border-line bg-surface px-4 py-2 text-sm font-medium text-accent hover:bg-sunken">
            Заявки на обслуживание
          </Link>
          <p className="mt-1 text-sm text-muted">Статусы работ, приоритеты и связанные сделки.</p>
        </nav>
        <ModuleBoard
          title="Обращения клиентов"
          subtitle="Входящие вопросы в службу поддержки"
          endpoint="/service/tickets"
          columns={[
            { key: "customer", label: "Клиент" },
            { key: "subject", label: "Тема" },
            { key: "status", label: "Статус" },
          ]}
          fields={[
            { key: "customer", label: "Клиент" },
            { key: "subject", label: "Тема" },
          ]}
        />
      </div>
    </AppShell>
  );
}
