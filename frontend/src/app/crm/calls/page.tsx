import { AppShell } from "@/components/app-shell";
import { CallsWorkspace } from "@/components/calls/calls-workspace";

export default async function CallsPage({ searchParams }: {
  searchParams?: Promise<{ counterparty_id?: string | string[]; call_id?: string | string[] }>;
}) {
  const search = await searchParams;
  const parseId = (raw: string | string[] | undefined): number | undefined => {
    const value = Array.isArray(raw) ? raw[0] : raw;
    if (!value || !/^\d+$/.test(value)) return undefined;
    const id = Number(value);
    return Number.isSafeInteger(id) && id > 0 ? id : undefined;
  };
  return (
    <AppShell crumbs={["CRM", "Звонки"]}>
      <CallsWorkspace initialCounterpartyId={parseId(search?.counterparty_id)} initialCallId={parseId(search?.call_id)} />
    </AppShell>
  );
}
