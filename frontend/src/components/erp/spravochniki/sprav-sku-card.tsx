"use client";

import { useState } from "react";
import { Package, Wallet } from "lucide-react";

import { formatByn } from "@/lib/format";
import { SourceTag } from "@/components/source-tag";
import { changedFields } from "@/lib/reference-data";
import type { FieldProvenance, GroupInherited, SkuBatchRow, SkuCard } from "@/lib/reference-data";
import { provenanceCounts } from "@/lib/spravochniki-card";

import { ProvenanceBadge } from "./provenance-badge";

// ── Примитивы карточки (повторяют дизайн макета nomenclature-card-preview.html) ──

/** Цветной бейдж-пилюля. Тон → пары токенов (в тёмной теме фоны приглушаются глобально). */
function Badge({
  children,
  tone = "mut",
  title,
}: {
  children: React.ReactNode;
  tone?: "ok" | "warn" | "bad" | "info" | "violet" | "mut" | "mono";
  title?: string;
}) {
  const cls: Record<string, string> = {
    ok: "bg-emerald-50 text-emerald-700",
    warn: "bg-amber-50 text-amber-700",
    bad: "bg-red-50 text-red-600",
    info: "bg-blue-50 text-blue-700",
    violet: "bg-violet-50 text-violet-700",
    mut: "bg-sunken text-muted",
    mono: "bg-sunken text-muted font-mono tabular-nums",
  };
  return (
    <span
      title={title}
      className={`inline-flex items-center gap-1 whitespace-nowrap rounded-full px-2 py-0.5 text-[11px] font-semibold ${cls[tone]}`}
    >
      {children}
    </span>
  );
}

/** Маркер «↑ из группы» (наследование) — рядом с подписью поля. */
function InheritMark({ title }: { title?: string }) {
  return (
    <span
      title={title}
      className="inline-flex shrink-0 cursor-help items-center gap-1 rounded-full bg-violet-50 px-1.5 py-0.5 text-[10.5px] font-semibold text-violet-700"
    >
      ↑ из группы
    </span>
  );
}

/** Маркер «задано здесь» (значение локальное, не унаследовано). */
function LocalMark() {
  return (
    <span className="inline-flex shrink-0 items-center gap-1 rounded-full bg-sunken px-1.5 py-0.5 text-[10.5px] font-semibold text-faint">
      задано здесь
    </span>
  );
}

/** Поле «подпись (+ маркер) → значение». unset=true — курсивное «нет данных».
 *  `prov` — происхождение поля (M2): источник+дата справа от подписи (если нет явного `mark`). */
function Field({
  label,
  value,
  mark,
  prov,
  mono = false,
  unset = false,
  full = false,
}: {
  label: React.ReactNode;
  value: React.ReactNode;
  mark?: React.ReactNode;
  prov?: FieldProvenance;
  mono?: boolean;
  unset?: boolean;
  full?: boolean;
}) {
  return (
    <div className={full ? "sm:col-span-2" : ""}>
      <div className="flex items-center gap-2">
        <p className="text-[11.5px] text-muted">{label}</p>
        {mark ?? <ProvenanceBadge prov={prov} />}
      </div>
      <div
        className={`mt-0.5 text-sm ${mono ? "font-mono tabular-nums" : ""} ${
          unset ? "italic text-faint" : "font-medium text-ink"
        }`}
      >
        {value}
      </div>
    </div>
  );
}

/** KPI-плитка (полоса под шапкой и внутри табов). */
function Kpi({
  icon,
  label,
  big,
  sub,
  money = false,
  warn = false,
  bigClass = "",
}: {
  icon?: string;
  label: string;
  big: React.ReactNode;
  sub?: React.ReactNode;
  money?: boolean;
  warn?: boolean;
  bigClass?: string;
}) {
  return (
    <div className="bg-surface px-3.5 py-3">
      <div className="flex items-center gap-1.5 text-[11px] text-muted">
        {icon && <span aria-hidden>{icon}</span>}
        {label}
      </div>
      <div
        className={`mt-0.5 text-lg font-extrabold tabular-nums ${bigClass} ${
          money ? "text-money" : warn ? "text-amber-600" : "text-ink"
        }`}
      >
        {big}
      </div>
      {sub && <div className="mt-px text-[11px] text-faint">{sub}</div>}
    </div>
  );
}

/** Карточка-секция. */
function Card({ children, className = "" }: { children: React.ReactNode; className?: string }) {
  return (
    <div className={`rounded-2xl bg-surface p-4 shadow-card ${className}`}>{children}</div>
  );
}

/** Заголовок-надпись над блоком. */
function Eyebrow({ children }: { children: React.ReactNode }) {
  return (
    <p className="text-[11px] font-semibold uppercase tracking-wide text-faint">{children}</p>
  );
}

/** Сворачиваемая группа (нативный details — без JS-состояния). */
function Collapsible({
  summary,
  count,
  children,
}: {
  summary: string;
  count?: number;
  children: React.ReactNode;
}) {
  return (
    <details className="mt-3 rounded-xl bg-sunken">
      <summary className="flex cursor-pointer list-none items-center gap-2 px-3.5 py-2.5 text-[13.5px] font-semibold text-ink">
        <span className="text-faint">▸</span>
        {summary}
        {count != null && <Badge tone="mut">{count}</Badge>}
      </summary>
      <div className="px-3.5 pb-3.5 pt-0.5">{children}</div>
    </details>
  );
}

/** Честный пустой блок таба — данные появятся после интеграции (не выдумываем числа). */
function EmptyState({ title, hint }: { title: string; hint: string }) {
  return (
    <Card>
      <p className="text-sm font-medium text-muted">{title}</p>
      <p className="mt-2 text-[12px] text-faint">{hint}</p>
    </Card>
  );
}

/** Кнопка-таб. */
function TabBtn({
  active,
  onClick,
  children,
}: {
  active: boolean;
  onClick: () => void;
  children: React.ReactNode;
}) {
  return (
    <button
      onClick={onClick}
      className={`rounded-full px-3 py-1.5 text-[13px] font-semibold transition ${
        active ? "bg-brand text-white" : "text-muted hover:bg-sunken"
      }`}
    >
      {children}
    </button>
  );
}

/** Русское склонение «склад» по числу: 1 склад, 2 склада, 5 складов. */
function skladPlural(n: number): string {
  const mod10 = n % 10;
  const mod100 = n % 100;
  if (mod10 === 1 && mod100 !== 11) return "склад";
  if (mod10 >= 2 && mod10 <= 4 && (mod100 < 10 || mod100 >= 20)) return "склада";
  return "складов";
}

/** ISO-дата (YYYY-MM-DD) → ДД.ММ.ГГГГ; null/пусто → «—». */
function fmtDate(iso: string | null): string {
  if (!iso) return "—";
  const [y, m, d] = iso.split("-");
  return d && m && y ? `${d}.${m}.${y}` : iso;
}

/** FEFO-бейдж по сроку годности партии: просрочено / <1 года / ок / без срока. */
function FefoBadge({ fefo, days }: { fefo: SkuBatchRow["fefo"]; days: number | null }) {
  if (fefo === "none") return <Badge tone="mut">без срока</Badge>;
  if (fefo === "expired")
    return <Badge tone="bad" title="Срок годности истёк">просрочено</Badge>;
  if (fefo === "warn")
    return (
      <Badge tone="warn" title="Менее года до конца срока — отгружать первой (FEFO)">
        ⚠ &lt; года{days != null && days >= 0 ? ` · ${days} дн` : ""}
      </Badge>
    );
  return <Badge tone="ok">ок</Badge>;
}

/** Значение JSON-атрибута → строка (объект/массив — компактный JSON). */
function attrValue(v: unknown): string {
  if (v == null) return "—";
  if (typeof v === "object") return JSON.stringify(v);
  return String(v);
}

/** Поле свободного атрибута (своё ∨ от группы). Пусто → честное «нет данных». */
function AttrField({ label, attr }: { label: string; attr?: GroupInherited }) {
  if (!attr?.value) return <Field label={label} value="нет данных" unset />;
  return (
    <Field
      label={label}
      value={attr.value}
      mark={
        attr.source === "group" ? (
          <InheritMark title={`По умолч. группы «${attr.group_name ?? ""}»`} />
        ) : (
          <LocalMark />
        )
      }
    />
  );
}

const TABS = [
  { id: "overview", label: "Обзор" },
  { id: "specs", label: "Характеристики" },
  { id: "procure", label: "Закупка и партии" },
  { id: "wh", label: "Склад" },
  { id: "price", label: "Цены и маржа 🔒" },
  { id: "analytics", label: "Аналитика" },
  { id: "history", label: "История" },
] as const;
type TabId = (typeof TABS)[number]["id"];

// Ключи attributes с отдельным рендером (производитель/упаковка/габариты — свои Field'ы с
// наследованием; страна — effective_country). Исключаем их из таблицы JSONB-хвоста, чтобы не дублить.
const DEDICATED_ATTR_KEYS = new Set([
  "Производитель", "Марка", "Бренд", "Импортёр",
  "Кол-во в коробке", "Габариты", "Объём",
  "Страна происхождения", "Страна",
]);

export function SpravSkuCard({ card }: { card: SkuCard }) {
  const [tab, setTab] = useState<TabId>("overview");

  const prov = card.provenance ?? {};
  const counts = provenanceCounts(prov);
  // JSONB-хвост для таблицы тех.характеристик — БЕЗ ключей, у которых есть отдельное поле
  // (производитель/упаковка/габариты — отдельные Field'ы с наследованием; страна — effective_country).
  const attrs = Object.entries(card.attributes ?? {}).filter(([k]) => !DEDICATED_ATTR_KEYS.has(k));
  const eff = card.effective_tnved ?? {
    code: card.tnved_code ?? null,
    source: card.tnved_code ? ("own" as const) : null,
    group_code: null,
    group_name: null,
  };
  const rates = card.tnved_rates;
  // Наследуемые «общие данные группы»: страна (своё ∨ от группы) + НДС по умолч. группы.
  // (Ед.изм. не наследуется в карточку: у Sku она задана всегда — см. поле ниже.)
  const effCountry = card.effective_country;
  const groupVat = card.group_vat;
  const groupPath = card.group_path ?? [];
  const sync = card.sync;
  const stock = card.stock;
  const batches = card.batches;
  // Маржа от себестоимости (контроль валовой прибыли) — null, если нет цены/себеса
  // или цена 0 (защита от деления на ноль → не показываем -Infinity%).
  const margin =
    stock?.price != null && stock.price > 0 && stock?.cost != null
      ? Math.round(((stock.price - stock.cost) / stock.price) * 100)
      : null;

  // Эффективные атрибуты (своё ∨ от группы) — backend отдаёт только непустые ключи.
  const effAttrs = card.effective_attrs ?? {};
  // «Производительские» поля для блока «Сведения о производителе» (таб Обзор) — по известным
  // ключам; берём эффективное значение (унаследованное от группы помечается «↑ из группы»).
  const makerKeys = ["Производитель", "Марка", "Бренд", "Импортёр"];
  const makerAttrs = makerKeys
    .map((k) => [k, effAttrs[k]] as const)
    .filter(([, v]) => v?.value != null && v.value !== "");

  // Заполненность карточки — доля непустых «горячих» полей (демо-метрика полноты golden record).
  const fillChecks = [
    card.title,
    card.unit,
    card.weight_kg,
    eff.code,
    card.shelf_life_days,
    makerAttrs.length > 0 ? "x" : null,
  ];
  const filled = fillChecks.filter((v) => v != null && v !== "").length;
  const fillPct = Math.round((filled / fillChecks.length) * 100);

  return (
    <div className="flex-1 overflow-y-auto bg-canvas p-6">
      <div className="mx-auto max-w-5xl space-y-4">
        {/* ──────── ШАПКА-СВОДКА ──────── */}
        <Card>
          <div className="flex flex-wrap items-start gap-4 sm:flex-nowrap">
            <div className="flex h-[88px] w-[88px] shrink-0 items-center justify-center rounded-2xl border border-line bg-gradient-to-br from-brand/10 to-violet-500/10 text-4xl">
              <Package className="h-9 w-9 text-faint" />
            </div>
            <div className="min-w-0 flex-1">
              <h1 className="text-lg font-extrabold leading-tight text-ink">{card.title}</h1>
              <div className="mt-2 flex flex-wrap items-center gap-1.5">
                <Badge tone="info" title="Мастер-данные (golden record)">
                  ★ эталон
                </Badge>
                {card.is_active ? (
                  <Badge tone="ok">Активна</Badge>
                ) : (
                  <Badge tone="mut">В архиве</Badge>
                )}
                <Badge tone="mono">{card.code}</Badge>
                <SourceTag
                  entity="Номенклатура"
                  source={sync ? (sync.origin === "1c" ? "mdm/1c" : sync.origin) : "erp"}
                />
                {sync?.last_synced_at && (
                  <Badge tone="violet" title={`Статус синка: ${sync.state}`}>
                    ↧ {sync.last_synced_at.slice(0, 16).replace("T", " ")}
                  </Badge>
                )}
                <Badge tone="mut">🤖 в каталоге AI</Badge>
              </div>
              <p className="mt-2 text-[12.5px] text-muted">
                Группа:{" "}
                {groupPath.length > 0 ? (
                  groupPath.map((g, i) => (
                    <span key={g.code}>
                      {i > 0 && " › "}
                      <span className="text-brand">{g.name}</span>
                    </span>
                  ))
                ) : (
                  <span className="italic text-faint">не задана</span>
                )}
                {" · "}Ед.: {card.unit ?? "—"}
              </p>
            </div>
            <div className="shrink-0">
              <Badge tone="mut" title="Витрина золотой записи: правка — фаза 2">
                🔒 read-витрина
              </Badge>
            </div>
          </div>

          {/* KPI-полоса */}
          <div className="mt-4 grid grid-cols-2 gap-px overflow-hidden rounded-xl border border-line bg-line sm:grid-cols-3 lg:grid-cols-5">
            <Kpi
              icon="📦"
              label="Остаток"
              big={
                stock ? (
                  <>
                    {stock.total_available} <span className="text-xs font-semibold text-muted">{card.unit ?? "шт"}</span>
                  </>
                ) : (
                  <span className="italic text-faint">нет данных</span>
                )
              }
              sub={stock ? `резерв ${stock.total_reserved} · истина — 1С` : "истина остатка — 1С"}
            />
            <Kpi
              icon="🗄"
              label="Где лежит"
              big={
                stock && stock.rows.length > 0 ? (
                  stock.rows.length === 1
                    ? stock.rows[0].warehouse
                    : `${stock.rows.length} ${skladPlural(stock.rows.length)}`
                ) : (
                  <span className="italic text-faint">нет данных</span>
                )
              }
              bigClass="text-[15px]"
              sub={stock ? "склады из 1С" : "WMS / инвентаризация"}
            />
            <Kpi
              icon="⏳"
              label="Срок годности"
              big={
                card.shelf_life_days != null ? (
                  `${card.shelf_life_days} дн.`
                ) : (
                  <span className="italic text-faint">нет данных</span>
                )
              }
              bigClass="text-[15px]"
              sub="по партии"
            />
            <Kpi
              icon="💰"
              label="Landed cost"
              money={card.landed_cost != null}
              big={
                card.landed_cost != null ? (
                  formatByn(card.landed_cost)
                ) : (
                  <span className="italic text-faint">нет расчёта</span>
                )
              }
              bigClass="text-[15px]"
              sub="из закупок (выкуп → машина)"
            />
            <Kpi
              icon="🌐"
              label="ТН ВЭД / пошлина"
              big={eff.code ?? <span className="italic text-faint">нет кода</span>}
              bigClass="text-[15px]"
              sub={
                rates
                  ? `пошлина ${rates.duty_rate}%${eff.source === "group" ? " · от группы" : ""}`
                  : eff.source === "group"
                    ? "унаследован от группы"
                    : "—"
              }
            />
          </div>

          {/* Табы */}
          <div className="mt-4 flex flex-wrap gap-1.5 border-t border-line pt-3.5">
            {TABS.map((t) => (
              <TabBtn key={t.id} active={tab === t.id} onClick={() => setTab(t.id)}>
                {t.label}
              </TabBtn>
            ))}
          </div>
        </Card>

        {/* ──────── ТАБ: ОБЗОР ──────── */}
        {tab === "overview" && (
          <div className="grid gap-4 lg:grid-cols-[minmax(0,1fr)_300px]">
            <div className="space-y-4">
              <Card>
                <div className="flex items-center justify-between gap-2">
                  <Eyebrow>Идентификация и наименования</Eyebrow>
                  {counts.length > 0 && (
                    <p className="text-[11px] text-faint">справа от поля — источник значения</p>
                  )}
                </div>
                <div className="mt-3 grid gap-3 sm:grid-cols-2">
                  <Field full label="Рабочее наименование" value={card.title} prov={prov.title} />
                  <Field label="Код / артикул" value={card.code} mono prov={prov.code} />
                  {/* Ед.изм. у товара задана всегда (default «шт») — показываем своё значение;
                      дефолт группы (effective_unit) применяется только к НОВЫМ товарам, не сюда. */}
                  <Field label="Ед. измерения" value={card.unit ?? "—"} prov={prov.unit} />
                  <Field
                    label="Страна происхождения"
                    value={effCountry?.value ?? "нет данных"}
                    unset={!effCountry?.value}
                    mark={
                      effCountry?.source === "group" ? (
                        <InheritMark title={`Страна по умолч. группы «${effCountry.group_name ?? ""}»`} />
                      ) : undefined
                    }
                  />
                  {groupVat?.value && (
                    <Field
                      label="Код НДС"
                      value={groupVat.rate != null ? `${groupVat.value} · ${groupVat.rate}%` : groupVat.value}
                      mark={
                        groupVat.source === "group" ? (
                          <InheritMark title={`Ставка НДС по умолч. группы «${groupVat.group_name ?? ""}»`} />
                        ) : (
                          <LocalMark />
                        )
                      }
                    />
                  )}
                  <Field
                    label="Вес, кг"
                    value={card.weight_kg != null ? String(card.weight_kg) : "нет данных"}
                    unset={card.weight_kg == null}
                    mono={card.weight_kg != null}
                    prov={prov.weight_kg}
                  />
                  <Field
                    label="Срок годности, дн."
                    value={card.shelf_life_days != null ? String(card.shelf_life_days) : "нет данных"}
                    unset={card.shelf_life_days == null}
                    mono={card.shelf_life_days != null}
                    prov={prov.shelf_life_days}
                  />
                </div>

                <Collapsible summary="Сведения о производителе">
                  {makerAttrs.length > 0 ? (
                    <div className="grid gap-3 sm:grid-cols-2">
                      {makerAttrs.map(([k, v]) => (
                        <Field
                          key={k}
                          label={k}
                          value={v.value}
                          mark={
                            v.source === "group" ? (
                              <InheritMark title={`По умолч. группы «${v.group_name ?? ""}»`} />
                            ) : (
                              <LocalMark />
                            )
                          }
                        />
                      ))}
                    </div>
                  ) : (
                    <p className="text-[12px] text-faint">
                      Производитель, марка, импортёр появятся, когда будут заполнены на товаре или
                      унаследованы от группы. Сейчас не заданы.
                    </p>
                  )}
                </Collapsible>
                <Collapsible summary="Описание и файлы">
                  <p className="text-[12px] text-faint">
                    Текстовое описание и вложения (паспорт, datasheet) не заданы.
                  </p>
                </Collapsible>
              </Card>
            </div>

            {/* sidebar */}
            <div className="space-y-4">
              <Card>
                <Eyebrow>Себестоимость партии</Eyebrow>
                {card.landed_cost != null ? (
                  <>
                    <p className="mt-2 flex items-center gap-1.5 text-2xl font-bold text-money">
                      <Wallet className="h-5 w-5" />
                      {formatByn(card.landed_cost)}
                    </p>
                    <p className="mt-2 text-[12px] text-muted">
                      Landed cost последней партии — из закупок. Видна продавцу в момент сделки для
                      контроля маржи.
                    </p>
                  </>
                ) : (
                  <>
                    <p className="mt-2 text-sm font-medium text-muted">Нет расчёта</p>
                    <p className="mt-2 text-[12px] text-faint">
                      Себестоимость появится после расчёта партии в закупках. Отсутствие не маскируем
                      нулём — пока расчёта нет, поле пустое.
                    </p>
                  </>
                )}
              </Card>

              <Card>
                <Eyebrow>Золотая запись</Eyebrow>
                <p className="mt-2 text-[13.5px] font-semibold text-ink">★ Эталон в ERP</p>
                <div className="mt-2 space-y-1.5 text-[13px]">
                  <div className="flex items-center justify-between">
                    <span className="text-muted">ERP-native</span>
                    <Badge tone="ok">эталон</Badge>
                  </div>
                  <div className="flex items-center justify-between">
                    <span className="text-muted">Связь с 1С</span>
                    {sync ? <Badge tone="violet">{sync.state}</Badge> : <Badge tone="mut">нет</Badge>}
                  </div>
                  <div className="flex items-center justify-between">
                    <span className="text-muted">Источник истины склада</span>
                    <Badge tone="violet">1С</Badge>
                  </div>
                </div>
                <p className="mt-2 text-[11px] text-faint">
                  Мастер-данные ведутся в ERP, склад/остатки — из 1С.
                </p>
              </Card>

              {counts.length > 0 && (
                <Card>
                  <Eyebrow>Происхождение полей</Eyebrow>
                  <div className="mt-3 space-y-1.5 text-[12px]">
                    {counts.map(({ source, meta, count }) => (
                      <div key={source} className="flex items-center justify-between">
                        <span className="flex items-center gap-1.5 text-muted">
                          <span aria-hidden>{meta.icon}</span>
                          {meta.label}
                        </span>
                        <span className="font-semibold text-ink">{count}</span>
                      </div>
                    ))}
                  </div>
                  <p className="mt-3 border-t border-line pt-3 text-[11px] text-faint">
                    Источник известен по каждому полю — синк из 1С не затирает закреплённые правилами.
                  </p>
                </Card>
              )}

              <Card>
                <Eyebrow>Заполненность</Eyebrow>
                <div className="mt-2 flex items-center justify-between text-[13px]">
                  <span className="text-muted">Полнота карточки</span>
                  <span className="font-bold tabular-nums text-money">{fillPct}%</span>
                </div>
                <div className="mt-1 h-2 overflow-hidden rounded-full bg-sunken">
                  <div className="h-full rounded-full bg-money" style={{ width: `${fillPct}%` }} />
                </div>
                <div className="mt-2.5 flex flex-wrap gap-1.5">
                  <Badge tone={eff.code ? "ok" : "warn"}>ТН ВЭД {eff.code ? "✓" : "⚠"}</Badge>
                  <Badge tone={card.weight_kg != null ? "ok" : "warn"}>Вес {card.weight_kg != null ? "✓" : "⚠"}</Badge>
                  <Badge tone={makerAttrs.length > 0 ? "ok" : "warn"}>Производитель {makerAttrs.length > 0 ? "✓" : "⚠"}</Badge>
                </div>
                <p className="mt-2.5 text-[11px] text-faint">
                  Полнота по «горячим» полям витрины. Обязательность задаёт группа (наследуется).
                </p>
              </Card>
            </div>
          </div>
        )}

        {/* ──────── ТАБ: ХАРАКТЕРИСТИКИ ──────── */}
        {tab === "specs" && (
          <div className="grid gap-4 lg:grid-cols-[minmax(0,1fr)_300px]">
            <div className="space-y-4">
              <Card>
                <p className="text-[13.5px] font-bold text-ink">Физические · упаковка</p>
                <div className="mt-3 grid gap-3 sm:grid-cols-2">
                  <Field
                    label="Вес, кг"
                    value={card.weight_kg != null ? String(card.weight_kg) : "нет данных"}
                    unset={card.weight_kg == null}
                    mono={card.weight_kg != null}
                    prov={prov.weight_kg}
                  />
                  <AttrField label="Габариты (Д×Ш×В)" attr={effAttrs["Габариты"]} />
                  <Field
                    label="Объём, м³"
                    value={card.volume_m3 != null ? String(card.volume_m3) : "нет данных"}
                    unset={card.volume_m3 == null}
                    mono={card.volume_m3 != null}
                    prov={prov.volume_m3}
                  />
                  <AttrField label="Кол-во в коробке" attr={effAttrs["Кол-во в коробке"]} />
                </div>

                <p className="mt-5 text-[13.5px] font-bold text-ink">Учёт и налоги</p>
                <div className="mt-3 grid gap-3 sm:grid-cols-2">
                  <Field
                    label="Код ТН ВЭД"
                    value={eff.code ?? "нет кода"}
                    unset={!eff.code}
                    mono={!!eff.code}
                    mark={
                      eff.code
                        ? eff.source === "group"
                          ? <InheritMark title={`Унаследован от группы «${eff.group_name ?? ""}»`} />
                          : <LocalMark />
                        : undefined
                    }
                  />
                  <Field
                    label="Ставка пошлины"
                    value={rates ? `${rates.duty_rate}%` : "—"}
                    unset={!rates}
                    mono={!!rates}
                    mark={
                      rates ? (
                        <span className="text-[11px] text-faint">📥 по коду ТН ВЭД</span>
                      ) : undefined
                    }
                  />
                  <Field
                    label="Ставка НДС"
                    value={rates?.vat_rate != null ? `${rates.vat_rate}%` : "—"}
                    unset={rates?.vat_rate == null}
                    mono={rates?.vat_rate != null}
                    mark={
                      rates?.vat_code ? (
                        <span className="text-[11px] text-faint">📥 {rates.vat_code}</span>
                      ) : undefined
                    }
                  />
                  <Field
                    label="Срок хранения, дн."
                    value={card.shelf_life_days != null ? String(card.shelf_life_days) : "нет данных"}
                    unset={card.shelf_life_days == null}
                    mono={card.shelf_life_days != null}
                  />
                </div>
                {eff.source === "group" && eff.group_name && (
                  <p className="mt-3 rounded-xl bg-violet-50 px-3 py-2 text-[12px] text-violet-700">
                    Код ТН ВЭД унаследован от группы «{eff.group_name}» — можно переопределить на
                    товаре. Пошлина/НДС резолвятся по этому коду на дату оформления.
                  </p>
                )}
              </Card>
            </div>

            <Card>
              <div className="flex items-center justify-between gap-2">
                <p className="text-[13.5px] font-bold text-ink">⚙️ Технические характеристики</p>
                <Badge tone="mut">JSONB</Badge>
              </div>
              <p className="mt-1 text-[12px] text-muted">
                «Горячие» параметры — в полях слева; остальное — таблица «параметр · значение».
              </p>
              {attrs.length === 0 ? (
                <p className="mt-3 text-sm italic text-faint">Характеристик не задано</p>
              ) : (
                <table className="mt-2 w-full border-collapse text-[13px]">
                  <tbody className="divide-y divide-line">
                    {attrs.map(([k, v]) => (
                      <tr key={k}>
                        <td className="py-1.5 pr-3 align-top text-muted">{k}</td>
                        <td className="py-1.5 text-right font-medium text-ink">{attrValue(v)}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              )}
            </Card>
          </div>
        )}

        {/* ──────── ТАБ: ЗАКУПКА И ПАРТИИ ──────── */}
        {tab === "procure" &&
          (batches && batches.rows.length > 0 ? (
            <Card>
              <div className="flex flex-wrap items-center justify-between gap-2">
                <p className="text-[13.5px] font-bold text-ink">🚚 Партии закупки (FEFO)</p>
                <div className="flex items-center gap-2">
                  <Badge tone="mut">всего {batches.total_qty} {card.unit ?? "шт"}</Badge>
                  {batches.nearest_expiry && (
                    <Badge tone="violet" title="Ближайший срок «годен до» среди партий">
                      ближайший срок · {fmtDate(batches.nearest_expiry)}
                    </Badge>
                  )}
                </div>
              </div>
              <p className="mt-1 text-[12px] text-muted">
                Откуда приехало и до какого срока годен. FEFO — раньше истекающие отгружаем
                первыми. Себестоимость партии (landed cost) — вход маржи.
              </p>
              <div className="mt-2 overflow-x-auto">
                <table className="w-full border-collapse text-[13px]">
                  <thead>
                    <tr className="text-left text-[10.5px] uppercase tracking-wide text-faint">
                      <th className="py-2 pr-3 font-semibold">Партия</th>
                      <th className="py-2 pr-3 font-semibold">Поставщик</th>
                      <th className="py-2 pr-3 font-semibold">Склад</th>
                      <th className="py-2 pr-3 text-right font-semibold">Кол-во</th>
                      <th className="py-2 pr-3 font-semibold">Произв.</th>
                      <th className="py-2 pr-3 font-semibold">Годен до</th>
                      <th className="py-2 pr-3 text-right font-semibold">Себес/ед</th>
                      <th className="py-2 font-semibold">FEFO</th>
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-line">
                    {batches.rows.map((b: SkuBatchRow) => (
                      <tr key={b.lot_no}>
                        <td className="py-2 pr-3 font-mono text-[12px] text-ink">
                          {b.lot_no}
                          {b.external_ref && (
                            <span className="block text-[10.5px] font-sans text-faint">
                              {b.external_ref}
                            </span>
                          )}
                        </td>
                        <td className="py-2 pr-3 text-muted">{b.supplier ?? "—"}</td>
                        <td className="py-2 pr-3 text-muted">{b.warehouse ?? "—"}</td>
                        <td className="py-2 pr-3 text-right tabular-nums text-ink">
                          {b.qty} {card.unit ?? "шт"}
                        </td>
                        <td className="py-2 pr-3 tabular-nums text-muted">{fmtDate(b.mfg_date)}</td>
                        <td className="py-2 pr-3 tabular-nums text-muted">
                          {fmtDate(b.expiry_date)}
                        </td>
                        <td className="py-2 pr-3 text-right tabular-nums text-ink">
                          {b.unit_landed_cost != null ? formatByn(b.unit_landed_cost) : "—"}
                        </td>
                        <td className="py-2">
                          <FefoBadge fefo={b.fefo} days={b.days_to_expiry} />
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
              <p className="mt-3 border-t border-line pt-3 text-[12px] text-faint">
                Себестоимость «—» — разбор landed cost (инвойс+фрахт+пошлина+брокер) появится
                после расчёта по методике цены. Машина/технология тестирования/фото приёмки —
                после связи партии с воронкой закупок (ZAK).
              </p>
            </Card>
          ) : (
            <EmptyState
              title="🚚 Партии закупки и landed cost"
              hint="Партий по этому товару нет. Поставщик, машина, технология тестирования, приёмка, годен до и разбор себестоимости появятся после прихода партии из закупок (ZAK) или синка из 1С. Числа не выдумываем."
            />
          ))}

        {/* ──────── ТАБ: СКЛАД ──────── */}
        {tab === "wh" && (
          stock && stock.rows.length > 0 ? (
            <Card>
              <div className="flex items-center justify-between gap-2">
                <p className="text-[13.5px] font-bold text-ink">🗄 Размещение и остатки</p>
                <Badge tone="violet">истина — 1С</Badge>
              </div>
              <table className="mt-2 w-full border-collapse text-[13px]">
                <thead>
                  <tr className="text-left text-[10.5px] uppercase tracking-wide text-faint">
                    <th className="py-2 pr-3 font-semibold">Склад</th>
                    <th className="py-2 pr-3 text-right font-semibold">Доступно</th>
                    <th className="py-2 pr-3 text-right font-semibold">Резерв</th>
                    <th className="py-2 text-right font-semibold">Прогноз</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-line">
                  {stock.rows.map((r) => (
                    <tr key={r.warehouse}>
                      <td className="py-2 pr-3 text-ink">{r.warehouse}</td>
                      <td className="py-2 pr-3 text-right font-medium tabular-nums text-ink">
                        {r.qty_available} {card.unit ?? "шт"}
                      </td>
                      <td className="py-2 pr-3 text-right tabular-nums text-muted">{r.qty_reserved}</td>
                      <td className="py-2 text-right tabular-nums text-muted">{r.qty_forecast || "—"}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
              <p className="mt-3 border-t border-line pt-3 text-[12px] text-faint">
                Итого доступно: <b className="text-ink">{stock.total_available} {card.unit ?? "шт"}</b>
                {stock.total_reserved > 0 && <> · в резерве {stock.total_reserved}</>}. Размещение по
                ячейкам и движение (приход/расход) — после интеграции WMS. Истина остатка — 1С.
              </p>
            </Card>
          ) : (
            <EmptyState
              title="🗄 Размещение, остатки и движение"
              hint="Остатков по этому товару в 1С нет. Размещение по складам/ячейкам и движение появятся после синка остатков из 1С и интеграции WMS. Истина остатка — 1С."
            />
          )
        )}

        {/* ──────── ТАБ: ЦЕНЫ И МАРЖА ──────── */}
        {tab === "price" && (
          <div className="space-y-4">
            <div className="flex items-center gap-2 rounded-xl bg-amber-50 px-3 py-2.5 text-[12.5px] font-medium text-amber-700">
              🔒 Видно отделу продаж, директору и заму. Закупщик видит landed cost и цену со скидкой
              (контроль маржи), но не видит клиента.
            </div>
            {stock?.price != null && stock?.cost != null ? (
              <Card>
                <p className="text-[13.5px] font-bold text-ink">💵 Цена и маржа</p>
                <table className="mt-2 w-full border-collapse text-[13px]">
                  <thead>
                    <tr className="text-left text-[10.5px] uppercase tracking-wide text-faint">
                      <th className="py-2 pr-3 font-semibold">Показатель</th>
                      <th className="py-2 pr-3 text-right font-semibold">Значение</th>
                      <th className="py-2 text-right font-semibold">Маржа</th>
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-line">
                    <tr>
                      <td className="py-2 pr-3 text-muted">Себестоимость (из 1С)</td>
                      <td className="py-2 pr-3 text-right font-semibold tabular-nums text-ink">
                        {formatByn(stock.cost)}
                      </td>
                      <td className="py-2 text-right text-faint">—</td>
                    </tr>
                    <tr>
                      <td className="py-2 pr-3 text-muted">Цена продажи (из 1С)</td>
                      <td className="py-2 pr-3 text-right font-semibold tabular-nums text-ink">
                        {formatByn(stock.price)}
                      </td>
                      <td className="py-2 text-right">
                        {margin != null && (
                          <Badge tone={margin >= 20 ? "ok" : "warn"}>+{margin}%</Badge>
                        )}
                      </td>
                    </tr>
                    {card.landed_cost != null && (
                      <tr>
                        <td className="py-2 pr-3 text-muted">Landed cost (партия)</td>
                        <td className="py-2 pr-3 text-right font-semibold tabular-nums text-ink">
                          {formatByn(card.landed_cost)}
                        </td>
                        <td className="py-2 text-right text-faint">—</td>
                      </tr>
                    )}
                  </tbody>
                </table>
                <p className="mt-3 text-[12px] text-faint">
                  Цена и себестоимость — из 1С (зеркало). Маржа = (цена − себес) / цена. Прайс-листы,
                  скидки и история цен (SCD2) появятся после реализации прайсинга в продажах.
                </p>
              </Card>
            ) : (
              <EmptyState
                title="💵 Цена и маржа"
                hint="Цена и себестоимость по этому товару из 1С не пришли. Маржа считается от себестоимости/landed cost. Прайс-листы, скидки и история цен (SCD2) появятся после реализации прайсинга в продажах."
              />
            )}
          </div>
        )}

        {/* ──────── ТАБ: АНАЛИТИКА ──────── */}
        {tab === "analytics" && (
          <EmptyState
            title="📊 ABC/XYZ, продажи, оборачиваемость"
            hint="Классификация ABC/XYZ, продажи, топ-клиенты и прогноз дефицита считаются по истории сделок за 12 мес. Аналитического слоя по этому товару пока нет — показатели не выдумываем (витрина золотой записи). Появятся со связью S&OP."
          />
        )}

        {/* ──────── ТАБ: ИСТОРИЯ ──────── */}
        {tab === "history" &&
          (card.history.length > 0 ? (
            <Card>
              <div className="flex items-center justify-between gap-2">
                <p className="text-[13.5px] font-bold text-ink">🕘 История характеристик</p>
                <Badge tone="violet">SCD2</Badge>
              </div>
              <p className="mt-1 text-[12px] text-muted">
                Датированные версии мастер-полей: документ «на дату» видит характеристики,
                действовавшие тогда. Цена/остаток — операционные (истина 1С), здесь не ведутся.
              </p>
              <ol className="mt-3 space-y-3">
                {card.history.map((v, i) => {
                  const older = card.history[i + 1] ?? null; // история по убыванию: следующая — старее
                  const changes = changedFields(v, older);
                  const current = v.end_date === null;
                  return (
                    <li key={`${v.start_date}-${i}`} className="rounded-xl bg-sunken p-3.5">
                      <div className="flex flex-wrap items-center gap-2">
                        <Badge tone={current ? "ok" : "mut"}>{current ? "текущая" : "архив"}</Badge>
                        <span className="text-[12.5px] font-semibold text-ink">
                          с {fmtDate(v.start_date)}
                          {v.end_date ? ` по ${fmtDate(v.end_date)}` : ""}
                        </span>
                        {older === null ? (
                          <Badge tone="info">первая версия</Badge>
                        ) : changes.length > 0 ? (
                          <span className="text-[11px] text-faint">
                            изменено: {changes.join(", ")}
                          </span>
                        ) : null}
                      </div>
                      <div className="mt-2 grid gap-3 sm:grid-cols-2">
                        <Field label="Наименование" value={v.title} />
                        <Field label="Ед." value={v.unit ?? "—"} />
                        <Field
                          label="Вес, кг"
                          value={v.weight_kg != null ? String(v.weight_kg) : "—"}
                          mono={v.weight_kg != null}
                          unset={v.weight_kg == null}
                        />
                        <Field
                          label="Объём, м³"
                          value={v.volume_m3 != null ? String(v.volume_m3) : "—"}
                          mono={v.volume_m3 != null}
                          unset={v.volume_m3 == null}
                        />
                        <Field
                          label="Код ТН ВЭД"
                          value={v.tnved_code ?? "—"}
                          mono={!!v.tnved_code}
                          unset={!v.tnved_code}
                        />
                        <Field
                          label="Код НДС"
                          value={v.vat_code ?? "—"}
                          mono={!!v.vat_code}
                          unset={!v.vat_code}
                        />
                        <Field
                          label="Срок годн., дн."
                          value={v.shelf_life_days != null ? String(v.shelf_life_days) : "—"}
                          mono={v.shelf_life_days != null}
                          unset={v.shelf_life_days == null}
                        />
                      </div>
                    </li>
                  );
                })}
              </ol>
              <p className="mt-3 border-t border-line pt-3 text-[12px] text-faint">
                Происхождение по полям (источник 1С/ERP) — во вкладке «Обзор». Журнал «кто/когда»
                правил — отдельная проекция событий справочника.
              </p>
            </Card>
          ) : (
            <EmptyState
              title="🕘 История характеристик (SCD2)"
              hint="Датированных версий по этому товару пока нет — появятся, когда мастер-поля номенклатуры начнут версионировать при правке. Документ «на дату» будет видеть характеристики, действовавшие тогда. Происхождение по полям уже видно во вкладке «Обзор»."
            />
          ))}
      </div>
    </div>
  );
}
