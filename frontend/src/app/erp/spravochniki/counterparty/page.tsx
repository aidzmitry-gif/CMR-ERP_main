import { AppShell } from "@/components/app-shell";
import { SpravCounterparties } from "@/components/erp/spravochniki/sprav-counterparties";

type SearchParam = string | string[] | undefined;

function firstParam(value: SearchParam): string {
  return Array.isArray(value) ? value[0] ?? "" : value ?? "";
}

export default async function CounterpartySearchPage({
  searchParams,
}: {
  searchParams?: Promise<{ name?: SearchParam; unp?: SearchParam }>;
}) {
  const params = await searchParams;

  return (
    <AppShell crumbs={["ERP", "Справочники", "Контрагенты"]}>
      <SpravCounterparties
        initialName={firstParam(params?.name)}
        initialUnp={firstParam(params?.unp)}
      />
    </AppShell>
  );
}
