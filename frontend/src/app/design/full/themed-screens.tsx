import type { CSSProperties, ReactNode } from "react";

/* Полноразмерные themed-экраны на CSS-переменных (--t-*). Один код → любая тема.
   Используются маршрутом /design/full/[theme]/[screen]. */

const num: CSSProperties = { fontVariantNumeric: "tabular-nums" };
const card: CSSProperties = {
  background: "var(--t-surface)", border: "var(--t-card-border)",
  borderRadius: "var(--t-radius)", boxShadow: "var(--t-shadow)", overflow: "hidden",
};
function Card({ children, style }: { children: ReactNode; style?: CSSProperties }) {
  return <div style={{ ...card, ...style }}>{children}</div>;
}
function Head({ children, right }: { children: ReactNode; right?: ReactNode }) {
  return (
    <div style={{ display: "flex", alignItems: "center", gap: 8, padding: "11px var(--t-pad)", borderBottom: "1px solid var(--t-line)", fontWeight: "var(--t-header-weight)" as CSSProperties["fontWeight"], fontSize: 13.5 }}>
      {children}{right && <span style={{ marginLeft: "auto", fontWeight: 500, fontSize: 11.5, color: "var(--t-muted)" }}>{right}</span>}
    </div>
  );
}
function Chip({ children, bg, fg }: { children: ReactNode; bg: string; fg: string }) {
  return <span style={{ display: "inline-flex", alignItems: "center", gap: 4, borderRadius: 999, padding: "3px 9px", fontSize: 11, fontWeight: 600, background: bg, color: fg }}>{children}</span>;
}
function Btn({ children, kind = "primary", sm }: { children: ReactNode; kind?: "primary" | "money" | "sec" | "ghost" | "call"; sm?: boolean }) {
  const base: CSSProperties = { display: "inline-flex", alignItems: "center", gap: 6, fontSize: sm ? 12 : 13, fontWeight: 600, padding: sm ? "7px 11px" : "9px 14px", borderRadius: "var(--t-radius-sm)", border: "1px solid transparent", fontFamily: "var(--t-font)", cursor: "pointer", whiteSpace: "nowrap" };
  const map: Record<string, CSSProperties> = {
    primary: { background: "var(--t-accent)", color: "#fff" },
    money: { background: "var(--t-money)", color: "#fff" },
    call: { background: "var(--t-money)", color: "#fff" },
    sec: { background: "var(--t-surface)", color: "var(--t-ink)", border: "1px solid var(--t-line-strong)" },
    ghost: { background: "transparent", color: "var(--t-muted)" },
  };
  return <button style={{ ...base, ...map[kind] }}>{children}</button>;
}
const eyebrow: CSSProperties = { fontSize: 10, textTransform: "uppercase", letterSpacing: ".05em", color: "var(--t-faint)", fontWeight: 700 };

// ═══════════════ ЭКРАН: КАРТОЧКА СДЕЛКИ (полная) ═══════════════
export function FullDealCard() {
  const stages = ["Новая", "В работе", "Квалиф.", "Цена", "Есть цена", "Встреча", "Счёт", "Защищён", "Договор"];
  const cur = 6;
  const items = [
    { n: "АКБ 6СТ-190", s: "Минск · свободно 40", q: 12, p: "3 600", m: "+24%", sum: "43 200" },
    { n: "Доставка по Минску", s: "авто рейса", q: 1, p: "600", m: "+40%", sum: "600" },
    { n: "Утилизация старых АКБ", s: "допуслуга", q: 12, p: "250", m: "+62%", sum: "3 000" },
  ];
  const docs = [
    ["Счёт СЧ-0462", "от 14.06 · 46 800 BYN", "money", "Проведён"],
    ["Договор ДГ-0125", "черновик · ждёт подписи", "amber", "Черновик"],
    ["Заказ-наряд ЗН-0207", "комплектация", "accent", "В работе"],
    ["Акт приёма-передачи", "после доставки", "slate", "Нет"],
  ];
  const tone = (t: string): [string, string] => ({
    money: ["var(--t-money-soft)", "var(--t-money)"], amber: ["var(--t-amber-soft)", "var(--t-amber)"],
    accent: ["var(--t-accent-soft)", "var(--t-accent-ink)"], red: ["var(--t-red-soft)", "var(--t-red)"],
    slate: ["var(--t-sunken)", "var(--t-muted)"],
  } as Record<string, [string, string]>)[t];

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 16 }}>
      {/* ШАПКА */}
      <Card style={{ padding: "var(--t-pad)" }}>
        <div style={{ display: "flex", flexWrap: "wrap", gap: 12 }}>
          <div>
            <div style={{ ...num, fontSize: 12, color: "var(--t-faint)", fontWeight: 600 }}>CRM-1029 · в работе 11 дн</div>
            <div style={{ fontSize: 20, fontWeight: 700, marginTop: 2 }}>ООО «БелТранс» — поставка АКБ</div>
            <div style={{ fontSize: 12.5, color: "var(--t-muted)", marginTop: 3 }}>Аккумуляторные батареи 6СТ-190 · 12 шт · рейс CN→MSK</div>
            <div style={{ display: "flex", gap: 6, marginTop: 9, flexWrap: "wrap" }}>
              <Chip {...chip(tone("money"))}>★ Постоянный клиент</Chip>
              <Chip {...chip(tone("red"))}>Высокий приоритет</Chip>
              <Chip {...chip(tone("amber"))}>🚚 Едет в машине</Chip>
              <Chip {...chip(tone("slate"))}>4 дня в стадии «Счёт»</Chip>
            </div>
          </div>
          <div style={{ marginLeft: "auto", display: "flex", gap: 8, flexWrap: "wrap", alignItems: "flex-start" }}>
            <Btn kind="call" sm>📞 Позвонить</Btn>
            <Btn kind="primary" sm>✦ Спросить AI</Btn>
          </div>
        </div>

        {/* ДЕНЬГИ */}
        <div style={{ display: "grid", gridTemplateColumns: "1.4fr 1fr 1fr 1fr 1fr", gap: 1, marginTop: 14, background: "var(--t-line)", border: "1px solid var(--t-line)", borderRadius: "var(--t-radius-sm)", overflow: "hidden" }}>
          <MoneyCell label="💰 Маржа сделки" value="+12 400 BYN" sub="26.5% · норма ≥ 18%" hero />
          <MoneyCell label="Сумма" value="46 800" sub="счёт СЧ-0462" />
          <MoneyCell label="Оплачено" value="20 000" sub="43% · аванс" money />
          <MoneyCell label="К доплате" value="26 800" sub="до отгрузки" />
          <MoneyCell label="🚚 Товар приедет" value="18.06" sub="резерв до 19.06" amber />
        </div>

        {/* СТАДИИ */}
        <div style={{ display: "flex", alignItems: "flex-start", marginTop: 16, overflowX: "auto" }}>
          {stages.map((s, i) => (
            <div key={s} style={{ flex: 1, minWidth: 64, textAlign: "center", position: "relative" }}>
              {i < stages.length - 1 && <div style={{ position: "absolute", left: "50%", top: 9, width: "100%", height: 2, background: i < cur ? "var(--t-accent)" : "var(--t-line-strong)", zIndex: 0 }} />}
              <div style={{ position: "relative", zIndex: 1, width: 19, height: 19, borderRadius: "50%", margin: "0 auto", display: "flex", alignItems: "center", justifyContent: "center", fontSize: 9, fontWeight: 700, color: "#fff", background: i < cur ? "var(--t-accent)" : i === cur ? "var(--t-amber)" : "var(--t-line-strong)" }}>{i < cur ? "✓" : i + 1}</div>
              <div style={{ fontSize: 10, marginTop: 6, color: i <= cur ? "var(--t-ink)" : "var(--t-faint)", fontWeight: i <= cur ? 600 : 400 }}>{s}</div>
            </div>
          ))}
        </div>
      </Card>

      {/* ACTION-BAR */}
      <Card style={{ background: "var(--t-accent-soft)", borderColor: "var(--t-accent)" }}>
        <div style={{ display: "flex", flexWrap: "wrap", alignItems: "center", gap: 16, padding: "var(--t-pad)" }}>
          <div style={{ flex: 1, minWidth: 280 }}>
            <div style={{ ...eyebrow, color: "var(--t-accent-ink)" }}>✦ Следующее лучшее действие · AI</div>
            <div style={{ fontSize: 16, fontWeight: 700, marginTop: 4 }}>Дожать доплату 26 800 BYN и отправить договор</div>
            <div style={{ fontSize: 12.5, color: "var(--t-muted)", marginTop: 4 }}>Аванс 43% получен. Прибыль собственнику — <b style={{ color: "var(--t-money)" }}>+12 400 BYN</b>.</div>
          </div>
          <div style={{ display: "flex", gap: 8 }}><Btn kind="money">💳 Запросить доплату</Btn><Btn kind="ghost">Позже</Btn></div>
        </div>
      </Card>

      <div style={{ display: "grid", gridTemplateColumns: "1.6fr 1fr", gap: 16 }}>
        <div style={{ display: "flex", flexDirection: "column", gap: 16 }}>
          {/* СОСТАВ */}
          <Card>
            <Head right="＋ со склада">📦 Состав счёта и маржа</Head>
            <div style={{ padding: "var(--t-pad)" }}>
              <table style={{ width: "100%", fontSize: 13, borderCollapse: "collapse" }}>
                <thead><tr style={{ ...eyebrow }}>
                  <th style={{ textAlign: "left", paddingBottom: 9 }}>Позиция</th>
                  <th style={{ textAlign: "right" }}>Кол-во</th><th style={{ textAlign: "right" }}>Цена</th>
                  <th style={{ textAlign: "right" }}>Маржа</th><th style={{ textAlign: "right" }}>Сумма</th>
                </tr></thead>
                <tbody>
                  {items.map((it) => (
                    <tr key={it.n} style={{ borderTop: "1px solid var(--t-line)" }}>
                      <td style={{ padding: "9px 0" }}><div style={{ fontWeight: 500 }}>{it.n}</div><div style={{ fontSize: 11, color: "var(--t-faint)" }}>{it.s}</div></td>
                      <td style={{ textAlign: "right", ...num }}>{it.q}</td><td style={{ textAlign: "right", ...num }}>{it.p}</td>
                      <td style={{ textAlign: "right", fontWeight: 700, color: "var(--t-money)", ...num }}>{it.m}</td>
                      <td style={{ textAlign: "right", ...num }}>{it.sum}</td>
                    </tr>
                  ))}
                  <tr style={{ borderTop: "1px solid var(--t-line-strong)", fontWeight: 700 }}>
                    <td style={{ padding: "10px 0" }}>Итого · маржа 26.5%</td><td /><td />
                    <td style={{ textAlign: "right", color: "var(--t-money)", ...num }}>+12 400</td>
                    <td style={{ textAlign: "right", ...num }}>46 800</td>
                  </tr>
                </tbody>
              </table>
              <div style={{ marginTop: 13, background: "var(--t-red-soft)", color: "var(--t-red)", borderRadius: "var(--t-radius-sm)", padding: "9px 12px", fontSize: 12, fontWeight: 500 }}>🔒 Скидка 15% превышает порог 10% — требует согласования РОПа.</div>
            </div>
          </Card>

          {/* КАССА */}
          <Card>
            <Head right="landed cost 34 400 BYN">💰 Касса по сделке</Head>
            <div style={{ padding: "var(--t-pad)" }}>
              <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr 1fr", gap: 10 }}>
                {[["Оплачено", "20 000", true], ["К доплате", "26 800", false], ["Прибыль", "+12 400", true]].map(([l, v, g]) => (
                  <div key={l as string} style={{ background: "var(--t-sunken)", border: "1px solid var(--t-line)", borderRadius: "var(--t-radius-sm)", padding: "10px 12px" }}>
                    <div style={{ fontSize: 10.5, textTransform: "uppercase", color: "var(--t-muted)", fontWeight: 600 }}>{l as string}</div>
                    <div style={{ fontSize: 16, fontWeight: 700, marginTop: 3, color: g ? "var(--t-money)" : "var(--t-ink)", ...num }}>{v as string}</div>
                  </div>
                ))}
              </div>
              <div style={{ height: 9, borderRadius: 99, background: "var(--t-line)", overflow: "hidden", margin: "13px 0 5px" }}><div style={{ height: "100%", width: "43%", background: "var(--t-money)" }} /></div>
              <div style={{ display: "flex", gap: 8, marginTop: 12 }}><Btn kind="money" sm>💳 Запросить доплату</Btn><Btn kind="sec" sm>Сверка</Btn></div>
            </div>
          </Card>
        </div>

        <div style={{ display: "flex", flexDirection: "column", gap: 16 }}>
          {/* КОНТАКТЫ */}
          <Card>
            <Head right="＋">👤 Контакты</Head>
            <div style={{ padding: "var(--t-pad)" }}>
              {[["ИП", "Иван Петров", "Директор по закупкам", true], ["СК", "Светлана Кузьмина", "Бухгалтер", false]].map(([ini, n, r, lpr]) => (
                <div key={n as string} style={{ display: "flex", gap: 11, padding: "10px 0", borderTop: "1px solid var(--t-line)" }}>
                  <div style={{ width: 34, height: 34, borderRadius: "var(--t-radius-sm)", background: lpr ? "var(--t-money-soft)" : "var(--t-accent-soft)", color: lpr ? "var(--t-money)" : "var(--t-accent-ink)", display: "flex", alignItems: "center", justifyContent: "center", fontSize: 12, fontWeight: 700, flexShrink: 0 }}>{ini as string}</div>
                  <div style={{ flex: 1 }}>
                    <div style={{ fontSize: 13, fontWeight: 600, display: "flex", gap: 6, alignItems: "center" }}>{n as string}{lpr && <Chip {...chip(tone("money"))}>ЛПР</Chip>}</div>
                    <div style={{ fontSize: 11.5, color: "var(--t-muted)" }}>{r as string}</div>
                    <div style={{ marginTop: 6 }}><Btn kind="call" sm>📞 Звонок</Btn></div>
                  </div>
                </div>
              ))}
            </div>
          </Card>

          {/* ДОКУМЕНТЫ */}
          <Card>
            <Head right="пакет">📄 Документы</Head>
            <div style={{ padding: "var(--t-pad)" }}>
              {docs.map(([n, s, t, lbl]) => (
                <div key={n} style={{ display: "flex", alignItems: "center", gap: 10, padding: "9px 0", borderTop: "1px solid var(--t-line)" }}>
                  <div style={{ flex: 1 }}><div style={{ fontSize: 13, fontWeight: 500 }}>{n}</div><div style={{ fontSize: 11, color: "var(--t-faint)" }}>{s}</div></div>
                  <Chip {...chip(tone(t))}>{lbl}</Chip>
                </div>
              ))}
            </div>
          </Card>
        </div>
      </div>
    </div>
  );
}

function chip([bg, fg]: [string, string]) { return { bg, fg }; }
function MoneyCell({ label, value, sub, hero, money, amber }: { label: string; value: string; sub: string; hero?: boolean; money?: boolean; amber?: boolean }) {
  const bg = hero ? "var(--t-money-soft)" : amber ? "var(--t-amber-soft)" : "var(--t-surface)";
  const vc = hero || money ? "var(--t-money)" : amber ? "var(--t-amber)" : "var(--t-ink)";
  return (
    <div style={{ background: bg, padding: "12px 14px" }}>
      <div style={{ fontSize: 10, textTransform: "uppercase", letterSpacing: ".05em", fontWeight: 700, color: hero ? "var(--t-money)" : amber ? "var(--t-amber)" : "var(--t-faint)" }}>{label}</div>
      <div style={{ fontSize: hero ? 23 : 17, fontWeight: 700, marginTop: 4, color: vc, fontVariantNumeric: "tabular-nums", letterSpacing: "-.02em" }}>{value}</div>
      <div style={{ fontSize: 11, color: "var(--t-muted)", marginTop: 1 }}>{sub}</div>
    </div>
  );
}

// ═══════════════ ЭКРАН: КАНБАН (полный) ═══════════════
export function FullKanban() {
  const cols = [
    { t: "Новая заявка", c: "#3B82F6", n: 125, sum: "8 450 000", deals: [["ООО МеталлПром", "850 000", "Высокий", true], ["АО СтройКомплект", "1 250 000", "Средний", false]] },
    { t: "Квалификация", c: "#8B5CF6", n: 68, sum: "12 300 000", deals: [["Завод Прогресс", "2 500 000", "Высокий", true], ["ПАО Энергия", "3 200 000", "Средний", false]] },
    { t: "Коммерч. предл.", c: "#F59E0B", n: 35, sum: "9 750 000", deals: [["АльфаМеталл", "1 750 000", "Высокий", true]] },
    { t: "Согласование", c: "#14B8A6", n: 18, sum: "6 200 000", deals: [["ПАО ХимПром", "4 200 000", "Высокий", true], ["СтройИнвест", "1 850 000", "Средний", false]] },
  ];
  const kpis = [["Звонки ключевым", "24", "40", 60], ["Всего звонков", "58", "100", 58], ["План отгрузки", "5,2М", "8М", 65], ["Холодные звонки", "32", "60", 53], ["Заявки", "18", "30", 60]];
  return (
    <div>
      {/* тулбар */}
      <div style={{ display: "flex", gap: 12, flexWrap: "wrap", alignItems: "center" }}>
        <div style={{ flex: 1, minWidth: 220, maxWidth: 360, background: "var(--t-surface)", border: "1px solid var(--t-line-strong)", borderRadius: "var(--t-radius-sm)", padding: "8px 12px", fontSize: 13, color: "var(--t-faint)" }}>🔍 Поиск сделок...</div>
        <Btn kind="sec">⚙ Фильтры</Btn><Btn kind="sec">⏱ Только висяки</Btn>
        <div style={{ marginLeft: "auto" }}><Btn kind="primary">＋ Создать сделку</Btn></div>
      </div>
      {/* скорборд */}
      <div style={{ fontSize: 14, fontWeight: 700, margin: "18px 0 10px" }}>План / Факт</div>
      <div style={{ display: "grid", gridTemplateColumns: "repeat(5,1fr)", gap: 12 }}>
        {kpis.map(([l, v, t, p]) => (
          <Card key={l as string} style={{ padding: 14 }}>
            <div style={{ fontSize: 12, color: "var(--t-muted)", fontWeight: 500 }}>{l as string}</div>
            <div style={{ display: "flex", alignItems: "baseline", gap: 5, marginTop: 6 }}><span style={{ fontSize: 18, fontWeight: 700, ...num }}>{v as string}</span><span style={{ fontSize: 11, color: "var(--t-faint)", ...num }}>/ {t as string}</span></div>
            <div style={{ height: 5, borderRadius: 99, background: "var(--t-line)", overflow: "hidden", marginTop: 8 }}><div style={{ height: "100%", width: `${p}%`, background: "var(--t-accent)" }} /></div>
          </Card>
        ))}
      </div>
      {/* доска */}
      <div style={{ display: "flex", gap: 14, marginTop: 18, overflowX: "auto", paddingBottom: 8 }}>
        {cols.map((col) => (
          <div key={col.t} style={{ width: 280, flexShrink: 0 }}>
            <Card style={{ marginBottom: 10 }}>
              <div style={{ height: 3, background: col.c }} />
              <div style={{ padding: "8px 12px" }}>
                <div style={{ display: "flex", justifyContent: "space-between" }}><span style={{ fontSize: 13, fontWeight: 700 }}>{col.t}</span><span style={{ fontSize: 11, fontWeight: 600, color: "var(--t-muted)", ...num }}>{col.n}</span></div>
                <div style={{ fontSize: 11, color: "var(--t-muted)", marginTop: 2, ...num }}>{col.sum} ₽</div>
              </div>
            </Card>
            <div style={{ display: "flex", flexDirection: "column", gap: 10 }}>
              {col.deals.map(([n, a, p, star]) => (
                <Card key={n as string} style={{ padding: 13 }}>
                  <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
                    <span style={{ fontSize: 13, fontWeight: 600 }}>{n as string}</span>
                    {star ? <span style={{ color: "#F59E0B" }}>★</span> : null}
                  </div>
                  <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginTop: 8 }}>
                    <span style={{ fontSize: 14, fontWeight: 700, ...num }}>{a as string} ₽</span>
                    <Chip bg={p === "Высокий" ? "var(--t-red-soft)" : "var(--t-amber-soft)"} fg={p === "Высокий" ? "var(--t-red)" : "var(--t-amber)"}>{p as string}</Chip>
                  </div>
                  <div style={{ marginTop: 8, paddingTop: 8, borderTop: "1px solid var(--t-line)", fontSize: 11, color: "var(--t-faint)" }}>📞 ✉ 💬 каналы</div>
                </Card>
              ))}
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}

// ═══════════════ ЭКРАН: РОП + ГРАФИКИ (полный) ═══════════════
export function FullRop() {
  const kpis = [["План июнь", "280 000 BYN", "цель"], ["Прогноз", "193 000 BYN", "69% плана", true], ["Покрытие", "3.2×", "норма 3–5×"], ["Конверсия", "27%", "лид→сделка"], ["Цикл", "24 дн", "заявка→закр."], ["Срыв", "12%", "съезжает", false, true]];
  const rev = [180, 210, 195, 240, 228, 280], mar = [42, 51, 47, 63, 58, 74];
  const team = [["Анна А.", 92, "290 000", "72 000", 58], ["Дмитрий Д.", 74, "207 000", "60 000", 41], ["Мария М.", 61, "137 000", "33 000", 33], ["Сергей С.", 48, "100 000", "28 000", 22]];
  const W = 460, H = 150, P = 24;
  const max = Math.max(...rev) * 1.1;
  const x = (i: number) => P + (i / (rev.length - 1)) * (W - P * 2);
  const y = (v: number) => H - P - (v / max) * (H - P * 2);
  const line = (a: number[]) => a.map((v, i) => `${i ? "L" : "M"}${x(i)},${y(v)}`).join(" ");

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 16 }}>
      <div style={{ fontSize: 20, fontWeight: 700 }}>Обзор РОП — июнь 2026</div>
      {/* KPI */}
      <Card>
        <div style={{ display: "grid", gridTemplateColumns: "repeat(6,1fr)" }}>
          {kpis.map(([l, v, s, teal, red], i) => (
            <div key={l as string} style={{ padding: 16, borderRight: i < 5 ? "1px solid var(--t-line)" : "none" }}>
              <div style={{ fontSize: 18, fontWeight: 700, color: teal ? "var(--t-money)" : red ? "var(--t-red)" : "var(--t-ink)", ...num }}>{v as string}</div>
              <div style={{ fontSize: 11, color: "var(--t-muted)", marginTop: 4 }}>{l as string}</div>
              <div style={{ fontSize: 10, color: "var(--t-faint)" }}>{s as string}</div>
            </div>
          ))}
        </div>
      </Card>
      <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 16 }}>
        {/* график выручка+маржа */}
        <Card>
          <Head right="выручка ● маржа ●">Динамика выручки и маржи</Head>
          <div style={{ padding: "var(--t-pad)" }}>
            <svg viewBox={`0 0 ${W} ${H}`} style={{ width: "100%" }}>
              {[0, 0.5, 1].map((g) => <line key={g} x1={P} x2={W - P} y1={P + g * (H - P * 2)} y2={P + g * (H - P * 2)} stroke="var(--t-line)" />)}
              <path d={line(rev)} fill="none" stroke="var(--t-accent)" strokeWidth="2.5" />
              <path d={line(mar.map((m) => m * 3))} fill="none" stroke="var(--t-money)" strokeWidth="2.5" />
              {rev.map((_, i) => <text key={i} x={x(i)} y={H - 6} textAnchor="middle" fontSize="9" fill="var(--t-faint)">{["Янв", "Фев", "Мар", "Апр", "Май", "Июн"][i]}</text>)}
            </svg>
          </div>
        </Card>
        {/* команда */}
        <Card>
          <Head right="июнь, BYN">Команда</Head>
          <div style={{ padding: "var(--t-pad)" }}>
            <table style={{ width: "100%", fontSize: 12.5, borderCollapse: "collapse" }}>
              <thead><tr style={{ ...eyebrow }}><th style={{ textAlign: "left", paddingBottom: 8 }}>Менеджер</th><th style={{ textAlign: "right" }}>В работе</th><th style={{ textAlign: "right" }}>% плана</th><th style={{ textAlign: "right" }}>Звонки</th></tr></thead>
              <tbody>
                {team.map(([n, p, w, , calls]) => {
                  const c = (p as number) >= 85 ? "var(--t-money)" : (p as number) >= 60 ? "var(--t-amber)" : "var(--t-red)";
                  return (
                    <tr key={n as string} style={{ borderTop: "1px solid var(--t-line)" }}>
                      <td style={{ padding: "8px 0", fontWeight: 500 }}>{n as string}</td>
                      <td style={{ textAlign: "right", ...num }}>{w as string}</td>
                      <td style={{ textAlign: "right" }}>
                        <span style={{ display: "inline-flex", alignItems: "center", gap: 6, justifyContent: "flex-end" }}>
                          <span style={{ width: 40, height: 6, borderRadius: 99, background: "var(--t-line)", overflow: "hidden" }}><span style={{ display: "block", height: "100%", width: `${p}%`, background: c }} /></span>
                          <b style={{ color: c, ...num }}>{p as number}%</b>
                        </span>
                      </td>
                      <td style={{ textAlign: "right", ...num }}>{calls as number}</td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        </Card>
      </div>
    </div>
  );
}
