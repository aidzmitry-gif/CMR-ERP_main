"use client";

import { useEffect, useState } from "react";

type Notice = { id: string; title: string; href: string };

/** Visible ERP presence is informational and cannot start or stop a workday. */
export function WorktimePresence({ enabled }: { enabled: boolean }) {
  const [notices, setNotices] = useState<Notice[]>([]);
  useEffect(() => {
    if (!enabled) return;
    let stopped = false, pending = false;
    const controller = new AbortController();
    const report = async () => {
      if (stopped || pending || document.visibilityState !== "visible") return;
      pending = true;
      try {
        const heartbeat = await fetch("/api/hr/me/worktime/presence", {
          method: "POST", cache: "no-store", signal: controller.signal,
        });
        if (!heartbeat.ok) throw new Error("Access or presence unavailable");
        const response = await fetch("/api/hr/me/worktime/notices", { cache: "no-store", signal: controller.signal });
        if (!response.ok) throw new Error("Notices unavailable");
        const data = await response.json();
        if (!Array.isArray(data.items)) throw new Error("Invalid notices");
        const safe = data.items.filter((item: Notice) => typeof item.id === "string"
          && typeof item.title === "string" && typeof item.href === "string"
          && /^\/erp\/hr\/worktime(?:\?tab=sheet&period=\d{4}-\d{2})?$/.test(item.href));
        if (!stopped) setNotices(safe);
      } catch { if (!stopped) setNotices([]); }
      finally { pending = false; }
    };
    void report();
    const interval = setInterval(() => void report(), 30000);
    document.addEventListener("visibilitychange", report);
    return () => { stopped = true; controller.abort(); clearInterval(interval); document.removeEventListener("visibilitychange", report); };
  }, [enabled]);
  if (!enabled || notices.length === 0) return null;
  return <aside aria-label="Уведомления об учёте времени" className="fixed bottom-4 right-4 z-40 max-h-64 w-80 max-w-[calc(100%-2rem)] space-y-2 overflow-y-auto rounded-xl border border-line bg-surface p-4 shadow-lg">
    <div role="status">{notices.length === 1 ? "Напоминание" : `Напоминания: ${notices.length}`}</div>
    {notices.map(item => <div className="text-sm" key={item.id}><p>{item.title}</p><a href={item.href} className="text-accent underline">Открыть учёт времени</a></div>)}
  </aside>;
}
