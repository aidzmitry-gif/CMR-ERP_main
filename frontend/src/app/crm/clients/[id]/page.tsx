import { notFound } from "next/navigation";
import { AppShell } from "@/components/app-shell";
import { CrmClientDetail } from "@/components/crm-client-detail";

export default async function ClientPage({ params, searchParams }: {
  params: Promise<{ id: string }>;
  searchParams?: Promise<{ contact?: string | string[] }>;
}) {
  const { id } = await params;
  const search = await searchParams;
  const clientId = Number(id);
  if (!Number.isSafeInteger(clientId) || clientId <= 0) notFound();
  const rawContactId = Array.isArray(search?.contact) ? search.contact[0] : search?.contact;
  const parsedContactId = rawContactId && /^\d+$/.test(rawContactId) ? Number(rawContactId) : undefined;
  const focusContactId = parsedContactId !== undefined && Number.isSafeInteger(parsedContactId) && parsedContactId > 0
    ? parsedContactId : undefined;
  return <AppShell crumbs={["CRM", "Клиенты", "Карточка клиента"]}><CrmClientDetail key={clientId} clientId={clientId} focusContactId={focusContactId} /></AppShell>;
}
