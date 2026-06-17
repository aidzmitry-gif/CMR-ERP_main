import "./themes.css";
import type { CSSProperties, ReactNode } from "react";

/**
 * ГАЛЕРЕЯ 3 ТЕМ × 3 ЭКРАНА (9 фрагментов) для выбора итогового стиля.
 * Один комплект вёрстки на CSS-переменных (--t-*), тема задаётся классом.
 * После выбора — победившую тему применяем в живые экраны. Открыть: /design/themes
 */

const GROUP1 = [
  { id: "theme-A", name: "A · Stripe / Notion", desc: "светлый, тёплый, воздушный, индиго" },
  { id: "theme-B", name: "B · Linear / Vercel", desc: "строгий, плотный, графит, тонкие границы" },
  { id: "theme-C", name: "C · Enterprise data", desc: "деловой, корпоративный синий, max данных" },
];
const GROUP2 = [
  { id: "theme-D", name: "D · Dark cockpit", desc: "тёмная тема, «командный центр», мониторинг" },
  { id: "theme-E", name: "E · Warm editorial", desc: "тёплый бумажный, премиальный фин-отчёт" },
  { id: "theme-F", name: "F · High-contrast bold", desc: "яркий, контрастный, крупная типографика" },
];

function ThemeColumn({ t }: { t: { id: string; name: string; desc: string } }) {
  return (
    <div className="space-y-4">
      <div className="rounded-xl border border-line bg-surface p-3 shadow-card">
        <div className="text-sm font-bold">{t.name}</div>
        <div className="text-[12px] text-muted">{t.desc}</div>
      </div>
      <div className={`tw-theme ${t.id} space-y-4 rounded-2xl p-3`} style={{ background: "var(--t-canvas)" }}>
        <DealCardMini />
        <KanbanMini />
        <RopMini />
      </div>
    </div>
  );
}

export default function ThemesGalleryPage() {
  return (
    <main className="mx-auto max-w-[1320px] p-6">
      <header className="mb-6">
        <p className="text-[11px] font-semibold uppercase tracking-wide text-faint">Выбор стиля · 6 вариантов × 3 экрана</p>
        <h1 className="mt-1 text-2xl font-bold tracking-tight">Сравните дизайн-решения</h1>
        <p className="mt-1 text-sm text-muted">
          Каждый столбец — один стиль на трёх экранах (карточка сделки · канбан · РОП+график). Выберите столбец —
          победителя применим в живые экраны.
        </p>
      </header>

      <h2 className="mb-3 text-[11px] font-semibold uppercase tracking-wide text-faint">Первая тройка</h2>
      <div className="grid gap-5 lg:grid-cols-3">
        {GROUP1.map((t) => <ThemeColumn key={t.id} t={t} />)}
      </div>

      <h2 className="mb-3 mt-10 text-[11px] font-semibold uppercase tracking-wide text-faint">Ещё три стиля</h2>
      <div className="grid gap-5 lg:grid-cols-3">
        {GROUP2.map((t) => <ThemeColumn key={t.id} t={t} />)}
      </div>
    </main>
  );
}

// ── общие themed-обёртки на переменных ──
const surface: CSSProperties = {
  background: "var(--t-surface)",
  border: "var(--t-card-border)",
  borderRadius: "var(--t-radius)",
  boxShadow: "var(--t-shadow)",
  fontFamily: "var(--t-font)",
  color: "var(--t-ink)",
};
function Panel({ children, style }: { children: ReactNode; style?: CSSProperties }) {
  return <div style={{ ...surface, overflow: "hidden", ...style }}>{children}</div>;
}
function Head({ children }: { children: ReactNode }) {
  return (
    <div style={{ padding: "10px var(--t-pad)", borderBottom: "1px solid var(--t-line)", fontWeight: "var(--t-header-weight)" as CSSProperties["fontWeight"], fontSize: 13 }}>
      {children}
    </div>
  );
}
function Chip({ children, bg, fg }: { children: ReactNode; bg: string; fg: string }) {
  return (
    <span style={{ display: "inline-flex", alignItems: "center", borderRadius: 999, padding: "2px 8px", fontSize: 11, fontWeight: 600, background: bg, color: fg }}>
      {children}
    </span>
  );
}
function Btn({ children, kind = "primary" }: { children: ReactNode; kind?: "primary" | "money" | "sec" }) {
  const base: CSSProperties = { fontSize: 12, fontWeight: 600, padding: "7px 12px", borderRadius: "var(--t-radius-sm)", border: "1px solid transparent", fontFamily: "var(--t-font)", cursor: "pointer" };
  const styles: Record<string, CSSProperties> = {
    primary: { background: "var(--t-accent)", color: "#fff" },
    money: { background: "var(--t-money)", color: "#fff" },
    sec: { background: "var(--t-surface)", color: "var(--t-ink)", border: "1px solid var(--t-line-strong)" },
  };
  return <button style={{ ...base, ...styles[kind] }}>{children}</button>;
}
const num: CSSProperties = { fontVariantNumeric: "tabular-nums" };

// ════════ ЭКРАН 1: карточка сделки (мини) ════════
function DealCardMini() {
  return (
    <Panel style={{ padding: "var(--t-pad)" }}>
      <div style={{ fontSize: 11, color: "var(--t-faint)", fontWeight: 600, ...num }}>CRM-1029 · 11 дн</div>
      <div style={{ fontSize: 16, fontWeight: 700, marginTop: 2 }}>ООО «БелТранс» — АКБ</div>
      <div style={{ display: "flex", gap: 5, marginTop: 8, flexWrap: "wrap" }}>
        <Chip bg="var(--t-money-soft)" fg="var(--t-money)">★ Постоянный</Chip>
        <Chip bg="var(--t-red-soft)" fg="var(--t-red)">Высокий</Chip>
        <Chip bg="var(--t-amber-soft)" fg="var(--t-amber)">🚚 18.06</Chip>
      </div>
      {/* деньги: маржа главная */}
      <div style={{ display: "grid", gridTemplateColumns: "1.3fr 1fr 1fr", gap: 1, marginTop: 12, background: "var(--t-line)", border: "1px solid var(--t-line)", borderRadius: "var(--t-radius-sm)", overflow: "hidden" }}>
        <div style={{ background: "var(--t-money-soft)", padding: 10 }}>
          <div style={{ fontSize: 9, textTransform: "uppercase", color: "var(--t-money)", fontWeight: 700 }}>💰 Маржа</div>
          <div style={{ fontSize: 18, fontWeight: 700, color: "var(--t-money)", ...num }}>+12 400</div>
        </div>
        <div style={{ background: "var(--t-surface)", padding: 10 }}>
          <div style={{ fontSize: 9, textTransform: "uppercase", color: "var(--t-faint)", fontWeight: 700 }}>Сумма</div>
          <div style={{ fontSize: 14, fontWeight: 700, ...num }}>46 800</div>
        </div>
        <div style={{ background: "var(--t-surface)", padding: 10 }}>
          <div style={{ fontSize: 9, textTransform: "uppercase", color: "var(--t-faint)", fontWeight: 700 }}>К доплате</div>
          <div style={{ fontSize: 14, fontWeight: 700, ...num }}>26 800</div>
        </div>
      </div>
      <div style={{ display: "flex", gap: 6, marginTop: 12 }}>
        <Btn kind="money">💳 Доплата</Btn>
        <Btn kind="sec">📞 Звонок</Btn>
      </div>
    </Panel>
  );
}

// ════════ ЭКРАН 2: канбан (мини, 2 колонки) ════════
function KanbanMini() {
  const cols = [
    { title: "Квалификация", color: "#8B5CF6", deals: [{ c: "Завод Прогресс", a: "2 500 000", p: "Высокий" }, { c: "ПАО Энергия", a: "3 200 000", p: "Средний" }] },
    { title: "Согласование", color: "#14B8A6", deals: [{ c: "ПАО ХимПром", a: "4 200 000", p: "Высокий" }] },
  ];
  return (
    <Panel style={{ padding: "var(--t-pad)" }}>
      <div style={{ fontSize: 12, fontWeight: "var(--t-header-weight)" as CSSProperties["fontWeight"], marginBottom: 10 }}>Доска сделок</div>
      <div style={{ display: "flex", gap: 8 }}>
        {cols.map((col) => (
          <div key={col.title} style={{ flex: 1 }}>
            <div style={{ ...surface, overflow: "hidden", marginBottom: 8 }}>
              <div style={{ height: 3, background: col.color }} />
              <div style={{ padding: "6px 8px", fontSize: 11, fontWeight: 700 }}>{col.title}</div>
            </div>
            {col.deals.map((d) => (
              <div key={d.c} style={{ ...surface, padding: 8, marginBottom: 6 }}>
                <div style={{ fontSize: 11.5, fontWeight: 600 }}>{d.c}</div>
                <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginTop: 5 }}>
                  <span style={{ fontSize: 12, fontWeight: 700, ...num }}>{d.a}</span>
                  <Chip bg={d.p === "Высокий" ? "var(--t-red-soft)" : "var(--t-amber-soft)"} fg={d.p === "Высокий" ? "var(--t-red)" : "var(--t-amber)"}>{d.p}</Chip>
                </div>
              </div>
            ))}
          </div>
        ))}
      </div>
    </Panel>
  );
}

// ════════ ЭКРАН 3: РОП + график ════════
function RopMini() {
  const team = [{ n: "Анна А.", p: 92 }, { n: "Дмитрий Д.", p: 74 }, { n: "Сергей С.", p: 48 }];
  const rev = [180, 210, 195, 240, 228, 280];
  const max = Math.max(...rev), min = Math.min(...rev);
  const pts = rev.map((v, i) => `${(i / (rev.length - 1)) * 100},${30 - ((v - min) / (max - min)) * 26}`).join(" ");
  return (
    <Panel>
      <Head>Обзор РОП · июнь</Head>
      <div style={{ padding: "var(--t-pad)" }}>
        {/* мини-KPI */}
        <div style={{ display: "flex", gap: 8, marginBottom: 12 }}>
          <div style={{ flex: 1 }}>
            <div style={{ fontSize: 9, textTransform: "uppercase", color: "var(--t-faint)", fontWeight: 700 }}>План</div>
            <div style={{ fontSize: 16, fontWeight: 700, ...num }}>280 000</div>
          </div>
          <div style={{ flex: 1 }}>
            <div style={{ fontSize: 9, textTransform: "uppercase", color: "var(--t-faint)", fontWeight: 700 }}>Прогноз</div>
            <div style={{ fontSize: 16, fontWeight: 700, color: "var(--t-money)", ...num }}>193 000</div>
          </div>
        </div>
        {/* график выручки */}
        <svg viewBox="0 0 100 30" style={{ width: "100%", height: 50 }} preserveAspectRatio="none">
          <polyline points={pts} fill="none" stroke="var(--t-accent)" strokeWidth="2" vectorEffect="non-scaling-stroke" />
        </svg>
        {/* бары команды */}
        <div style={{ marginTop: 10, display: "flex", flexDirection: "column", gap: 7 }}>
          {team.map((t) => {
            const c = t.p >= 85 ? "var(--t-money)" : t.p >= 60 ? "var(--t-amber)" : "var(--t-red)";
            return (
              <div key={t.n}>
                <div style={{ display: "flex", justifyContent: "space-between", fontSize: 12 }}>
                  <span>{t.n}</span><span style={{ fontWeight: 700, color: c, ...num }}>{t.p}%</span>
                </div>
                <div style={{ height: 6, borderRadius: 99, background: "var(--t-line)", overflow: "hidden", marginTop: 3 }}>
                  <div style={{ height: "100%", width: `${t.p}%`, background: c, borderRadius: 99 }} />
                </div>
              </div>
            );
          })}
        </div>
      </div>
    </Panel>
  );
}
