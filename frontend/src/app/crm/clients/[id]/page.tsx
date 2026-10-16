import { notFound } from "next/navigation";
import { AppShell } from "@/components/app-shell";
import { CrmClientDetail } from "@/components/crm-client-detail";

export default async function ClientPage({ params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;
  const clientId = Number(id);
  if (!Number.isSafeInteger(clientId) || clientId <= 0) notFound();
  return <AppShell crumbs={["CRM", "Клиенты", "Карточка клиента"]}><CrmClientDetail key={clientId} clientId={clientId} /></AppShell>;
}
