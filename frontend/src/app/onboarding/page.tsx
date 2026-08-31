import { redirect } from "next/navigation";

import { OnboardingExit } from "@/components/onboarding-exit";
import { defaultPathForRole, ONBOARDING_ROLE } from "@/lib/app-role";
import { currentRole, currentUserName } from "@/lib/role-server";

export default async function OnboardingPage() {
  const userName = await currentUserName();
  if (!userName) redirect("/login");
  const role = await currentRole();
  if (role !== ONBOARDING_ROLE) redirect(defaultPathForRole(role));

  return (
    <main className="flex min-h-screen items-center justify-center bg-slate-50 px-4 text-ink">
      <section className="w-full max-w-xl rounded-2xl bg-white p-8 shadow-card">
        <p className="text-sm font-semibold uppercase tracking-wide text-accent-ink">AI-OS · ознакомление</p>
        <h1 className="mt-3 text-2xl font-bold">Добро пожаловать, {userName}</h1>
        <p className="mt-3 text-sm leading-6 text-muted">
          Учётная запись создана. Сейчас вам доступно только ознакомление с системой: данные
          коллег, клиентов и рабочие модули закрыты.
        </p>
        <div className="mt-5 rounded-xl border border-amber-200 bg-amber-50 p-4 text-sm text-amber-900">
          Рабочую роль и нужные разделы активирует отдельно ответственный руководитель после
          завершения адаптации.
        </div>
        <OnboardingExit />
      </section>
    </main>
  );
}
