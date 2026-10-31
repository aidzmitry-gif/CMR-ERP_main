import { backendAuthHeaders } from "@/lib/auth-headers-server";

interface CampaignAttribution {
  id: number;
  name: string;
  channel: string;
  utm_source: string;
  utm_medium: string;
  utm_campaign: string;
  leads: number;
  budget: string;
  goal: string;
}

function isCampaign(value: unknown): value is CampaignAttribution {
  if (!value || typeof value !== "object") return false;
  const row = value as Record<string, unknown>;
  return Number.isSafeInteger(row.id) && Number(row.id) > 0
    && Number.isSafeInteger(row.leads) && Number(row.leads) >= 0
    && ["name", "channel", "utm_source", "utm_medium", "utm_campaign", "budget", "goal"]
      .every((key) => typeof row[key] === "string");
}

export async function MarketingCampaignBoard() {
  const base = process.env.BACKEND_URL ?? "http://127.0.0.1:8000";
  let items: CampaignAttribution[] = [];
  let error = "";
  try {
    const res = await fetch(`${base}/marketing/campaigns/attribution`, {
      cache: "no-store",
      headers: await backendAuthHeaders(),
    });
    if (res.status === 401 || res.status === 403) {
      error = "Нет доступа к UTM-атрибуции. Проверьте вход и права доступа.";
    } else {
      if (!res.ok) throw new Error("Campaigns unavailable");
      const data: unknown = await res.json();
      if (!Array.isArray(data) || !data.every(isCampaign)
        || new Set(data.map((row) => row.id)).size !== data.length) {
        throw new Error("Invalid campaigns response");
      }
      items = data;
    }
  } catch {
    error = "Не удалось загрузить UTM-атрибуцию. Попробуйте обновить страницу.";
  }

  return (
    <section className="mt-8">
      <h2 className="mb-3 text-lg font-semibold text-ink">
        UTM-атрибуция
      </h2>
      {error ? <p role="alert" className="rounded-xl border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-800">{error}</p> : (
      <div className="overflow-x-auto rounded-2xl border border-line bg-surface text-ink shadow-card">
        <table className="w-full text-sm">
          <thead className="bg-sunken/50 text-xs uppercase tracking-wide text-muted">
            <tr>
              <th className="px-4 py-3 text-left">Кампания</th>
              <th className="px-4 py-3 text-left">Канал</th>
              <th className="px-4 py-3 text-left">UTM source</th>
              <th className="px-4 py-3 text-left">UTM medium</th>
              <th className="px-4 py-3 text-left">UTM campaign</th>
              <th className="px-4 py-3 text-right">Бюджет BYN</th>
              <th className="px-4 py-3 text-right">Лиды</th>
              <th className="px-4 py-3 text-left">Цель</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-line">
            {items.length === 0 ? (
              <tr>
                <td
                  colSpan={8}
                  className="px-4 py-6 text-center text-muted"
                >
                  Нет кампаний
                </td>
              </tr>
            ) : (
              items.map((c) => (
                <tr
                  key={c.id}
                  className="transition-colors hover:bg-sunken/30"
                >
                  <td className="px-4 py-3 font-medium text-ink">
                    {c.name}
                  </td>
                  <td className="px-4 py-3 text-muted">{c.channel}</td>
                  <td className="px-4 py-3 font-mono text-xs text-muted">
                    {c.utm_source || "—"}
                  </td>
                  <td className="px-4 py-3 font-mono text-xs text-muted">
                    {c.utm_medium || "—"}
                  </td>
                  <td className="px-4 py-3 font-mono text-xs text-muted">
                    {c.utm_campaign || "—"}
                  </td>
                  <td className="px-4 py-3 text-right tabular-nums">{c.budget}</td>
                  <td className="px-4 py-3 text-right font-semibold tabular-nums text-accent-ink">
                    {c.leads}
                  </td>
                  <td className="px-4 py-3 text-xs text-muted">
                    {c.goal || "—"}
                  </td>
                </tr>
              ))
            )}
          </tbody>
        </table>
      </div>
      )}
    </section>
  );
}
