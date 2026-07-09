import { ArrowRight, CheckCircle2, Clock3, Globe2, MapPin, Rocket, Search } from "lucide-react";
import Link from "next/link";
import { AppShell } from "@/components/app-shell";

const regions = [
  { name: "Минск", cluster: "Столица", pages: 18, demand: 92, status: "Готово", owner: "SEO" },
  { name: "Гомель", cluster: "Юг", pages: 12, demand: 74, status: "Проверка", owner: "Маркетинг" },
  { name: "Витебск", cluster: "Север", pages: 9, demand: 58, status: "Черновик", owner: "SEO" },
  { name: "Брест", cluster: "Запад", pages: 10, demand: 63, status: "Очередь", owner: "Контент" },
];

const templates = [
  { title: "Категория + город", pages: 42, intent: "Коммерческий", ready: "86%" },
  { title: "Филиал + услуга", pages: 24, intent: "Навигационный", ready: "71%" },
  { title: "Сравнение поставщиков", pages: 16, intent: "Исследование", ready: "54%" },
];

const queue = [
  { task: "Проверить каннибализацию Минск/область", state: "Сегодня", icon: Search },
  { task: "Опубликовать Гомель после финального H1", state: "2 страницы", icon: Rocket },
  { task: "Собрать локальные FAQ для Витебска", state: "Нужно ТЗ", icon: Clock3 },
];

function statusTone(status: string) {
  if (status === "Готово") return "bg-green-100 text-green-700";
  if (status === "Проверка") return "bg-amber-100 text-amber-700";
  if (status === "Черновик") return "bg-blue-100 text-blue-700";
  return "bg-sunken text-muted";
}

export default function MarketingGeoPage() {
  const totalPages = regions.reduce((sum, region) => sum + region.pages, 0);
  const avgDemand = Math.round(regions.reduce((sum, region) => sum + region.demand, 0) / regions.length);

  return (
    <AppShell crumbs={["ERP", "Маркетинг", "Гео-фабрика"]}>
      <main className="flex-1 overflow-auto bg-sunken/30 p-6">
        <div className="mx-auto grid max-w-7xl gap-5">
          <section className="flex flex-wrap items-start justify-between gap-4">
            <div>
              <div className="flex items-center gap-2 text-sm font-semibold text-accent-ink">
                <Globe2 size={16} />
                SEO / GEO production
              </div>
              <h1 className="mt-1 text-2xl font-bold text-ink">Гео-фабрика</h1>
            </div>
            <Link
              href="/erp/marketing/seo"
              className="inline-flex items-center gap-2 rounded-lg bg-accent px-3 py-2 text-sm font-semibold text-white shadow-card hover:bg-accent-ink"
            >
              SEO-проекты <ArrowRight size={16} />
            </Link>
          </section>

          <section className="grid gap-3 md:grid-cols-4">
            {[
              ["Страниц в плане", totalPages.toString(), "по активным регионам"],
              ["Средний спрос", `${avgDemand}%`, "оценка intent-fit"],
              ["К запуску", "18", "готовые URL"],
              ["На проверке", "12", "контент + SEO"],
            ].map(([label, value, hint]) => (
              <div key={label} className="rounded-lg bg-surface p-4 shadow-card">
                <div className="text-xs font-semibold uppercase text-faint">{label}</div>
                <div className="mt-2 text-2xl font-bold text-ink">{value}</div>
                <div className="mt-1 text-xs text-muted">{hint}</div>
              </div>
            ))}
          </section>

          <section className="grid gap-5 lg:grid-cols-[1.5fr_1fr]">
            <div className="overflow-hidden rounded-lg bg-surface shadow-card">
              <div className="flex items-center justify-between border-b border-line px-4 py-3">
                <div>
                  <h2 className="text-sm font-bold text-ink">Региональная очередь</h2>
                  <p className="text-xs text-muted">Приоритеты публикации по городам и кластерам.</p>
                </div>
                <MapPin size={18} className="text-accent-ink" />
              </div>
              <div className="overflow-x-auto">
                <table className="w-full min-w-[680px] text-left text-sm">
                  <thead className="bg-sunken text-xs uppercase text-faint">
                    <tr>
                      <th className="px-4 py-2">Регион</th>
                      <th className="px-4 py-2">Кластер</th>
                      <th className="px-4 py-2">Страниц</th>
                      <th className="px-4 py-2">Спрос</th>
                      <th className="px-4 py-2">Статус</th>
                      <th className="px-4 py-2">Владелец</th>
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-line">
                    {regions.map((region) => (
                      <tr key={region.name}>
                        <td className="px-4 py-3 font-semibold text-ink">{region.name}</td>
                        <td className="px-4 py-3 text-muted">{region.cluster}</td>
                        <td className="px-4 py-3 text-ink">{region.pages}</td>
                        <td className="px-4 py-3">
                          <div className="flex items-center gap-2">
                            <div className="h-2 w-24 overflow-hidden rounded-full bg-sunken">
                              <div className="h-full bg-accent" style={{ width: `${region.demand}%` }} />
                            </div>
                            <span className="text-xs text-muted">{region.demand}%</span>
                          </div>
                        </td>
                        <td className="px-4 py-3">
                          <span className={`rounded-md px-2 py-1 text-xs font-semibold ${statusTone(region.status)}`}>
                            {region.status}
                          </span>
                        </td>
                        <td className="px-4 py-3 text-muted">{region.owner}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </div>

            <div className="grid gap-5">
              <div className="rounded-lg bg-surface p-4 shadow-card">
                <div className="flex items-center justify-between">
                  <h2 className="text-sm font-bold text-ink">Шаблоны</h2>
                  <CheckCircle2 size={18} className="text-money" />
                </div>
                <div className="mt-3 grid gap-3">
                  {templates.map((template) => (
                    <div key={template.title} className="rounded-lg border border-line p-3">
                      <div className="flex items-center justify-between gap-3">
                        <div className="font-semibold text-ink">{template.title}</div>
                        <div className="text-sm font-bold text-accent-ink">{template.ready}</div>
                      </div>
                      <div className="mt-1 flex items-center justify-between text-xs text-muted">
                        <span>{template.intent}</span>
                        <span>{template.pages} страниц</span>
                      </div>
                    </div>
                  ))}
                </div>
              </div>

              <div className="rounded-lg bg-surface p-4 shadow-card">
                <h2 className="text-sm font-bold text-ink">Контроль дня</h2>
                <div className="mt-3 grid gap-2">
                  {queue.map(({ task, state, icon: Icon }) => (
                    <div key={task} className="flex items-center gap-3 rounded-lg bg-sunken px-3 py-2">
                      <Icon size={16} className="text-accent-ink" />
                      <div className="min-w-0 flex-1">
                        <div className="truncate text-sm font-medium text-ink">{task}</div>
                        <div className="text-xs text-muted">{state}</div>
                      </div>
                    </div>
                  ))}
                </div>
              </div>
            </div>
          </section>
        </div>
      </main>
    </AppShell>
  );
}
