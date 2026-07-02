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

export async function MarketingCampaignBoard() {
  const base = process.env.BACKEND_URL ?? "http://localhost:8000";
  let items: CampaignAttribution[] = [];
  try {
    const res = await fetch(`${base}/marketing/campaigns/attribution`, {
      cache: "no-store",
    });
    if (res.ok) items = (await res.json()) as CampaignAttribution[];
  } catch {
    // backend недоступен — пустая таблица
  }

  return (
    <section className="mt-8">
      <h2 className="text-lg font-semibold mb-3 text-zinc-900 dark:text-zinc-100">
        UTM Attribution
      </h2>
      <div className="overflow-x-auto rounded-lg border border-zinc-200 dark:border-zinc-700">
        <table className="w-full text-sm">
          <thead className="bg-zinc-50 dark:bg-zinc-800 text-zinc-500 dark:text-zinc-400 uppercase text-xs tracking-wide">
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
          <tbody className="divide-y divide-zinc-100 dark:divide-zinc-800">
            {items.length === 0 ? (
              <tr>
                <td
                  colSpan={8}
                  className="px-4 py-6 text-center text-zinc-400 dark:text-zinc-500"
                >
                  Нет кампаний
                </td>
              </tr>
            ) : (
              items.map((c) => (
                <tr
                  key={c.id}
                  className="hover:bg-zinc-50 dark:hover:bg-zinc-800/50 transition-colors"
                >
                  <td className="px-4 py-3 font-medium text-zinc-900 dark:text-zinc-100">
                    {c.name}
                  </td>
                  <td className="px-4 py-3 text-zinc-600 dark:text-zinc-300">{c.channel}</td>
                  <td className="px-4 py-3 font-mono text-xs text-zinc-500">
                    {c.utm_source || "—"}
                  </td>
                  <td className="px-4 py-3 font-mono text-xs text-zinc-500">
                    {c.utm_medium || "—"}
                  </td>
                  <td className="px-4 py-3 font-mono text-xs text-zinc-500">
                    {c.utm_campaign || "—"}
                  </td>
                  <td className="px-4 py-3 text-right tabular-nums">{c.budget}</td>
                  <td className="px-4 py-3 text-right tabular-nums font-semibold text-indigo-600 dark:text-indigo-400">
                    {c.leads}
                  </td>
                  <td className="px-4 py-3 text-zinc-500 dark:text-zinc-400 text-xs">
                    {c.goal || "—"}
                  </td>
                </tr>
              ))
            )}
          </tbody>
        </table>
      </div>
    </section>
  );
}
