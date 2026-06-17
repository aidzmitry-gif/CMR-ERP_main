import "@/app/design/themes/themes.css";
import { FullDealCard, FullKanban, FullRop } from "@/app/design/full/themed-screens";

/** Полноразмерный themed-экран на весь экран. /design/full/theme-C/deal-card и т.п. */

const THEME_NAMES: Record<string, string> = {
  "theme-A": "A · Stripe / Notion", "theme-B": "B · Linear / Vercel", "theme-C": "C · Enterprise data",
  "theme-D": "D · Dark cockpit", "theme-E": "E · Warm editorial", "theme-F": "F · High-contrast bold",
};
const SCREENS: Record<string, { title: string; render: () => React.ReactNode }> = {
  "deal-card": { title: "Карточка сделки", render: FullDealCard },
  kanban: { title: "Доска сделок (канбан)", render: FullKanban },
  rop: { title: "Обзор РОП + графики", render: FullRop },
};

export function generateStaticParams() {
  const themes = Object.keys(THEME_NAMES), screens = Object.keys(SCREENS);
  return themes.flatMap((theme) => screens.map((screen) => ({ theme, screen })));
}

export default async function FullScreenPage({ params }: { params: Promise<{ theme: string; screen: string }> }) {
  const { theme, screen } = await params;
  const sc = SCREENS[screen];
  const themeName = THEME_NAMES[theme] ?? theme;
  if (!sc) return <div className="p-8">Экран не найден</div>;

  return (
    <div className={`tw-theme ${theme}`} style={{ minHeight: "100vh", background: "var(--t-canvas)", fontFamily: "var(--t-font)", color: "var(--t-ink)" }}>
      <div style={{ position: "sticky", top: 0, zIndex: 30, background: "var(--t-surface)", borderBottom: "1px solid var(--t-line)", padding: "10px 24px", display: "flex", gap: 12, alignItems: "center", fontSize: 12.5 }}>
        <a href="/design/themes" style={{ color: "var(--t-accent-ink)", fontWeight: 600, textDecoration: "none" }}>← Все стили</a>
        <span style={{ color: "var(--t-muted)" }}>{themeName} · {sc.title}</span>
        <span style={{ marginLeft: "auto", display: "flex", gap: 8 }}>
          {Object.entries(SCREENS).map(([k, v]) => (
            <a key={k} href={`/design/full/${theme}/${k}`} style={{ fontSize: 12, color: k === screen ? "var(--t-accent-ink)" : "var(--t-muted)", fontWeight: k === screen ? 700 : 500, textDecoration: "none" }}>{v.title.split(" ")[0]}</a>
          ))}
        </span>
      </div>
      <div style={{ maxWidth: 1280, margin: "0 auto", padding: 24 }}>{sc.render()}</div>
    </div>
  );
}
