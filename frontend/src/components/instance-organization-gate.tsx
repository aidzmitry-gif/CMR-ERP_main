"use client";

import { useEffect, useState, type ReactNode } from "react";
import { fetchInstanceOrganization, type InstanceOrganization } from "@/lib/instance-organization";
import { Button } from "@/components/ui/button";

/** Mount scoped screens only after the server confirms the installation's company. */
export function InstanceOrganizationGate({ children }: {
  children: (organization: InstanceOrganization) => ReactNode;
}) {
  const [organization, setOrganization] = useState<InstanceOrganization | null>(null);
  const [error, setError] = useState("");
  const [attempt, setAttempt] = useState(0);
  useEffect(() => {
    let active = true;
    void fetchInstanceOrganization().then(value => { if (active) setOrganization(value); })
      .catch((reason: Error) => { if (active) setError(reason.message); });
    return () => { active = false; };
  }, [attempt]);

  if (error) return <div className="space-y-3 rounded-xl border border-line bg-surface p-4">
    <p role="alert" className="text-red-700">{error}</p>
    <a className="text-accent underline" href="/erp/settings">Настройки организации</a>
    <Button variant="secondary" onClick={() => { setOrganization(null); setError(""); setAttempt(value => value + 1); }}>Повторить загрузку юрлица</Button>
  </div>;
  if (!organization) return <p role="status">Загрузка юрлица установки…</p>;
  return <div className="min-w-0 space-y-4" key={organization.id}>
    <p className="text-sm text-muted">{organization.name} · УНП {organization.unp}</p>
    {children(organization)}
  </div>;
}
