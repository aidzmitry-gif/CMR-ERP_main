"use client";

import {
  AlertTriangle,
  ArrowRight,
  Check,
  CheckCircle2,
  ChevronRight,
  Clock,
  Info,
  Lightbulb,
  Minus,
  Pencil,
  Phone,
  PhoneForwarded,
  Repeat,
  Target,
  TrendingDown,
  TrendingUp,
  Users,
} from "lucide-react";
import { useMemo, useState } from "react";
import { formatByn } from "@/lib/format";

// ── Типы ───────────────────────────────────────────────────────────────────
type ClientStatus = "red" | "amber" | "green";
type ConfBadge = "ok" | "due" | "risk";
type TrendDir = "up" | "down" | "flat";
type SkuStatus = "up" | "same" | "drop";
type AgreementKind = "рамочный" | "регулярно" | "обсужд." | "предв." | "устно" | "—";

type Sku = {
  nm: string;
  hist: string; // факт, шт/мес
  plan: string; // план клиента, шт/мес
  agr: AgreementKind;
  conf: number; // подтв. объём, шт/мес
  stt: SkuStatus;
};

type Client = {
  av: string;
  color: string; // бренд/индивидуальный цвет аватара — допустимое исключение (DESIGN.md §4.1)
  nm: string;
  sub: string;
  st: ClientStatus;
  stt: string;
  last: string;
  int: string;
  next: string;
  nd: "" | "soon" | "over";
  avg: number; // средний чек, BYN
  trend: string;
  trendDir: TrendDir;
  upsell: string; // "—" → нет допродажи
  cbs: ConfBadge;
  conf: number; // уверенность, %
  upd: string;
  pillars: { h: string; a: string; d: string };
  sk: Sku[];
  roll: { c: number; s: number; i: number }; // подтверждено / склад / в пути
};

// demo-данные (бэкенда по экрану пока нет)
const DEMO_CLIENTS: Client[] = [
  {
    av: "СБ", color: "#EF4444", nm: "ООО «СтройБаза»", sub: "Гомель · 11 заказов",
    st: "red", stt: "Просрочен 12 дн", last: "02.03.2026", int: "~90 дн",
    next: "просрочен (01.06)", nd: "over", avg: 18400, trend: "↘ -14%", trendDir: "down",
    upsell: "Не берёт ЗУ — повод вернуть", cbs: "risk", conf: 35, upd: "02.03 — устарело",
    pillars: {
      h: "6СТ-132 ~14 шт/мес, тренд ↘ -14%",
      a: "нет контакта 12 дн — объём НЕ подтверждён",
      d: "стройтехника простаивает — спрос под вопросом",
    },
    sk: [{ nm: "АКБ 6СТ-132", hist: "14", plan: "?", agr: "—", conf: 0, stt: "drop" }],
    roll: { c: 0, s: 20, i: 0 },
  },
  {
    av: "НФ", color: "#EF4444", nm: "ОАО «Нафтан»", sub: "Новополоцк · 8 заказов",
    st: "red", stt: "Просрочен 8 дн", last: "15.03.2026", int: "~120 дн",
    next: "просрочен (05.06)", nd: "over", avg: 62800, trend: "↘ -9%", trendDir: "down",
    upsell: "Промышленные АКБ + сервис", cbs: "risk", conf: 42, upd: "15.03 — устарело",
    pillars: {
      h: "промышл. АКБ ~6 шт/мес, ↘ -9%",
      a: "на паузе, ждут финансирование",
      d: "ремонт цеха перенесён — потребность под вопросом",
    },
    sk: [{ nm: "АКБ промышл.", hist: "6", plan: "?", agr: "—", conf: 0, stt: "drop" }],
    roll: { c: 0, s: 8, i: 0 },
  },
  {
    av: "АМ", color: "#EF4444", nm: "ЧТУП «АвтоМир»", sub: "Минск · 6 заказов",
    st: "red", stt: "Просрочен 5 дн", last: "20.03.2026", int: "~75 дн",
    next: "просрочен (03.06)", nd: "over", avg: 9200, trend: "→ стаб.", trendDir: "flat",
    upsell: "Тестеры АКБ", cbs: "risk", conf: 48, upd: "20.03 — устарело",
    pillars: {
      h: "тестеры ~3 шт/мес, стабильно",
      a: "обещал заявку, не прислал",
      d: "СТО, сезонный спрос",
    },
    sk: [{ nm: "Тестеры АКБ", hist: "3", plan: "4", agr: "устно", conf: 0, stt: "drop" }],
    roll: { c: 0, s: 2, i: 0 },
  },
  {
    av: "БТ", color: "#2563EB", nm: "ОАО «Белтранс»", sub: "Минск · 7 заказов",
    st: "amber", stt: "Пора связаться", last: "12.03.2026", int: "~90 дн",
    next: "через 3 дн (15.06)", nd: "soon", avg: 43200, trend: "↗ +8%", trendDir: "up",
    upsell: "Парк вырос 38→40 → +2 АКБ + 2 ЗУ", cbs: "ok", conf: 92, upd: "12.06",
    pillars: {
      h: "6СТ-190 ~32 шт/мес, 7 заказов, ↗ +8%",
      a: "созвон 12.06 — подтвердил ~36 шт/мес, рамочный на год",
      d: "парк вырос 38→40 машин, плановое ТО Q3",
    },
    sk: [
      { nm: "АКБ 6СТ-190", hist: "32", plan: "36", agr: "рамочный", conf: 36, stt: "up" },
      { nm: "ЗУ зарядное", hist: "4", plan: "6", agr: "обсужд.", conf: 4, stt: "same" },
    ],
    roll: { c: 40, s: 12, i: 18 },
  },
  {
    av: "А7", color: "#F59E0B", nm: "Автопарк №7", sub: "Брест · 5 заказов",
    st: "amber", stt: "Пора связаться", last: "15.02.2026", int: "~120 дн",
    next: "через 2 дн (15.06)", nd: "soon", avg: 49500, trend: "→ стаб.", trendDir: "flat",
    upsell: "Рамочный договор на год", cbs: "ok", conf: 88, upd: "10.06",
    pillars: {
      h: "6СТ-190 ~18 шт/мес",
      a: "годовой рамочный договор подписан",
      d: "5 машин/мес плановое ТО парка",
    },
    sk: [{ nm: "АКБ 6СТ-190", hist: "18", plan: "20", agr: "рамочный", conf: 20, stt: "up" }],
    roll: { c: 20, s: 8, i: 6 },
  },
  {
    av: "ЭМ", color: "#F59E0B", nm: "ТЧУП «Энергомир»", sub: "Витебск · 4 заказа",
    st: "amber", stt: "Пора связаться", last: "01.03.2026", int: "~100 дн",
    next: "через 6 дн (18.06)", nd: "soon", avg: 31600, trend: "↗ +5%", trendDir: "up",
    upsell: "Зарядные + стеллаж", cbs: "due", conf: 68, upd: "01.06 — уточнить",
    pillars: {
      h: "зарядные ~5 шт/мес, ↗ +5%",
      a: "интерес к стеллажу, объём не финализирован",
      d: "расширяют склад — возможен рост",
    },
    sk: [
      { nm: "Зарядные", hist: "5", plan: "8", agr: "предв.", conf: 6, stt: "up" },
      { nm: "Стеллаж", hist: "0", plan: "1", agr: "обсужд.", conf: 0, stt: "same" },
    ],
    roll: { c: 6, s: 4, i: 0 },
  },
  {
    av: "БВ", color: "#22C55E", nm: "РУП «Белводхоз»", sub: "Минск · 9 заказов",
    st: "green", stt: "В цикле", last: "28.05.2026", int: "~60 дн",
    next: "через 34 дн (27.07)", nd: "", avg: 52400, trend: "↗ +11%", trendDir: "up",
    upsell: "—", cbs: "ok", conf: 90, upd: "28.05",
    pillars: {
      h: "АКБ+ЗУ ~28 шт/мес, ↗ +11%",
      a: "цикл 60 дн стабилен, подтвердил",
      d: "насосные станции, плановая замена",
    },
    sk: [
      { nm: "АКБ 6СТ-190", hist: "24", plan: "24", agr: "регулярно", conf: 24, stt: "same" },
      { nm: "ЗУ", hist: "4", plan: "4", agr: "регулярно", conf: 4, stt: "same" },
    ],
    roll: { c: 28, s: 10, i: 20 },
  },
  {
    av: "ГС", color: "#22C55E", nm: "СТО «Гранд-Сервис»", sub: "Гомель · 12 заказов",
    st: "green", stt: "В цикле", last: "30.05.2026", int: "~45 дн",
    next: "через 19 дн (19.07)", nd: "", avg: 14800, trend: "→ стаб.", trendDir: "flat",
    upsell: "—", cbs: "ok", conf: 84, upd: "30.05",
    pillars: {
      h: "АКБ легк. ~16 шт/мес, стабильно",
      a: "регулярный, подтверждает по телефону",
      d: "СТО, ровный поток",
    },
    sk: [{ nm: "АКБ легк.", hist: "16", plan: "16", agr: "устно", conf: 16, stt: "same" }],
    roll: { c: 16, s: 18, i: 0 },
  },
  {
    av: "МЭ", color: "#14B8A6", nm: "УП «Минскэлектро»", sub: "Минск · 6 заказов",
    st: "green", stt: "В цикле", last: "25.05.2026", int: "~70 дн",
    next: "через 38 дн (02.08)", nd: "", avg: 38900, trend: "↗ +6%", trendDir: "up",
    upsell: "—", cbs: "ok", conf: 86, upd: "25.05",
    pillars: {
      h: "промышл. ~14 шт/мес, ↗ +6%",
      a: "счёт оплачен, цикл 70 дн",
      d: "электромонтаж, плановые объекты",
    },
    sk: [{ nm: "АКБ промышл.", hist: "14", plan: "14", agr: "регулярно", conf: 14, stt: "same" }],
    roll: { c: 14, s: 6, i: 10 },
  },
  {
    av: "ВД", color: "#22C55E", nm: "ОДО «ВодоканалСервис»", sub: "Могилёв · 5 заказов",
    st: "green", stt: "В цикле", last: "02.06.2026", int: "~90 дн",
    next: "через 56 дн (31.08)", nd: "", avg: 27300, trend: "→ стаб.", trendDir: "flat",
    upsell: "—", cbs: "ok", conf: 80, upd: "02.06",
    pillars: {
      h: "АКБ ~10 шт/мес, стабильно",
      a: "цикл 90 дн, подтверждает",
      d: "водоканал, плановое обслуживание",
    },
    sk: [{ nm: "АКБ 6СТ-190", hist: "10", plan: "10", agr: "регулярно", conf: 10, stt: "same" }],
    roll: { c: 10, s: 12, i: 0 },
  },
];

// ── Карты токенов статусов ──────────────────────────────────────────────────
const STATUS_TONE: Record<ClientStatus, { dot: string; chip: string; label: string }> = {
  red: { dot: "bg-red-500", chip: "bg-red-50 text-red-600", label: "Уходят" },
  amber: { dot: "bg-amber-500", chip: "bg-amber-50 text-amber-600", label: "Пора связаться" },
  green: { dot: "bg-emerald-500", chip: "bg-emerald-50 text-emerald-600", label: "В цикле" },
};

const NEXT_TONE: Record<"" | "soon" | "over", string> = {
  "": "text-ink",
  soon: "text-amber-600",
  over: "text-red-600",
};

const SKU_TONE: Record<SkuStatus, { chip: string; label: string }> = {
  up: { chip: "bg-emerald-50 text-emerald-600", label: "↑ рост" },
  same: { chip: "bg-sunken text-muted", label: "без изм." },
  drop: { chip: "bg-red-50 text-red-600", label: "снято клиентом" },
};

type FilterKey = "all" | ClientStatus;

const FILTERS: { key: FilterKey; label: string; dot?: string }[] = [
  { key: "all", label: "Все" },
  { key: "red", label: "Уходят", dot: "bg-red-500" },
  { key: "amber", label: "Пора связаться", dot: "bg-amber-500" },
  { key: "green", label: "В цикле", dot: "bg-emerald-500" },
];

// ── Вспомогательные ─────────────────────────────────────────────────────────
function confTone(pct: number): string {
  if (pct >= 80) return "bg-emerald-500";
  if (pct >= 60) return "bg-amber-500";
  return "bg-red-500";
}

function ConfBadgePill({ client }: { client: Client }) {
  if (client.cbs === "ok") {
    return (
      <span className="inline-flex items-center gap-1 rounded-full bg-emerald-50 px-2.5 py-0.5 text-[11px] font-semibold text-emerald-600">
        <CheckCircle2 size={12} /> {client.roll.c} шт/мес
      </span>
    );
  }
  if (client.cbs === "due") {
    return (
      <span className="inline-flex items-center gap-1 rounded-full bg-amber-50 px-2.5 py-0.5 text-[11px] font-semibold text-amber-600">
        <Clock size={12} /> уточнить
      </span>
    );
  }
  return (
    <span className="inline-flex items-center gap-1 rounded-full bg-red-50 px-2.5 py-0.5 text-[11px] font-semibold text-red-600">
      <AlertTriangle size={12} /> не подтв.
    </span>
  );
}

function TrendCell({ dir, label }: { dir: TrendDir; label: string }) {
  const Icon = dir === "up" ? TrendingUp : dir === "down" ? TrendingDown : Minus;
  const cls = dir === "up" ? "text-emerald-600" : dir === "down" ? "text-red-600" : "text-muted";
  return (
    <span className={`inline-flex items-center gap-1 text-xs font-bold ${cls}`}>
      <Icon size={13} /> {label}
    </span>
  );
}

function rollupText(roll: Client["roll"]): { text: string; tone: string } {
  const order = Math.max(0, roll.c - roll.s - roll.i);
  if (order > 0) {
    return {
      text: `подтверждено ${roll.c} шт · склад ${roll.s} · в пути ${roll.i} → дозаказать ${order} шт`,
      tone: "text-amber-600",
    };
  }
  if (roll.c > 0) {
    return {
      text: `подтверждено ${roll.c} шт · склад ${roll.s} · в пути ${roll.i} → достаточно — не заказывать`,
      tone: "text-emerald-600",
    };
  }
  return {
    text: `объём НЕ подтверждён · склад ${roll.s} · в машину не ставим (иначе ляжет на склад)`,
    tone: "text-emerald-600",
  };
}

// ── Верхние KPI удержания ────────────────────────────────────────────────────
type Kpi = { label: string; value: string; delta?: string; deltaTone?: string; valueTone?: string };

const RETENTION_KPIS: Kpi[] = [
  { label: "Постоянных клиентов", value: "38", delta: "+3 за месяц", deltaTone: "text-emerald-600" },
  { label: "Повторная выручка (мес)", value: formatByn(418200), delta: "67% всей выручки", deltaTone: "text-emerald-600" },
  { label: "% удержания", value: "86%", delta: "▲ +4 п.п.", deltaTone: "text-emerald-600" },
  { label: "Пора связаться", value: "7", delta: "в ближайшие 7 дн", deltaTone: "text-muted", valueTone: "text-amber-600" },
  { label: "Уходят (просрочка)", value: "3", delta: "риск потери", deltaTone: "text-red-600", valueTone: "text-red-600" },
];

// ── Блоки постпродажного хвоста ──────────────────────────────────────────────
const FLOW: { icon: React.ReactNode; title: string; tag?: string; body: React.ReactNode }[] = [
  {
    icon: <CheckCircle2 size={15} className="text-emerald-600" />,
    title: "Сделка выиграна",
    tag: "событие sales.deal.won",
    body: (
      <>
        Доставка/оплата прошла. Сейчас на это <b className="font-semibold text-ink">никто не подписан</b> —
        добавляем обработчик <b className="font-semibold text-ink">on_deal_won</b>.
      </>
    ),
  },
  {
    icon: <Users size={15} className="text-accent" />,
    title: "Карточка клиента",
    body: (
      <>
        Обновляется <b className="font-semibold text-ink">last_order</b>, пересчитывается интервал →{" "}
        <b className="font-semibold text-ink">дата следующего заказа</b>. Клиент попадает в этот список.
      </>
    ),
  },
  {
    icon: <Clock size={15} className="text-amber-600" />,
    title: "Авто-задачи",
    body: (
      <>+7 дн: «проверить, всё ли ок» (качество). За lead-time до след. заказа: «пора связаться — перезаказ».</>
    ),
  },
  {
    icon: <Repeat size={15} className="text-accent" />,
    title: "Перезаказ",
    body: (
      <>
        Новая сделка <b className="font-semibold text-ink">по шаблону прошлой</b> (те же позиции), стартует
        ближе к концу воронки + подсказка по допродаже.
      </>
    ),
  },
];

// ── Строка детали (подтверждённый объём) ─────────────────────────────────────
function ConfirmPanel({ client }: { client: Client }) {
  const [skus, setSkus] = useState<Sku[]>(() => client.sk.map((s) => ({ ...s })));
  const [editing, setEditing] = useState(false);
  const [confirmed, setConfirmed] = useState(false);

  const total = useMemo(() => skus.reduce((sum, s) => sum + s.conf, 0), [skus]);
  const roll = useMemo(() => ({ ...client.roll, c: editing || confirmed ? total : client.roll.c }), [client.roll, total, editing, confirmed]);
  const rollup = rollupText(roll);
  const liveBadge: Client = { ...client, roll, cbs: confirmed || editing ? (total > 0 ? "ok" : "risk") : client.cbs };

  function setSkuConf(idx: number, value: number) {
    setSkus((prev) => prev.map((s, i) => (i === idx ? { ...s, conf: Math.max(0, value) } : s)));
  }

  return (
    <div className="rounded-xl bg-surface p-4 shadow-card">
      <div className="mb-3 flex flex-wrap items-center justify-between gap-3">
        <div className="flex items-center gap-2 text-[13px] font-bold text-ink">
          <Target size={15} className="text-accent" /> Подтверждённый объём под закупку
          <ConfBadgePill client={liveBadge} />
        </div>
        <div className="flex items-center gap-2 text-[11px] text-muted">
          обновлено продавцом <b className="font-semibold text-ink">{confirmed ? "сегодня" : editing ? "сейчас" : client.upd}</b> ·
          уверенность <b className="font-semibold text-ink">{client.conf}%</b>
          <span className="inline-block h-1.5 w-[110px] overflow-hidden rounded-full bg-sunken align-middle">
            <span className={`block h-full rounded-full ${confTone(client.conf)}`} style={{ width: `${client.conf}%` }} />
          </span>
        </div>
      </div>

      {/* Три опоры решения */}
      <div className="mb-3 grid grid-cols-1 gap-2.5 md:grid-cols-3">
        <Pillar label="История / опыт" value={client.pillars.h} />
        <Pillar label="Договорённость с клиентом" value={client.pillars.a} />
        <Pillar label="План клиента (его продукт / производство)" value={client.pillars.d} />
      </div>

      {/* Таблица позиций */}
      <div className="overflow-x-auto">
        <table className="mb-2.5 w-full border-collapse text-[12.5px]">
          <thead>
            <tr className="text-[10px] uppercase tracking-wide text-faint">
              <th className="border-b border-line px-2 py-1.5 text-left font-semibold">Позиция</th>
              <th className="border-b border-line px-2 py-1.5 text-right font-semibold">Факт, шт/мес</th>
              <th className="border-b border-line px-2 py-1.5 text-right font-semibold">План клиента, шт/мес</th>
              <th className="border-b border-line px-2 py-1.5 text-left font-semibold">Договорённость</th>
              <th className="border-b border-line px-2 py-1.5 text-right font-semibold">Подтв. объём, шт/мес</th>
              <th className="border-b border-line px-2 py-1.5 text-left font-semibold">Статус</th>
            </tr>
          </thead>
          <tbody>
            {skus.map((s, idx) => (
              <tr key={s.nm}>
                <td className="border-b border-line px-2 py-1.5 text-ink">{s.nm}</td>
                <td className="border-b border-line px-2 py-1.5 text-right tabular-nums text-ink">{s.hist}</td>
                <td className="border-b border-line px-2 py-1.5 text-right tabular-nums text-ink">{s.plan}</td>
                <td className="border-b border-line px-2 py-1.5 text-muted">{s.agr}</td>
                <td className="border-b border-line px-2 py-1.5 text-right">
                  {editing ? (
                    <input
                      type="number"
                      min={0}
                      value={s.conf}
                      onChange={(e) => setSkuConf(idx, parseInt(e.target.value, 10) || 0)}
                      className="w-[66px] rounded-md border border-accent bg-surface px-1.5 py-0.5 text-right text-[12.5px] font-bold tabular-nums text-ink"
                    />
                  ) : (
                    <span className="tabular-nums text-ink">
                      <b className="font-bold">{s.conf}</b> шт
                    </span>
                  )}
                </td>
                <td className="border-b border-line px-2 py-1.5">
                  <span className={`inline-block rounded px-1.5 py-0.5 text-[10px] font-bold ${SKU_TONE[s.stt].chip}`}>
                    {SKU_TONE[s.stt].label}
                  </span>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      <p className="mb-2.5 text-[11px] leading-relaxed text-faint">
        Факт — средняя продажа (прошлое) · План клиента — сколько он сам планирует брать
        (его производство/продажи) · Договорённость — насколько твёрдо (рамочный / устно / обсужд.) ·{" "}
        <b className="font-semibold text-muted">Подтв. объём</b> — итог для закупки (решение продавца). Всё в шт/мес.
      </p>

      <div className="mb-2.5 rounded-xl bg-blue-50 px-3 py-2.5 text-[12.5px] text-blue-600">
        → в план закупки следующей машины:{" "}
        <span className={`font-bold ${rollup.tone}`}>{rollup.text}</span>
      </div>

      <div className="flex flex-wrap items-center gap-2.5">
        {confirmed ? (
          <button
            type="button"
            disabled
            className="inline-flex cursor-default items-center gap-1.5 rounded-xl border border-emerald-600 bg-emerald-50 px-3 py-1.5 text-xs font-semibold text-emerald-600"
          >
            <Check size={14} /> Подтверждено на месяц
          </button>
        ) : (
          <button
            type="button"
            onClick={() => total > 0 && setConfirmed(true)}
            className="inline-flex items-center gap-1.5 rounded-xl bg-accent px-3 py-1.5 text-xs font-semibold text-white hover:bg-accent-ink disabled:opacity-60"
            disabled={total <= 0}
            title={total <= 0 ? "Объём 0 — сначала «Скорректировать» и укажите количество" : undefined}
          >
            <CheckCircle2 size={14} /> Подтвердить объём на месяц
          </button>
        )}
        <button
          type="button"
          onClick={() => setEditing((v) => !v)}
          className={`inline-flex items-center gap-1.5 rounded-xl border px-3 py-1.5 text-xs font-semibold ${
            editing
              ? "border-accent bg-accent text-white hover:bg-accent-ink"
              : "border-line bg-surface text-muted hover:bg-sunken"
          }`}
        >
          {editing ? <Check size={14} /> : <Pencil size={14} />} {editing ? "Готово" : "Скорректировать"}
        </button>
        <span className="text-[11px] text-faint">
          подтверждение уйдёт закупщику в план следующей машины
        </span>
      </div>
    </div>
  );
}

function Pillar({ label, value }: { label: string; value: string }) {
  return (
    <div className="rounded-xl bg-sunken p-3">
      <div className="mb-1 text-[11px] font-bold text-muted">{label}</div>
      <div className="text-xs leading-snug text-ink">{value}</div>
    </div>
  );
}

// ── Главный компонент ────────────────────────────────────────────────────────
export function RegularClients() {
  const [filter, setFilter] = useState<FilterKey>("all");
  const [openRow, setOpenRow] = useState<string | null>(null);

  const counts = useMemo(() => {
    const acc: Record<FilterKey, number> = { all: DEMO_CLIENTS.length, red: 0, amber: 0, green: 0 };
    for (const c of DEMO_CLIENTS) acc[c.st] += 1;
    return acc;
  }, []);

  const rows = useMemo(
    () => (filter === "all" ? DEMO_CLIENTS : DEMO_CLIENTS.filter((c) => c.st === filter)),
    [filter],
  );

  return (
    <main className="flex-1 overflow-auto p-6">
      <div className="mx-auto max-w-[1220px] space-y-4">
        {/* Заголовок */}
        <div>
          <h1 className="text-xl font-bold text-ink">Постоянные клиенты</h1>
          <p className="mt-1 text-sm text-muted">
            Удержание · периодичность заказов · перезаказ и допродажа · SALES-48 · BYN
          </p>
        </div>

        {/* KPI удержания */}
        <div className="grid grid-cols-2 gap-3 sm:grid-cols-3 lg:grid-cols-5">
          {RETENTION_KPIS.map((k) => (
            <div key={k.label} className="rounded-2xl bg-surface p-4 shadow-card">
              <div className="text-[11px] text-muted">{k.label}</div>
              <div className={`mt-1.5 text-xl font-bold tabular-nums ${k.valueTone ?? "text-ink"}`}>{k.value}</div>
              {k.delta && <div className={`mt-1 text-[11px] font-semibold ${k.deltaTone ?? "text-muted"}`}>{k.delta}</div>}
            </div>
          ))}
        </div>

        {/* Фильтр-статусы */}
        <div className="inline-flex flex-wrap gap-1 rounded-xl border border-line bg-surface p-1">
          {FILTERS.map((f) => {
            const on = filter === f.key;
            return (
              <button
                key={f.key}
                type="button"
                onClick={() => setFilter(f.key)}
                className={`inline-flex items-center gap-1.5 rounded-lg px-3.5 py-1.5 text-[13px] font-medium ${
                  on ? "bg-accent-soft text-accent-ink" : "text-muted hover:bg-sunken"
                }`}
              >
                {f.dot && <span className={`h-2 w-2 rounded-full ${f.dot}`} />}
                {f.label}
                <span className="text-[11px] opacity-70">{counts[f.key]}</span>
              </button>
            );
          })}
        </div>

        {/* Таблица аккаунтов */}
        <div className="overflow-x-auto rounded-2xl bg-surface shadow-card">
          <table className="w-full min-w-[1080px] border-collapse text-[13px]">
            <thead>
              <tr className="bg-sunken text-left text-[11px] uppercase tracking-wide text-faint">
                <th className="border-b border-line px-3.5 py-2.5 font-bold">Клиент</th>
                <th className="border-b border-line px-3.5 py-2.5 font-bold">Статус</th>
                <th className="border-b border-line px-3.5 py-2.5 font-bold">Последний заказ</th>
                <th className="border-b border-line px-3.5 py-2.5 font-bold">Следующий ожидается</th>
                <th className="border-b border-line px-3.5 py-2.5 text-right font-bold">Средний чек</th>
                <th className="border-b border-line px-3.5 py-2.5 font-bold">Тренд</th>
                <th className="border-b border-line px-3.5 py-2.5 font-bold">Подтв. объём</th>
                <th className="border-b border-line px-3.5 py-2.5 font-bold">Допродажа</th>
                <th className="border-b border-line px-3.5 py-2.5 text-right font-bold">Действие</th>
              </tr>
            </thead>
            <tbody>
              {rows.map((c) => {
                const open = openRow === c.nm;
                const tone = STATUS_TONE[c.st];
                return (
                  <RegularRowGroup
                    key={c.nm}
                    client={c}
                    open={open}
                    tone={tone}
                    onToggle={() => setOpenRow((cur) => (cur === c.nm ? null : c.nm))}
                  />
                );
              })}
            </tbody>
          </table>
        </div>

        {/* Пояснение к сортировке */}
        <div className="flex gap-2 rounded-xl border border-line bg-surface px-3.5 py-3 text-[12.5px] text-faint">
          <Info size={16} className="mt-0.5 shrink-0 text-muted" />
          <span>
            Сортировка по умолчанию — <b className="font-semibold text-ink">«кому звонить раньше»</b> (просрочка → пора → в цикле).
            Статус считается из истории: периодичность = медиана интервалов между заказами, ожидаемая дата = последний
            заказ + интервал. Просрочка → авто-эскалация РОПу.
          </span>
        </div>

        {/* Постпродажный хвост */}
        <div className="pt-2">
          <h2 className="mb-3 text-[15px] font-bold text-ink">
            Что происходит после продажи (won) — чтобы не забыть
          </h2>
          <div className="flex flex-wrap items-stretch gap-2.5">
            {FLOW.map((n, idx) => (
              <div key={n.title} className="flex flex-1 items-center gap-2.5">
                <div className="min-w-[200px] flex-1 rounded-xl border border-line bg-surface p-3.5 shadow-card">
                  <div className="flex items-center gap-2 text-[13px] font-bold text-ink">
                    {n.icon}
                    <span>{n.title}</span>
                    {n.tag && (
                      <span className="rounded bg-sunken px-1.5 py-0.5 text-[10px] font-bold text-muted">{n.tag}</span>
                    )}
                  </div>
                  <div className="mt-1.5 text-xs leading-relaxed text-muted">{n.body}</div>
                </div>
                {idx < FLOW.length - 1 && <ArrowRight size={20} className="shrink-0 text-faint" />}
              </div>
            ))}
          </div>
        </div>
      </div>
    </main>
  );
}

// ── Группа: строка клиента + раскрываемая деталь ─────────────────────────────
function RegularRowGroup({
  client,
  open,
  tone,
  onToggle,
}: {
  client: Client;
  open: boolean;
  tone: { dot: string; chip: string; label: string };
  onToggle: () => void;
}) {
  const actions =
    client.st === "red" ? (
      <>
        <button
          type="button"
          className="inline-flex items-center gap-1 rounded-lg bg-accent px-2.5 py-1.5 text-xs font-semibold text-white hover:bg-accent-ink"
        >
          <Phone size={13} /> Связаться
        </button>
        <button
          type="button"
          className="inline-flex items-center gap-1 rounded-lg border border-line bg-surface px-2.5 py-1.5 text-xs font-semibold text-muted hover:bg-sunken"
        >
          <PhoneForwarded size={13} /> Передать РОПу
        </button>
      </>
    ) : client.st === "amber" ? (
      <>
        <button
          type="button"
          className="inline-flex items-center gap-1 rounded-lg bg-accent px-2.5 py-1.5 text-xs font-semibold text-white hover:bg-accent-ink"
        >
          <Repeat size={13} /> Перезаказ
        </button>
        <button
          type="button"
          className="inline-flex items-center gap-1 rounded-lg border border-line bg-surface px-2.5 py-1.5 text-xs font-semibold text-muted hover:bg-sunken"
        >
          <Phone size={13} />
        </button>
      </>
    ) : (
      <button
        type="button"
        className="inline-flex items-center gap-1 rounded-lg border border-line bg-surface px-2.5 py-1.5 text-xs font-semibold text-muted hover:bg-sunken"
      >
        <Repeat size={13} /> Перезаказ
      </button>
    );

  return (
    <>
      <tr className="cursor-pointer hover:bg-sunken" onClick={onToggle}>
        <td className="border-b border-line px-3.5 py-3">
          <div className="flex items-center gap-2.5">
            <ChevronRight size={14} className={`shrink-0 text-faint transition-transform ${open ? "rotate-90" : ""}`} />
            <span
              className="flex h-9 w-9 shrink-0 items-center justify-center rounded-full text-[13px] font-bold text-white"
              style={{ backgroundColor: client.color }}
            >
              {client.av}
            </span>
            <div>
              <div className="font-semibold text-ink">{client.nm}</div>
              <div className="text-[11.5px] text-faint">{client.sub}</div>
            </div>
          </div>
        </td>
        <td className="border-b border-line px-3.5 py-3">
          <span className={`inline-flex items-center gap-1.5 rounded-full px-2.5 py-0.5 text-xs font-semibold ${tone.chip}`}>
            <span className={`h-1.5 w-1.5 rounded-full ${tone.dot}`} />
            {client.stt}
          </span>
        </td>
        <td className="border-b border-line px-3.5 py-3 text-ink">
          {client.last}
          <div className="text-[11px] text-faint">интервал {client.int}</div>
        </td>
        <td className="border-b border-line px-3.5 py-3">
          <span className={`font-semibold ${NEXT_TONE[client.nd]}`}>{client.next}</span>
        </td>
        <td className="border-b border-line px-3.5 py-3 text-right font-bold tabular-nums text-money">
          {formatByn(client.avg)}
        </td>
        <td className="border-b border-line px-3.5 py-3">
          <TrendCell dir={client.trendDir} label={client.trend} />
        </td>
        <td className="border-b border-line px-3.5 py-3">
          <ConfBadgePill client={client} />
        </td>
        <td className="border-b border-line px-3.5 py-3">
          {client.upsell === "—" ? (
            <span className="text-[11px] text-faint">—</span>
          ) : (
            <span className="inline-flex items-start gap-1 text-xs text-emerald-600">
              <Lightbulb size={13} className="mt-0.5 shrink-0" /> {client.upsell}
            </span>
          )}
        </td>
        <td className="border-b border-line px-3.5 py-3" onClick={(e) => e.stopPropagation()}>
          <div className="flex flex-wrap justify-end gap-1.5">{actions}</div>
        </td>
      </tr>
      {open && (
        <tr>
          <td colSpan={9} className="bg-sunken px-3.5 pb-3.5 pt-0">
            <ConfirmPanel client={client} />
          </td>
        </tr>
      )}
    </>
  );
}
