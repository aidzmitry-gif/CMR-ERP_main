/** Индекс полноразмерных themed-экранов: 6 стилей × 3 экрана = 18 ссылок. /design/full */

const THEMES = [
  ["theme-A", "A · Stripe / Notion"], ["theme-B", "B · Linear / Vercel"], ["theme-C", "C · Enterprise data"],
  ["theme-D", "D · Dark cockpit"], ["theme-E", "E · Warm editorial"], ["theme-F", "F · High-contrast bold"],
];
const SCREENS = [["deal-card", "Карточка сделки"], ["kanban", "Канбан"], ["rop", "РОП + графики"]];

export default function FullIndexPage() {
  return (
    <main className="mx-auto max-w-[900px] p-8">
      <p className="text-[11px] font-semibold uppercase tracking-wide text-faint">Полные экраны для выбора</p>
      <h1 className="mt-1 text-2xl font-bold tracking-tight">6 стилей × 3 экрана</h1>
      <p className="mt-1 text-sm text-muted">Каждый — на весь экран, с деталями. Открывай и сравнивай. Внутри можно переключать экран.</p>

      <div className="mt-6 space-y-3">
        {THEMES.map(([id, name]) => (
          <div key={id} className="flex flex-wrap items-center gap-3 rounded-xl border border-line bg-surface p-4 shadow-card">
            <span className="min-w-[180px] text-sm font-bold">{name}</span>
            {SCREENS.map(([s, label]) => (
              <a key={s} href={`/design/full/${id}/${s}`} className="rounded-lg bg-accent-soft px-3 py-1.5 text-[13px] font-semibold text-accent-ink hover:bg-accent hover:text-white">
                {label}
              </a>
            ))}
          </div>
        ))}
      </div>
    </main>
  );
}
