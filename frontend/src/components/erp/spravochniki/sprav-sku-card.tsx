"use client";

import { useState } from "react";
import { Package, Wallet } from "lucide-react";

import { formatByn } from "@/lib/format";
import type { FieldProvenance, SkuCard } from "@/lib/reference-data";
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

/** Значение JSON-атрибута → строка (объект/массив — компактный JSON). */
function attrValue(v: unknown): string {
  if (v == null) return "—";
  if (typeof v === "object") return JSON.stringify(v);
  return String(v);
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

export function SpravSkuCard({ card }: { card: SkuCard }) {
  const [tab, setTab] = useState<TabId>("overview");

  const prov = card.provenance ?? {};
  const counts = provenanceCounts(prov);
  const attrs = Object.entries(card.attributes ?? {});
  const eff = card.effective_tnved ?? {
    code: card.tnved_code ?? null,
    source: card.tnved_code ? ("own" as const) : null,
    group_code: null,
    group_name: null,
  };
  const rates = card.tnved_rates;
  const groupPath = card.group_path ?? [];
  const sync = card.sync;

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
                {sync ? (
                  <Badge tone="violet" title={`Происхождение: ${sync.origin} · статус: ${sync.state}`}>
                    ↧ синк из 1С
                    {sync.last_synced_at ? ` · ${sync.last_synced_at.slice(0, 16).replace("T", " ")}` : ""}
                  </Badge>
                ) : (
                  <Badge tone="mut" title="Связь с 1С ещё не установлена">
                    нет синка с 1С
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
              big={<span className="italic text-faint">нет данных</span>}
              bigClass="text-[15px]"
              sub="истина остатка — 1С"
            />
            <Kpi
              icon="🗄"
              label="Где лежит"
              big={<span className="italic text-faint">нет данных</span>}
              bigClass="text-[15px]"
              sub="WMS / инвентаризация"
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
                  <Field label="Ед. измерения" value={card.unit ?? "—"} prov={prov.unit} />
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
                  <p className="text-[12px] text-faint">
                    Производитель, марка, импортёр и страна происхождения появятся, когда будут
                    заполнены на товаре или унаследованы от группы. Сейчас не заданы.
                  </p>
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
                  <Field label="Габариты (Д×Ш×В)" value="нет данных" unset />
                  <Field label="Объём" value="нет данных" unset />
                  <Field label="Кол-во в коробке" value="нет данных" unset />
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
        {tab === "procure" && (
          <EmptyState
            title="🚚 Партии закупки и landed cost"
            hint="Партии из Китая (поставщик, машина, технология тестирования, приёмка, годен до) и разбор себестоимости появятся после реализации модели партии в закупках (ZAK). Сейчас транзакционных данных по этому товару нет — числа не выдумываем."
          />
        )}

        {/* ──────── ТАБ: СКЛАД ──────── */}
        {tab === "wh" && (
          <EmptyState
            title="🗄 Размещение, остатки и движение"
            hint="Размещение по складам/ячейкам, остатки и движение (приход/расход/перемещение) появятся после интеграции WMS и синка остатков из 1С. Истина остатка — 1С; пока данных нет — поле пустое."
          />
        )}

        {/* ──────── ТАБ: ЦЕНЫ И МАРЖА ──────── */}
        {tab === "price" && (
          <div className="space-y-4">
            <div className="flex items-center gap-2 rounded-xl bg-amber-50 px-3 py-2.5 text-[12.5px] font-medium text-amber-700">
              🔒 Видно отделу продаж, директору и заму. Закупщик видит landed cost и цену со скидкой
              (контроль маржи), но не видит клиента.
            </div>
            {card.landed_cost != null ? (
              <Card>
                <p className="text-[13.5px] font-bold text-ink">💵 Цена и маржа</p>
                <table className="mt-2 w-full border-collapse text-[13px]">
                  <tbody className="divide-y divide-line">
                    <tr>
                      <td className="py-2 text-muted">Landed cost (себест.)</td>
                      <td className="py-2 text-right font-semibold tabular-nums text-ink">
                        {formatByn(card.landed_cost)}
                      </td>
                    </tr>
                    <tr>
                      <td className="py-2 text-muted">Прайс (база)</td>
                      <td className="py-2 text-right italic text-faint">цена не задана</td>
                    </tr>
                  </tbody>
                </table>
                <p className="mt-3 text-[12px] text-faint">
                  Прайс, скидки и минимальная цена появятся после реализации прайс-листов в продажах.
                  Маржа считается от landed cost.
                </p>
              </Card>
            ) : (
              <EmptyState
                title="💵 Цена и маржа"
                hint="Маржа считается от landed cost, которого пока нет (расчёт партии в закупках не выполнен). Прайс/скидки/история цен (SCD2) появятся после реализации прайс-листов в продажах."
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
        {tab === "history" && (
          <EmptyState
            title="🕘 Аудит изменений"
            hint="Журнал изменений полей (было → стало, кто, когда, источник 1С/ERP) появится, когда для номенклатуры включат аудит. Происхождение по полям уже видно во вкладке «Обзор» (блок «Происхождение полей»)."
          />
        )}
      </div>
    </div>
  );
}
