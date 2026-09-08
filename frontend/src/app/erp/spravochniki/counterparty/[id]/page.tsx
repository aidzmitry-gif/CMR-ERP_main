import { AppShell } from "@/components/app-shell";
import { SpravCard } from "@/components/erp/spravochniki/sprav-card";
import Link from "next/link";

import { backendAuthHeaders } from "@/lib/auth-headers-server";
import { fetchCounterpartyCardResult } from "@/lib/reference-data";
import { currentRole } from "@/lib/role-server";

type SearchParam = string | string[] | undefined;

function firstParam(value: SearchParam): string {
  return Array.isArray(value) ? value[0] ?? "" : value ?? "";
}

function searchHref(name: string, unp: string): string {
  const query = new URLSearchParams();
  if (name) query.set("name", name);
  if (unp) query.set("unp", unp);
  const encoded = query.toString();
  return `/erp/spravochniki/counterparty${encoded ? `?${encoded}` : ""}`;
}

function failureText(status: Exclude<Awaited<ReturnType<typeof fetchCounterpartyCardResult>>, { status: "success" }>["status"]): string {
  switch (status) {
    case "invalid-id":
      return "Некорректный ID контрагента.";
    case "not-found":
      return "Контрагент не найден (404).";
    case "unauthorized":
      return "Сессия истекла или отсутствует авторизация (401).";
    case "forbidden":
      return "Доступ к карточке контрагента запрещён (403).";
    case "service-error":
      return "Сервис карточек контрагентов недоступен или вернул некорректные данные.";
  }
}

export default async function CounterpartyCardPage({
  params,
  searchParams,
}: {
  params: Promise<{ id: string }>;
  searchParams?: Promise<{ name?: SearchParam; unp?: SearchParam }>;
}) {
  const { id } = await params;
  const search = await searchParams;
  const name = firstParam(search?.name);
  const unp = firstParam(search?.unp);
  const role = await currentRole();
  const result = await fetchCounterpartyCardResult(Number(id), role, await backendAuthHeaders(role));
  const backHref = searchHref(name, unp);

  return (
    <AppShell crumbs={["ERP", "Справочники", "Контрагент"]}>
      {result.status === "success" ? (
        <div className="flex-1">
          <div className="mx-auto max-w-5xl px-6 pt-6">
            <Link
              href={backHref}
              className="text-sm font-medium text-accent hover:underline"
            >
              ← К поиску контрагентов
            </Link>
          </div>
          <SpravCard card={result.card} />
        </div>
      ) : (
        <div className="flex flex-1 flex-col items-center justify-center gap-4 text-muted">
          <p role="status">{failureText(result.status)}</p>
          <Link href={backHref} className="text-sm font-medium text-accent hover:underline">
            ← К поиску контрагентов
          </Link>
        </div>
      )}
    </AppShell>
  );
}
