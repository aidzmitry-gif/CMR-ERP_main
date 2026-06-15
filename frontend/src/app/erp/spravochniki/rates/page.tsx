import { AppShell } from "@/components/app-shell";
import { SpravRates } from "@/components/erp/spravochniki/sprav-rates";
import { fetchCurrencyRates, fetchVatRates } from "@/lib/reference-data";
import { currentRole } from "@/lib/role-server";

export default async function SpravRatesPage() {
  const role = await currentRole();
  const [currencyRates, vatRates] = await Promise.all([
    fetchCurrencyRates(undefined, role),
    fetchVatRates(undefined, role),
  ]);
  return (
    <AppShell crumbs={["ERP", "Справочники", "Курсы и ставки"]}>
      <SpravRates initialCurrencyRates={currencyRates} initialVatRates={vatRates} />
    </AppShell>
  );
}
