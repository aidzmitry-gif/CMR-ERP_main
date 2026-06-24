import Link from "next/link";
import { ArrowLeft } from "lucide-react";
import { ChannelButtons } from "@/components/channels";
import { DealActions } from "@/components/deal-actions";
import { DealAiAssistant } from "@/components/deal-ai-assistant";
import { DealApprovals } from "@/components/deal-approvals";
import { DealContacts } from "@/components/deal-contacts";
import { DealEditButton } from "@/components/deal-edit-button";
import { DealDocuments } from "@/components/deal-documents";
import { DealItems } from "@/components/deal-items";
import { DealTasks } from "@/components/deal-tasks";
import { DealMessages } from "@/components/deal-messages";
import { PriorityBadge } from "@/components/priority-badge";
import { Card } from "@/components/ui/card";
import { fetchDealDetail } from "@/lib/api";
import { formatByn } from "@/lib/format";
import { currentRole } from "@/lib/role-server";

// 9-стадийная воронка продаж (эталон — sales-card-full.html).
// TODO(SALES): stage/stageIdx → из бэкенда (d.stage.idx), пока хардкод-stub.
const STAGES = [
  "Контакт",
  "Квалификация",
  "Презентация",
  "Встреча",
  "Есть цена",
  "Счёт защищён",
  "Договор / предоплата",
  "Отгрузка",
  "Закрыта",
];

export default async function DealDetailPage({ params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;
  const d = await fetchDealDetail(id, await currentRole());
  // Server-only хардкод; страница остаётся server component, гидрация консистентна.
  const stageIdx = 0;

  return (
    <div className="min-h-screen bg-canvas text-ink">
      <div className="mx-auto max-w-[1280px] px-[22px] pb-10 pt-[18px]">
        <Link
          href="/crm/deals"
          className="mb-3 inline-flex items-center gap-1 text-[12.5px] font-semibold text-muted hover:text-ink"
        >
          <ArrowLeft size={14} /> К сделкам
        </Link>

        {/* ── ШАПКА ── */}
        <Card className="mb-3.5 px-[18px] py-[13px]">
          <div className="flex flex-wrap items-start gap-3.5">
            <div className="min-w-0 flex-1">
              <div className="text-[12.5px] text-muted">№ {d.number}</div>
              <h1 className="mt-px text-[19px] font-extrabold leading-tight text-ink">
                {d.company || "Контрагент не указан"}
              </h1>
              <div className="mt-0.5 text-[12.5px] text-muted">
                {d.description || "Описание не задано"}
              </div>
              {/* Контрагент — из MDM-витрины (источник истины — 1С).
                  TODO: реальный УНП/counterparty.id из API; пока плэйсхолдер. */}
              <div className="mt-1 flex flex-wrap items-center gap-2 text-[11px] text-faint">
                <span className="rounded-md bg-sunken px-1.5 py-0.5 font-semibold text-muted">
                  контрагент · из MDM / 1С
                </span>
                <span className="text-faint">УНП —</span>
              </div>
              <div className="mt-1.5 flex flex-wrap items-center gap-1.5">
                <PriorityBadge priority={d.priority} withIcon />
                {/* TODO(SALES): stage / regular / temperature / ship-бейджи из бэкенда */}
              </div>
            </div>
            <div className="flex flex-wrap gap-2">
              <DealEditButton
                dealId={id}
                title={d.description}
                amount={d.amount}
                nextStep={d.nextStep}
                dealDate={d.dealDate}
              />
            </div>
          </div>

          <Metrics amount={d.amount} closeDate={d.dealDate} />
          <Stages currentIdx={stageIdx} />
        </Card>

        {/* ── ОСНОВНАЯ СЕТКА: 1.5fr / 1fr; порядок блоков как в render() прототипа. ── */}
        <div className="grid grid-cols-1 items-start gap-4 lg:grid-cols-[1.5fr_1fr]">
          {/* LEFT — «мозг» сверху (AI), затем операционка по порядку прототипа */}
          <div className="min-w-0 space-y-4">
            <DealAiAssistant dealId={id} />
            <NextStepStub nextStep={d.nextStep} datetime={d.datetime} contact={d.contact} />
            <ShipStub />
            <CallsStub />
            <PayStub amount={d.amount} />
            <DeliveryStub />
            <DealItems dealId={id} />
            <DealTasks dealId={id} />
            <DealDocuments dealId={id} />
          </div>

          {/* RIGHT — клиент / постоянный / переписка / связанные / действия */}
          <div className="min-w-0 space-y-4">
            <DealContacts dealId={id} />
            <RegStub />
            <DealMessages dealId={id} />
            <LinkedStub />
            <DealApprovals dealId={id} />
            <DealActions dealId={id} focus={d.focus} starred={d.starred} priority={d.priority} />
            <Card className="px-[18px] py-[14px]">
              <div className="mb-2 text-[13.5px] font-bold text-ink">Связь с клиентом</div>
              <ChannelButtons dealId={id} />
            </Card>
          </div>
        </div>
      </div>
    </div>
  );
}

// ── вспомогательные подкомпоненты страницы (server, без хуков) ───────────────────

function Metrics({ amount, closeDate }: { amount: number; closeDate: string }) {
  // TODO(SALES): cost/profit/margin/probability — из d.pricing.* (см. types.ts расширение).
  const cells: { label: string; value: string; tone?: "money" }[] = [
    { label: "Сумма", value: formatByn(amount) },
    { label: "Себестоимость", value: "—" },
    { label: "Прибыль", value: "—", tone: "money" },
    { label: "Маржа", value: "—" },
    { label: "Вероятность", value: "—" },
    { label: "Закрытие", value: closeDate || "—" },
  ];
  return (
    <div className="mt-2.5 flex flex-wrap overflow-hidden rounded-[10px] border border-line">
      {cells.map((c, i) => (
        <div
          key={c.label}
          className={`flex min-w-[150px] flex-1 flex-wrap items-baseline gap-1.5 px-3.5 py-[7px] ${
            i < cells.length - 1 ? "border-r border-line" : ""
          }`}
        >
          <div className="text-[11px] uppercase tracking-wide text-muted">{c.label}</div>
          <div
            className={`text-[15px] font-extrabold tabular-nums ${
              c.tone === "money" ? "text-money" : "text-ink"
            }`}
          >
            {c.value}
          </div>
        </div>
      ))}
    </div>
  );
}

function Stages({ currentIdx }: { currentIdx: number }) {
  // <ol>/<li> вместо role="list" — настоящая семантика упорядоченного списка.
  // Цвет текущего узла — токен stage.prop (из tailwind config), не raw amber.
  return (
    <ol aria-label="Стадии воронки продаж" className="relative mt-3 flex list-none items-start">
      {STAGES.map((label, i) => {
        const done = i < currentIdx;
        const cur = i === currentIdx;
        const nodeBg = done
          ? "bg-accent"
          : cur
            ? "bg-stage-prop ring-4 ring-stage-prop/20"
            : "bg-line-strong";
        const lineBg = done ? "bg-accent" : "bg-line";
        const txt = done || cur ? "text-ink font-semibold" : "text-faint";
        return (
          <li
            key={label}
            aria-current={cur ? "step" : undefined}
            className="relative min-w-0 flex-1 text-center"
          >
            {i < STAGES.length - 1 && (
              <div className={`absolute left-1/2 top-2 h-0.5 w-full ${lineBg}`} aria-hidden />
            )}
            <div
              className={`relative z-10 mx-auto flex h-[17px] w-[17px] items-center justify-center rounded-full text-[9px] font-bold text-white ${nodeBg}`}
              aria-hidden
            >
              {done ? "✓" : i + 1}
            </div>
            <div className={`mt-1 truncate px-0.5 text-[10px] leading-tight ${txt}`} title={label}>
              {label}
            </div>
          </li>
        );
      })}
    </ol>
  );
}

function PanelHeader({ icon, title }: { icon: string; title: string }) {
  return (
    <div className="flex items-center gap-1.5 border-b border-line px-[18px] py-3 text-[13.5px] font-bold text-ink">
      <span aria-hidden>{icon}</span>
      <span>{title}</span>
    </div>
  );
}

function StubNote({ children }: { children: React.ReactNode }) {
  return (
    <div className="rounded-lg bg-sunken px-3 py-2 text-[12px] text-muted">
      <span className="font-semibold text-faint">нет данных · </span>
      {children}
    </div>
  );
}

function NextStepStub({
  nextStep,
  datetime,
  contact,
}: {
  nextStep: string;
  datetime: string;
  contact: string;
}) {
  // datetime — точное время следующего шага (DealDetail.datetime), НЕ dealDate (дата закрытия).
  return (
    <Card>
      <PanelHeader icon="⏭" title="Следующий шаг" />
      <div className="space-y-2 px-[18px] py-[14px]">
        <div className="text-[13.5px] font-semibold text-ink">{nextStep || "—"}</div>
        <div className="flex flex-wrap gap-x-4 gap-y-1 text-[12px] text-muted">
          <span>
            <span aria-hidden>🕒</span> {datetime || "когда — не задано"}
          </span>
          <span>
            <span aria-hidden>👤</span> {contact || "ответственный не назначен"}
          </span>
        </div>
      </div>
    </Card>
  );
}

function ShipStub() {
  // STUB: «🚚 Сквозная машина / отгрузка» — три источника данных:
  //   logistics (рейс / ETA / route), 1С OData (резерв / статус склада),
  //   procurement/ZAK (сквозной груз нескольких сделок одним рейсом).
  return (
    <Card>
      <PanelHeader icon="🚚" title="Сквозная машина / отгрузка" />
      <div className="space-y-2 px-[18px] py-[14px]">
        <ul className="space-y-1 text-[12px] text-muted">
          <li>
            <span aria-hidden>🚚</span>{" "}
            <b className="text-ink">Рейс / ETA / маршрут</b> — модуль <code>logistics</code>
          </li>
          <li>
            <span aria-hidden>📦</span>{" "}
            <b className="text-ink">Резерв / статус склада</b> — 1С OData (источник истины, см.
            memory <code>invoice-1c-reserve-shipment</code>)
          </li>
          <li>
            <span aria-hidden>🔗</span>{" "}
            <b className="text-ink">Сквозной груз нескольких сделок</b> — модуль{" "}
            <code>procurement</code> (ZAK)
          </li>
        </ul>
        <StubNote>
          подключим, когда бэкенд начнёт отдавать{" "}
          <code>ship.{`{tripId, eta, route, reserve1cDocId, warehouseStatus, cargoTripDealIds}`}</code>{" "}
          в DealDetail.
        </StubNote>
      </div>
    </Card>
  );
}

function CallsStub() {
  // STUB: «📞 Звонки и транскрибация» — отдельный фид (не часть DealDetail).
  // Источник: Bitrix24-коннектор + faster-whisper large-v3 → comm_call
  // (memory: bitrix-connector-call-kb, controller-op-hr-spec).
  return (
    <Card>
      <PanelHeader icon="📞" title="Звонки и транскрибация" />
      <div className="space-y-2 px-[18px] py-[14px]">
        <div className="text-[12px] text-muted">
          плеер · авто-теги (сигналы, возражения) · sentiment · извлечённые договорённости ·
          построчная транскрипция.
        </div>
        <StubNote>
          импорт из Bitrix24 (исторические звонки), транскрипция локально faster-whisper large-v3 →{" "}
          <code>comm_call</code>; подключим отдельным фидом по сделке (не через DealDetail).
        </StubNote>
      </div>
    </Card>
  );
}

function PayStub({ amount }: { amount: number }) {
  // STUB: «к оплате» — из счёта ERP; «оплачено» — факт из 1С (банк/касса).
  // Прогресс-бар: при amount === 0 рисуем 0% (защита от деления на ноль при оживлении).
  return (
    <Card>
      <PanelHeader icon="💵" title="Оплата и деньги" />
      <div className="space-y-2 px-[18px] py-[14px]">
        <div className="grid grid-cols-2 gap-2.5">
          <div className="rounded-[10px] bg-sunken px-3 py-2.5">
            <div className="text-[11px] text-muted">К оплате</div>
            <div className="mt-0.5 text-[16px] font-extrabold tabular-nums text-ink">
              {formatByn(amount)}
            </div>
            <div className="mt-0.5 text-[10px] text-faint">из счёта ERP</div>
          </div>
          <div className="rounded-[10px] bg-sunken px-3 py-2.5">
            <div className="text-[11px] text-muted">Оплачено</div>
            <div className="mt-0.5 text-[16px] font-extrabold tabular-nums text-faint">—</div>
            <div className="mt-0.5 text-[10px] text-faint">из 1С (банк/касса)</div>
          </div>
        </div>
        <div className="h-[9px] overflow-hidden rounded-full bg-sunken" aria-hidden>
          <div className="h-full bg-money" style={{ width: "0%" }} />
        </div>
        <StubNote>
          подключим, когда payments появятся в API (<code>pay.invoiced</code> из ERP,{" "}
          <code>pay.paid</code> из 1С-фида).
        </StubNote>
      </div>
    </Card>
  );
}

function DeliveryStub() {
  // STUB: без визуально-«выбранной» кнопки (a11y: имитация selected без aria-checked сбивает SR).
  return (
    <Card>
      <PanelHeader icon="📦" title="Доставка" />
      <div className="space-y-2 px-[18px] py-[14px]">
        <div className="flex gap-2">
          {["Самовывоз", "Доставка по адресу", "Наша машина"].map((opt) => (
            <button
              key={opt}
              type="button"
              disabled
              className="flex-1 rounded-[9px] border border-line bg-surface px-2 py-2 text-[12.5px] font-semibold text-muted disabled:cursor-not-allowed disabled:opacity-80"
            >
              {opt}
            </button>
          ))}
        </div>
        <StubNote>
          метод / адрес / дата — CRM (ввод продавцом); склад отгрузки — справочник WMS
          (синхронизирован с 1С, резерв создаётся в 1С); рейс / машина — модуль{" "}
          <code>logistics</code>.
        </StubNote>
      </div>
    </Card>
  );
}

function RegStub() {
  // STUB: «★ Постоянный клиент». В прототипе условно рендерится при d.reg=true.
  // TODO: показывать только при d.regular?.isRegular; пока всегда виден с note.
  return (
    <Card>
      <PanelHeader icon="★" title="Постоянный клиент" />
      <div className="space-y-2 px-[18px] py-[14px]">
        <div className="text-[11px] text-faint">
          плашка будет показываться только для постоянных клиентов —{" "}
          <code>d.regular?.isRegular === true</code>
        </div>
        <StubNote>
          счётчик заказов — из CRM (<code>sales.deal</code>); LTV / средний чек — из 1С (реализации).
          Подключим, когда LTV-витрина начнёт отдавать regular-флаг.
        </StubNote>
      </div>
    </Card>
  );
}

function LinkedStub() {
  return (
    <Card>
      <PanelHeader icon="🔗" title="Сделки клиента" />
      <div className="px-[18px] py-[14px]">
        <StubNote>
          другие сделки контрагента — запросим по <code>counterparty.id</code> (тот же ключ, что в
          MDM / 1С); при <code>merged_into_id != null</code> покажем плашку «контрагент слит».
        </StubNote>
      </div>
    </Card>
  );
}
