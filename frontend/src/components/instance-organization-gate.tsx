"use client";

import { Button } from "@/components/ui/button";
import { INSTALLATION_CHANGED,INSTALLATION_STORAGE_KEY } from "@/lib/installation-events";
import { fetchInstanceOrganization,type InstanceOrganization } from "@/lib/instance-organization";
import { createContext,useContext,useEffect,useLayoutEffect,useState,type ComponentType,type ReactNode } from "react";

const InstanceContext = createContext<InstanceOrganization | null>(null);

export function useInstanceOrganization() {
  const organization = useContext(InstanceContext);
  if (!organization) throw new Error("Юрлицо установки не подтверждено.");
  return organization;
}

export function withInstanceOrganization<P extends object>(Component: ComponentType<P>) {
  function ScopedComponent(props: P) {
    return <InstanceOrganizationGate>{() => <Component {...props} />}</InstanceOrganizationGate>;
  }
  return ScopedComponent;
}

/** Mount scoped screens only after the server confirms the installation's company. */
export function InstanceOrganizationGate({ children }: { children: (organization: InstanceOrganization) => ReactNode }) {
  const inherited = useContext(InstanceContext);
  return inherited ? children(inherited) : <LoadInstanceOrganization>{children}</LoadInstanceOrganization>;
}

function LoadInstanceOrganization({ children }: { children: (organization: InstanceOrganization) => ReactNode }) {
  const [organization, setOrganization] = useState<InstanceOrganization | null>(null);
  const [error, setError] = useState("");
  const [attempt, setAttempt] = useState(0);
  const [invalidated, setInvalidated] = useState(false);
  useEffect(() => {
    let active = true;
    void fetchInstanceOrganization().then(value => { if (active) setOrganization(value); })
      .catch((reason: Error) => { if (active) setError(reason.message); });
    return () => { active = false; };
  }, [attempt]);

  // Subscribe before paint and before mounted forms can emit a change from their effects.
  useLayoutEffect(() => {
    if (!organization) return;
    let active = true;
    const original = `${organization.id}:${organization.unp}:${organization.revision ?? 0}`;
    async function check() {
      try {
        const current = await fetchInstanceOrganization();
        if (active && `${current.id}:${current.unp}:${current.revision ?? 0}` !== original) setInvalidated(true);
      } catch { if (active) setInvalidated(true); }
    }
    const onStorage = (event: StorageEvent) => { if (event.key === INSTALLATION_STORAGE_KEY) void check(); };
    window.addEventListener("focus", check);
    window.addEventListener(INSTALLATION_CHANGED, check);
    window.addEventListener("storage", onStorage);
    return () => {
      active = false;
      window.removeEventListener("focus", check);
      window.removeEventListener(INSTALLATION_CHANGED, check);
      window.removeEventListener("storage", onStorage);
    };
  }, [organization]);

  if (error) return <div className="space-y-3 rounded-xl border border-line bg-surface p-4">
    <p role="alert" className="text-red-700">{error}</p>
    <a className="text-accent underline" href="/erp/settings">Настройки организации</a>
    <Button variant="secondary" onClick={() => { setOrganization(null); setError(""); setAttempt(value => value + 1); }}>Повторить загрузку юрлица</Button>
  </div>;
  if (!organization) return <p role="status">Загрузка юрлица установки…</p>;
  return <InstanceContext.Provider value={organization}><div className="min-w-0 space-y-4" key={organization.id}>
    <p className="text-sm text-muted">{organization.name} · УНП {organization.unp}</p>
    {invalidated && <div className="space-y-3 rounded-xl border border-amber-400 bg-surface p-4">
      <p role="alert">Настройка юрлица или доступ изменились. Открытая форма заблокирована до обновления страницы. Её данные не переносятся в другую организацию.</p>
      <Button variant="secondary" onClick={() => window.location.reload()}>Обновить страницу</Button>
    </div>}
    <div inert={invalidated} aria-disabled={invalidated || undefined}>{children(organization)}</div>
  </div></InstanceContext.Provider>;
}
