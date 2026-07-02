"use client"

import { useState } from "react"

// ── Types ──────────────────────────────────────────────────────────────────

type Path = "cny" | "usd"
type RowStatus = "machine" | "deal" | "history" | "draft"

interface CostRow {
  name: string
  hs: string
  path: Path
  price: number
  qty: number
  w: number
  tara: string
  perBox: number
  util: number
  markup: number
  markup0: number
  duty: number | null // percent 0–100, null = use settings default
  status: RowStatus
  machine: string
  deal: string
  date: string
}

interface Settings {
  usdByn: number
  cnyRub: number
  rubByn: number
  usdRub: number
  fxBuf: number    // percent (≥ 10)
  comm: number     // percent
  ins: number      // percent
  freight: number  // USD/kg
  duty: number     // percent fallback
  utilRate: number // percent
  vat: number      // percent
  minRent: number  // percent
}

interface CalcResult {
  isCny: boolean
  goodsUnitWC: number
  wcToByn: number
  fxFreight: number
  goods: number
  comm: number
  ins: number
  freight: number
  duty: number
  dutyRate: number
  total: number
  landedUnitWC: number
  fxPart: number
  landed: number
  priceEx: number
  priceVat: number
  sumVat: number
  utilOnPrice: number
  profitU: number
  profit: number
  margin: number
}

// ── Static data ────────────────────────────────────────────────────────────

// Demo duty rates; source of truth = ref_tnved on backend
const TNVED: Record<string, number> = {
  "8507 60 000 0": 0,
  "8504 40 900 0": 0,
  "8427 20 110 0": 5,
  "8427 20 190 0": 5,
}

function dutyForHs(hs: string): number | null {
  return hs in TNVED ? TNVED[hs] : null
}

type SkuTemplate = Omit<CostRow, "price" | "qty" | "markup" | "markup0" | "status" | "machine" | "deal" | "date">

const SKU_DATA: SkuTemplate[] = [
  { name: "Аккумулятор Li INR18650-35E 3500mah", hs: "8507 60 000 0", path: "cny", w: 0.05,   tara: "коробка 44×28×6 см", perBox: 70,  util: 0,     duty: dutyForHs("8507 60 000 0") },
  { name: "Lifepo4 battery pack 25.6V/200Ah",    hs: "8507 60 000 0", path: "cny", w: 57.667, tara: "паллета",            perBox: 1,   util: 0,     duty: dutyForHs("8507 60 000 0") },
  { name: "Электроштабелер HILIFT PT16",         hs: "8427 20 190 0", path: "usd", w: 1500,   tara: "без упаковки",       perBox: 1,   util: 0,     duty: dutyForHs("8427 20 190 0") },
  { name: "Погрузчик CPD15 48V/450ah",           hs: "8427 20 110 0", path: "usd", w: 2800,   tara: "без упаковки",       perBox: 1,   util: 6800,  duty: dutyForHs("8427 20 110 0") },
  { name: "Электропогрузчик CPD35 15·24kw",      hs: "8427 20 190 0", path: "usd", w: 3900,   tara: "без упаковки",       perBox: 1,   util: 28100, duty: dutyForHs("8427 20 190 0") },
]

const skuByName: Record<string, SkuTemplate> = Object.fromEntries(SKU_DATA.map(s => [s.name, s]))

function makeDemoRows(): CostRow[] {
  const specs: Array<{ i: number; price: number; qty: number; markup: number; status: RowStatus; machine: string; deal: string; date: string }> = [
    { i: 0, price: 17,   qty: 1200, markup: 2.0,  status: "machine", machine: "MO-2026-016", deal: "S-1182", date: "20.06.2026" },
    { i: 1, price: 5350, qty: 6,    markup: 2.0,  status: "deal",    machine: "",            deal: "S-1187", date: "24.06.2026" },
    { i: 2, price: 4423, qty: 1,    markup: 1.8,  status: "history", machine: "MO-2026-013", deal: "S-1099", date: "12.06.2026" },
    { i: 3, price: 6800, qty: 3,    markup: 1.65, status: "machine", machine: "MO-2026-017", deal: "S-1185", date: "22.06.2026" },
    { i: 4, price: 9400, qty: 1,    markup: 1.2,  status: "deal",    machine: "",            deal: "S-1190", date: "25.06.2026" },
  ]
  return specs.map(s => ({
    ...SKU_DATA[s.i]!,
    price: s.price, qty: s.qty,
    markup: s.markup, markup0: s.markup,
    status: s.status, machine: s.machine, deal: s.deal, date: s.date,
  }))
}

const DEFAULT_SETTINGS: Settings = {
  usdByn: 3.0, cnyRub: 12.8, rubByn: 0.0368, usdRub: 94,
  fxBuf: 10, comm: 18, ins: 0.2, freight: 1.5,
  duty: 5, utilRate: 3, vat: 20, minRent: 15,
}

// ── Calculation (mirrors Расчёт Китай.xlsx logic) ─────────────────────────

function calcRow(r: CostRow, s: Settings): CalcResult {
  const isCny = r.path === "cny"
  const goodsUnitWC = isCny ? r.price * s.cnyRub : r.price * s.usdByn
  const wcToByn = isCny ? s.rubByn : 1
  const fxFreight = isCny ? s.usdRub : s.usdByn
  const goods = goodsUnitWC * r.qty
  const comm = goods * (s.comm / 100)
  const ins = goods * (s.ins / 100)
  const freight = r.w * r.qty * s.freight * fxFreight
  const dutyRate = r.duty != null ? r.duty / 100 : s.duty / 100
  const duty = (goods + freight) * dutyRate
  const total = goods + comm + ins + freight + duty
  const landedUnitWC = r.qty ? total / r.qty : 0
  const fxPart = landedUnitWC * wcToByn * (1 + Math.max(s.fxBuf, 0) / 100)
  const landed = fxPart + (r.util || 0)
  const priceEx = landed * r.markup
  const priceVat = priceEx * (1 + s.vat / 100)
  const sumVat = priceVat * r.qty
  const utilOnPrice = priceEx * (s.utilRate / 100)
  const profitU = priceEx - landed - utilOnPrice
  const profit = profitU * r.qty
  const margin = sumVat ? profit / sumVat : 0
  return {
    isCny, goodsUnitWC, wcToByn, fxFreight, goods, comm, ins, freight,
    duty, dutyRate, total, landedUnitWC, fxPart, landed,
    priceEx, priceVat, sumVat, utilOnPrice, profitU, profit, margin,
  }
}

// ── Formatting ─────────────────────────────────────────────────────────────

const f2 = (n: number) => (isFinite(n) ? (n || 0) : 0).toFixed(2)
const f0 = (n: number) => Math.round(isFinite(n) ? (n || 0) : 0).toLocaleString("ru-RU")
const pct = (n: number) => ((isFinite(n) ? (n || 0) : 0) * 100).toFixed(1) + "%"

// ── Status config ──────────────────────────────────────────────────────────

const STATUS_CFG: Record<RowStatus, { lbl: string; cls: string }> = {
  machine: { lbl: "🚚 в машине",  cls: "bg-emerald-50 dark:bg-emerald-500/15 text-emerald-700 dark:text-emerald-300" },
  deal:    { lbl: "📋 предварит.", cls: "bg-amber-50 dark:bg-amber-500/15 text-amber-700 dark:text-amber-300" },
  history: { lbl: "🗄 история",   cls: "bg-sunken text-faint" },
  draft:   { lbl: "● черновик",   cls: "bg-accent-soft text-accent" },
}

// ── Sub-components ─────────────────────────────────────────────────────────

function RateInput({
  label, hint, value, onChange, step = 0.01, min,
}: {
  label: string; hint?: string; value: number
  onChange: (v: number) => void; step?: number; min?: number
}) {
  return (
    <label className="block">
      <span className="text-[11px] text-muted">
        {label}{hint && <span className="text-faint"> {hint}</span>}
      </span>
      <input
        type="number"
        step={step}
        min={min}
        value={value}
        onChange={e => onChange(parseFloat(e.target.value) || 0)}
        className="mt-1 w-full rounded-lg bg-sunken border border-line px-2 py-[5px] text-right font-bold text-sm text-ink focus:outline-none focus:border-accent focus:bg-surface [appearance:textfield] [&::-webkit-outer-spin-button]:appearance-none [&::-webkit-inner-spin-button]:appearance-none"
      />
    </label>
  )
}

function CellInput({
  value, onChange, step = 0.01, className = "",
}: {
  value: number; onChange: (v: number) => void; step?: number; className?: string
}) {
  return (
    <input
      type="number"
      step={step}
      value={value}
      onChange={e => onChange(parseFloat(e.target.value) || 0)}
      onClick={e => e.stopPropagation()}
      className={`bg-transparent border border-transparent rounded-lg px-1.5 py-0.5 text-ink font-semibold hover:border-line focus:outline-none focus:border-accent focus:bg-surface [appearance:textfield] [&::-webkit-outer-spin-button]:appearance-none [&::-webkit-inner-spin-button]:appearance-none ${className}`}
    />
  )
}

function BrkRow({ label, value, hint }: { label: string; value: string; hint?: string }) {
  return (
    <div className="flex items-baseline justify-between gap-3 py-1 border-b border-line/60">
      <span className="text-[12px] text-muted">
        {label}{hint && <span className="text-faint"> {hint}</span>}
      </span>
      <span className="text-[13px] font-semibold tabular-nums">{value}</span>
    </div>
  )
}

// ── Main component ─────────────────────────────────────────────────────────

export function ProcurementCostCalc() {
  const [settings, setSettings] = useState<Settings>(DEFAULT_SETTINGS)
  const [rows, setRows] = useState<CostRow[]>(makeDemoRows)
  const [sel, setSel] = useState(0)

  function setSetting(k: keyof Settings, v: number) {
    setSettings(s => ({ ...s, [k]: v }))
  }

  function updateRow(idx: number, patch: Partial<CostRow>) {
    setRows(prev => prev.map((r, i) => (i === idx ? { ...r, ...patch } : r)))
  }

  function addRow() {
    const newRow: CostRow = {
      name: "", hs: "", duty: null, path: "cny",
      price: 0, qty: 1, w: 0, tara: "—", perBox: 1, util: 0,
      markup: 1.5, markup0: 1.5, status: "draft",
      machine: "", deal: "", date: "29.06.2026",
    }
    setRows(prev => [...prev, newRow])
    setSel(rows.length)
  }

  function deleteRow(idx: number) {
    setRows(prev => prev.filter((_, i) => i !== idx))
    setSel(s => Math.min(s, Math.max(0, rows.length - 2)))
  }

  function resetAll() {
    setSettings(DEFAULT_SETTINGS)
    setRows(makeDemoRows())
    setSel(0)
  }

  const calcs = rows.map(r => calcRow(r, settings))
  const totalCost   = calcs.reduce((sum, c, i) => sum + c.landed * (rows[i]?.qty ?? 0), 0)
  const totalRev    = calcs.reduce((sum, c) => sum + c.sumVat, 0)
  const totalProfit = calcs.reduce((sum, c) => sum + c.profit, 0)
  const totalMargin = totalRev ? totalProfit / totalRev : 0

  const minRentFrac = settings.minRent / 100

  return (
    <div className="space-y-4">
      {/* Header */}
      <div className="flex items-start justify-between gap-4 flex-wrap">
        <div>
          <h2 className="text-xl font-bold">
            Предварительная себестоимость (Китай) → цена реализации
          </h2>
          <p className="mt-1 text-[13px] text-muted max-w-[760px]">
            Цена поставщика + комиссия + страховка + доставка + пошлина →{" "}
            <b>landed cost</b> за штуку → наценка и НДС → цена продажи → прибыль.
            Все ставки редактируемые, пересчёт на лету.
          </p>
        </div>
        <div className="flex gap-2 shrink-0">
          <button
            onClick={addRow}
            className="rounded-xl bg-accent px-3 py-2 text-sm font-semibold text-white shadow-card hover:opacity-90"
          >
            + Позиция
          </button>
          <button
            onClick={resetAll}
            className="rounded-xl bg-surface px-3 py-2 text-sm font-semibold text-ink border border-line hover:border-accent"
          >
            Сбросить
          </button>
        </div>
      </div>

      {/* Info banner */}
      <div className="rounded-2xl bg-accent-soft/50 border border-accent/20 px-4 py-3 text-[13px] text-ink space-y-1">
        <div>
          <b>Назначение:</b> предварительная себестоимость → <b>цена реализации</b>.
          Согласуется с клиентом, идёт в прайс и цену продажи.
        </div>
        <div className="text-muted">
          <b className="text-ink">Фактическая себестоимость</b> — из 1С (после перехода — через план счетов ERP).
          🛡 <b className="text-ink">Буфер курса +10%</b> заложен. Рентабельность ниже минимума —{" "}
          <b className="text-red-600 dark:text-red-400">красная подсветка</b>.
        </div>
      </div>

      {/* Settings panels */}
      <div className="grid gap-4 lg:grid-cols-2">
        <div className="rounded-2xl bg-surface p-4 shadow-card">
          <div className="text-sm font-semibold mb-3">
            Курсы валют <span className="text-faint font-normal">· задаются вручную</span>
          </div>
          <div className="grid grid-cols-2 gap-3 sm:grid-cols-3">
            <RateInput label="USD → BYN"          value={settings.usdByn}  onChange={v => setSetting("usdByn", v)}  step={0.0001} />
            <RateInput label="CNY → RUB"          value={settings.cnyRub}  onChange={v => setSetting("cnyRub", v)}  step={0.01} />
            <RateInput label="RUB → BYN"          value={settings.rubByn}  onChange={v => setSetting("rubByn", v)}  step={0.0001} />
            <RateInput label="USD → RUB (фрахт)"  value={settings.usdRub}  onChange={v => setSetting("usdRub", v)}  step={0.1} />
            <RateInput label="Буфер курса, %" hint="мин 10" value={settings.fxBuf} onChange={v => setSetting("fxBuf", Math.max(v, 10))} step={1} min={10} />
          </div>
          <p className="mt-2 text-[11px] text-faint">
            Закладываем буфер на курсовые колебания (мин. +10% сверх курса НБ РБ).
          </p>
        </div>

        <div className="rounded-2xl bg-surface p-4 shadow-card">
          <div className="text-sm font-semibold mb-3">Ставки и коэффициенты</div>
          <div className="grid grid-cols-2 gap-3 sm:grid-cols-3">
            <RateInput label="Комиссия, %"              value={settings.comm}     onChange={v => setSetting("comm", v)}     step={0.1} />
            <RateInput label="Страховка, %"             value={settings.ins}      onChange={v => setSetting("ins", v)}      step={0.01} />
            <label className="block">
              <span className="text-[11px] text-muted">Доставка (фрахт)</span>
              <select
                value={settings.freight}
                onChange={e => setSetting("freight", parseFloat(e.target.value))}
                className="mt-1 w-full rounded-lg bg-sunken border border-line px-2 py-[5px] text-sm font-bold text-ink focus:outline-none focus:border-accent focus:bg-surface"
              >
                {[1.5, 2, 5, 10].map(v => (
                  <option key={v} value={v}>{v} $/кг</option>
                ))}
              </select>
            </label>
            <RateInput label="Пошлина по умолч., %" hint="нет ТН ВЭД" value={settings.duty}     onChange={v => setSetting("duty", v)}     step={0.5} />
            <RateInput label="Утильсбор АКБ, %"                        value={settings.utilRate} onChange={v => setSetting("utilRate", v)} step={0.5} />
            <RateInput label="НДС, %"                                   value={settings.vat}     onChange={v => setSetting("vat", v)}     step={1} />
            <RateInput label="Мин. рентабельность, %" hint="ниже = красный" value={settings.minRent} onChange={v => setSetting("minRent", v)} step={1} />
          </div>
        </div>
      </div>

      {/* Summary cards */}
      <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
        {[
          { label: "Себестоимость партии", sub: "предварит. landed cost, BYN", val: f0(totalCost),   cls: "" },
          { label: "Выручка с НДС",        sub: "сумма продажи, BYN",          val: f0(totalRev),    cls: "" },
          { label: "Прибыль",              sub: "валовая, BYN",                val: f0(totalProfit), cls: "text-money" },
          { label: "Рентабельность",       sub: "прибыль / выручка",           val: pct(totalMargin), cls: "" },
        ].map(c => (
          <div key={c.label} className="rounded-2xl bg-surface p-4 shadow-card">
            <div className="text-[11px] text-muted">{c.label}</div>
            <div className={`mt-1 text-xl font-bold tabular-nums ${c.cls}`}>{c.val}</div>
            <div className="text-[11px] text-faint">{c.sub}</div>
          </div>
        ))}
      </div>

      {/* Table */}
      <div className="rounded-2xl bg-surface shadow-card overflow-hidden">
        <div className="overflow-x-auto">
          <table className="w-full text-[13px]">
            <thead>
              <tr className="bg-sunken text-muted text-left">
                <th className="px-3 py-2 font-semibold min-w-[200px]">Номенклатура</th>
                <th className="px-2 py-2 font-semibold whitespace-nowrap">ТН ВЭД</th>
                <th className="px-2 py-2 font-semibold">Путь</th>
                <th className="px-2 py-2 font-semibold text-right whitespace-nowrap">Цена за ед.</th>
                <th className="px-2 py-2 font-semibold text-right">Кол-во</th>
                <th className="px-2 py-2 font-semibold text-right whitespace-nowrap">Вес/шт, кг</th>
                <th className="px-2 py-2 font-semibold text-right whitespace-nowrap">Наценка ×</th>
                <th className="px-2 py-2 font-semibold text-right bg-accent-soft/60 whitespace-nowrap">Себес/шт, BYN</th>
                <th className="px-2 py-2 font-semibold text-right whitespace-nowrap">Цена без НДС</th>
                <th className="px-2 py-2 font-semibold text-right whitespace-nowrap">Цена с НДС</th>
                <th className="px-2 py-2 font-semibold text-right whitespace-nowrap text-money">Прибыль/шт</th>
                <th className="px-2 py-2 font-semibold text-right">Рентаб.</th>
                <th className="px-2 py-2 font-semibold">Статус / машина</th>
                <th className="px-2 py-2"></th>
              </tr>
            </thead>
            <tbody>
              {rows.map((r, i) => {
                const c = calcs[i]!
                const isSelected = i === sel
                const lowRent = c.margin < minRentFrac
                const lowMarkup = r.markup < r.markup0
                const marginCls = lowRent
                  ? "text-red-600 dark:text-red-400 font-bold"
                  : c.margin < 0.18
                  ? "text-amber-600 dark:text-amber-300"
                  : "text-money"
                const statusCfg = STATUS_CFG[r.status] ?? STATUS_CFG.draft
                const statusRef = r.status === "machine"
                  ? `машина ${r.machine}`
                  : r.status === "history"
                  ? `→ ${r.machine || "—"}`
                  : r.deal
                  ? `сделка ${r.deal}`
                  : ""

                return (
                  <tr
                    key={i}
                    onClick={() => setSel(i)}
                    className={[
                      "border-t border-line align-middle cursor-pointer transition-colors",
                      isSelected
                        ? "bg-accent-soft/30 shadow-[inset_3px_0_0_rgb(var(--accent))]"
                        : "hover:bg-sunken/60",
                      lowRent ? "bg-red-50/50 dark:bg-red-500/10" : "",
                    ].filter(Boolean).join(" ")}
                  >
                    <td className="px-2 py-1">
                      <input
                        list="cost-calc-sku-list"
                        value={r.name}
                        onChange={e => {
                          const match = skuByName[e.target.value]
                          if (match) {
                            updateRow(i, { ...match })
                          } else {
                            updateRow(i, { name: e.target.value })
                          }
                        }}
                        onClick={e => e.stopPropagation()}
                        className="bg-transparent border border-transparent rounded-lg px-1.5 py-0.5 text-ink font-semibold w-full hover:border-line focus:outline-none focus:border-accent focus:bg-surface"
                      />
                    </td>
                    <td className="px-1 py-1 whitespace-nowrap">
                      <span className="text-[11px] text-muted tabular-nums">{r.hs || "—"}</span>
                    </td>
                    <td className="px-1 py-1">
                      <select
                        value={r.path}
                        onChange={e => updateRow(i, { path: e.target.value as Path })}
                        onClick={e => e.stopPropagation()}
                        className="bg-transparent border border-transparent rounded-lg px-1.5 py-0.5 text-ink font-semibold cursor-pointer hover:border-line focus:outline-none focus:border-accent focus:bg-surface"
                      >
                        <option value="cny">CNY→RUB→BYN</option>
                        <option value="usd">USD→BYN</option>
                      </select>
                    </td>
                    <td className="px-1 py-1 text-right whitespace-nowrap">
                      <span className="text-faint text-[11px]">{r.path === "cny" ? "¥" : "$"}</span>
                      <CellInput
                        value={r.price} step={0.01}
                        onChange={v => updateRow(i, { price: v })}
                        className="inline-block w-[78px] text-right"
                      />
                    </td>
                    <td className="px-1 py-1 text-right">
                      <CellInput value={r.qty} step={1} onChange={v => updateRow(i, { qty: v })} className="w-[60px] text-right" />
                    </td>
                    <td className="px-1 py-1 text-right whitespace-nowrap">
                      <CellInput value={r.w} step={0.001} onChange={v => updateRow(i, { w: v })} className="w-[64px] text-right" />
                      <span className="text-faint text-[10px]"> 🔗</span>
                    </td>
                    <td className="px-1 py-1 text-right">
                      <CellInput
                        value={r.markup} step={0.05}
                        onChange={v => updateRow(i, { markup: v })}
                        className={["w-[56px] text-right", lowMarkup ? "text-red-600 dark:text-red-400 ring-1 ring-red-400 rounded" : ""].join(" ")}
                      />
                      {lowMarkup && (
                        <span className="text-red-500 text-[10px]" title={`ниже стандарта ${r.markup0}`}>▼</span>
                      )}
                    </td>
                    <td className="px-2 py-1 text-right font-bold tabular-nums bg-accent-soft/30">
                      {f2(c.landed)}
                    </td>
                    <td className="px-2 py-1 text-right tabular-nums">{f2(c.priceEx)}</td>
                    <td className="px-2 py-1 text-right tabular-nums">{f2(c.priceVat)}</td>
                    <td className="px-2 py-1 text-right font-semibold tabular-nums text-money">{f2(c.profitU)}</td>
                    <td className={`px-2 py-1 text-right font-semibold tabular-nums ${marginCls}`}>
                      {pct(c.margin)}{lowRent && <span title="ниже минимума"> ⚠</span>}
                    </td>
                    <td className="px-2 py-1 whitespace-nowrap">
                      <span className={`inline-flex items-center rounded-full px-2 py-0.5 text-[10px] font-semibold ${statusCfg.cls}`}>
                        {statusCfg.lbl}
                      </span>
                      <div className="mt-0.5 text-[10px] text-faint leading-tight">
                        {statusRef}<br />{r.date}
                      </div>
                    </td>
                    <td className="px-1 py-1 text-right">
                      <button
                        onClick={e => { e.stopPropagation(); deleteRow(i) }}
                        className="text-faint hover:text-red-500 px-1"
                        title="Удалить"
                      >
                        ✕
                      </button>
                    </td>
                  </tr>
                )
              })}
            </tbody>
          </table>
        </div>
      </div>

      <datalist id="cost-calc-sku-list">
        {SKU_DATA.map(s => <option key={s.name} value={s.name} />)}
      </datalist>

      {/* Breakdown panel */}
      {(() => {
        const r = rows[sel]
        const c = calcs[sel]
        if (!r || !c) return null
        const wc = c.isCny ? "RUB" : "BYN"
        const statusCfg = STATUS_CFG[r.status] ?? STATUS_CFG.draft
        const statusRef = r.status === "machine"
          ? `машина ${r.machine}`
          : r.status === "history"
          ? `архив, ездила в ${r.machine || "—"}`
          : r.deal ? `сделка ${r.deal}` : "—"

        return (
          <div className="rounded-2xl bg-surface p-5 shadow-card">
            <div className="flex items-center justify-between flex-wrap gap-2">
              <div className="text-sm font-semibold">
                Расшифровка расчёта{" "}
                <span className="text-muted font-normal">· {r.name || "—"}</span>
              </div>
              <span className="text-[11px] text-faint">клик по строке — показать разбор</span>
            </div>

            {/* Info bar */}
            <div className="mt-3 rounded-xl bg-accent-soft/40 p-3 flex flex-wrap gap-x-6 gap-y-2 items-center text-[12px]">
              <span className="font-semibold text-ink">Из справочника номенклатуры 🔗</span>
              <span className="text-muted">
                ТН ВЭД: <b className="text-ink tabular-nums">{r.hs || "—"}</b>
              </span>
              <span className="text-muted">
                Пошлина по ТН ВЭД:{" "}
                <b className="text-ink tabular-nums">{(c.dutyRate * 100).toFixed(1)}%</b>
                {r.duty == null && <span className="text-faint"> (запасная)</span>}
              </span>
              <span className="text-muted">
                Вес/шт: <b className="text-ink tabular-nums">{r.w} кг</b>
              </span>
              <span className="text-muted">
                Тара: <b className="text-ink">{r.tara || "—"}</b>
              </span>
              <span className="ml-auto flex items-center gap-2">
                <span className={`inline-flex items-center rounded-full px-2 py-0.5 text-[10px] font-semibold ${statusCfg.cls}`}>
                  {statusCfg.lbl}
                </span>
                <span className="text-muted">{statusRef}</span>
                <span className="text-faint">· {r.date}</span>
              </span>
            </div>

            <div className="mt-3 grid gap-4 md:grid-cols-3">
              {/* Column 1: Landed cost */}
              <div className="rounded-xl bg-sunken p-3">
                <div className="text-[12px] font-semibold text-ink mb-1">
                  1 · Landed cost <span className="text-faint">({wc})</span>
                </div>
                <BrkRow
                  label="Цена ед. × курс"
                  value={`${f2(c.goodsUnitWC)} ${wc}`}
                  hint={c.isCny ? `¥${r.price}×${settings.cnyRub}` : `$${r.price}×${settings.usdByn}`}
                />
                <BrkRow label="Стоимость партии" value={`${f2(c.goods)} ${wc}`}   hint={`× ${r.qty} шт`} />
                <BrkRow label="Комиссия"          value={`${f2(c.comm)} ${wc}`}   hint={`${settings.comm}%`} />
                <BrkRow label="Страховка"         value={`${f2(c.ins)} ${wc}`}    hint={`${settings.ins}%`} />
                <BrkRow
                  label="Доставка"
                  value={`${f2(c.freight)} ${wc}`}
                  hint={`${(r.w * r.qty).toFixed(1)} кг × $${settings.freight}`}
                />
                <BrkRow label="Пошлина" value={`${f2(c.duty)} ${wc}`} hint={`${(c.dutyRate * 100).toFixed(1)}%`} />
                <div className="flex items-baseline justify-between gap-3 py-1">
                  <span className="text-[12px] font-semibold text-ink">Итого партия</span>
                  <span className="text-[13px] font-bold tabular-nums">{f2(c.total)} {wc}</span>
                </div>
              </div>

              {/* Column 2: Unit cost + price */}
              <div className="rounded-xl bg-sunken p-3">
                <div className="text-[12px] font-semibold text-ink mb-1">2 · Себестоимость за штуку</div>
                <BrkRow label={`Итого ÷ кол-во`} value={`${f2(c.landedUnitWC)} ${wc}`} hint={`÷ ${r.qty}`} />
                {c.isCny && (
                  <BrkRow
                    label="× курс RUB→BYN"
                    value={`${f2(c.landedUnitWC * c.wcToByn)} BYN`}
                    hint={`× ${settings.rubByn}`}
                  />
                )}
                {settings.fxBuf > 0 && (
                  <BrkRow
                    label="× буфер курса"
                    value={`${f2(c.fxPart)} BYN`}
                    hint={`+${settings.fxBuf}% курс. колебания`}
                  />
                )}
                {r.util > 0 && (
                  <BrkRow label="+ утильсбор техники" value={`${f2(r.util)} BYN`} hint="фикс." />
                )}
                <div className="flex items-baseline justify-between gap-3 py-1 border-b border-line/60">
                  <span className="text-[12px] font-semibold text-ink">Себес/шт, BYN</span>
                  <span className="text-[13px] font-bold text-accent tabular-nums">{f2(c.landed)}</span>
                </div>
                <div className="mt-2 text-[12px] font-semibold text-ink mb-1">3 · Цена продажи</div>
                <BrkRow
                  label={`× наценка${r.markup < r.markup0 ? " ▼ ниже стандарта" : ""}`}
                  value={`${f2(c.priceEx)} BYN`}
                  hint={`× ${r.markup}`}
                />
                <BrkRow label="+ НДС" value={`${f2(c.priceVat)} BYN`} hint={`${settings.vat}%`} />
                <div className="mt-2 rounded-lg bg-accent-soft/60 px-2.5 py-1.5 text-[11px] text-accent">
                  → согласуется с клиентом → в прайс и цену продажи
                </div>
              </div>

              {/* Column 3: Profit */}
              <div className="rounded-xl bg-sunken p-3">
                <div className="text-[12px] font-semibold text-ink mb-1">4 · Прибыль и рентабельность</div>
                <BrkRow label="Цена без НДС"      value={`${f2(c.priceEx)} BYN`} />
                <BrkRow label="− себестоимость"   value={`−${f2(c.landed)} BYN`} />
                <BrkRow label="− утильсбор АКБ"   value={`−${f2(c.utilOnPrice)} BYN`} hint={`${settings.utilRate}%`} />
                <div className="flex items-baseline justify-between gap-3 py-1 border-b border-line/60">
                  <span className="text-[12px] font-semibold text-ink">Прибыль / шт</span>
                  <span className="text-[13px] font-bold text-money tabular-nums">{f2(c.profitU)} BYN</span>
                </div>
                <BrkRow label="Прибыль партии" value={`${f2(c.profit)} BYN`}  hint={`× ${r.qty}`} />
                <BrkRow label="Выручка с НДС"  value={`${f2(c.sumVat)} BYN`} />
                <div className="flex items-baseline justify-between gap-3 py-1">
                  <span className="text-[12px] font-semibold text-ink">Рентабельность</span>
                  <span className="text-[13px] font-bold text-money tabular-nums">{pct(c.margin)}</span>
                </div>
              </div>
            </div>
          </div>
        )
      })()}
    </div>
  )
}
