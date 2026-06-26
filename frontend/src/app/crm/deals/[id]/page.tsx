import Link from "next/link";
import { ArrowLeft } from "lucide-react";
import { AppShell } from "@/components/app-shell";
import { ChannelButtons } from "@/components/channels";
import { DealActions } from "@/components/deal-actions";
import { DealAiAssistant } from "@/components/deal-ai-assistant";
import { DealApprovals } from "@/components/deal-approvals";
import { DealContacts } from "@/components/deal-contacts";
import { DealEditButton } from "@/components/deal-edit-button";
import { DealDocuments } from "@/components/deal-documents";
import { DealMetrics } from "@/components/deal-metrics";
import { DealItems } from "@/components/deal-items";
import { DealTasks } from "@/components/deal-tasks";
import { DealMessages } from "@/components/deal-messages";
import { PriorityBadge } from "@/components/priority-badge";
import { Button } from "@/components/ui/button";
import { Card, CardBody, CardHeader } from "@/components/ui/card";
import { fetchDealDetail } from "@/lib/api";
import { formatByn } from "@/lib/format";
import { currentRole } from "@/lib/role-server";
import { PROGRESSION_STAGES, STAGE_BY_ID } from "@/lib/sales-stages";
import type { DealDetail } from "@/lib/types";

export default async function DealDetailPage({ params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;
  const d = await fetchDealDetail(id, await currentRole());
  // Активная стадия — из бэка (DealDetail.stage.idx); fallback 0 для mock/без стадии.
  const stageIdx = d.stage?.idx ?? 0;

  return (
    <AppShell crumbs={["CRM", "Сделки", d.number || "сделка"]}>
      <div className="flex-1 overflow-y-auto bg-canvas text-ink">
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
                  TODO(Step B): вынести в <SourceTag source="mdm/1c" /> и переиспользовать
                  на других экранах (drawer-preview, board hover-card, leads-workspace). */}
              <div className="mt-1 flex flex-wrap items-center gap-2 text-[11px] text-faint">
                <span className="rounded-md bg-sunken px-1.5 py-0.5 font-semibold text-muted">
                  контрагент · из MDM / 1С
                </span>
                <span className="text-faint">УНП —</span>
              </div>
              <div className="mt-1.5 flex flex-wrap items-center gap-1.5">
                <PriorityBadge priority={d.priority} withIcon />
                {d.stage && <StageBadge stage={d.stage} />}
                {/* TODO(SALES): regular / temperature / ship-бейджи — ждут полей бэкенда */}
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

          <DealMetrics
            dealId={id}
            amount={d.amount}
            closeDate={d.expectedCloseDate || d.dealDate}
            stageId={d.stage?.id}
            probability={d.probability}
          />
          <Stages currentIdx={stageIdx} />
        </Card>

        {/* ── ОСНОВНАЯ СЕТКА: 1.5fr / 1fr; порядок блоков как в render() прототипа. ── */}
        {/* TODO(Step B): вынести stub-карточки в frontend/src/components/deal/ —
            drawer-preview и hover-card на доске собираются из тех же блоков. */}
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
    </AppShell>
  );
}

// ── вспомогательные подкомпоненты страницы (server, без хуков) ───────────────────

function Stages({ currentIdx }: { currentIdx: number }) {
  // <ol>/<li> вместо role="list" — настоящая семантика упорядоченного списка.
  // Цвет текущего узла — токен stage.prop (из tailwind config), не raw amber.
  return (
    <ol aria-label="Стадии воронки продаж" className="relative mt-3 flex list-none items-start">
      {PROGRESSION_STAGES.map((stage, i) => {
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
            key={stage.id}
            aria-current={cur ? "step" : undefined}
            className="relative min-w-0 flex-1 text-center"
          >
            {i < PROGRESSION_STAGES.length - 1 && (
              <div className={`absolute left-1/2 top-2 h-0.5 w-full ${lineBg}`} aria-hidden />
            )}
            <div
              className={`relative z-10 mx-auto flex h-[17px] w-[17px] items-center justify-center rounded-full text-[9px] font-bold text-white ${nodeBg}`}
              aria-hidden
            >
              {done ? "✓" : i + 1}
            </div>
            <div
              className={`mt-1 truncate px-0.5 text-[10px] leading-tight ${txt}`}
              title={stage.title}
            >
              {stage.title}
            </div>
          </li>
        );
      })}
    </ol>
  );
}

/** Бейдж активной стадии в шапке: канон-цвет + дней в стадии + «протухает» (SALES-43). */
function StageBadge({ stage }: { stage: NonNullable<DealDetail["stage"]> }) {
  const color = STAGE_BY_ID[stage.id]?.color ?? "#64748B";
  return (
    <span
      className="inline-flex items-center gap-1.5 rounded-md px-2 py-0.5 text-[11.5px] font-semibold"
      style={{ background: `${color}1A`, color }}
    >
      <span className="h-1.5 w-1.5 rounded-full" style={{ background: color }} aria-hidden />
      {stage.title}
      {stage.daysInStage != null && (
        <span className="font-normal opacity-80">· {stage.daysInStage} дн</span>
      )}
      {stage.isStale && (
        <span className="rounded bg-amber-500/20 px-1 text-[10px] font-bold text-amber-700 dark:text-amber-300">
          протухает
        </span>
      )}
    </span>
  );
}

/**
 * Тонкая обёртка над CardHeader из ui/card.tsx — даёт удобный (icon + title) API
 * для stub-карточек, при этом стиль шапки приходит из дизайн-системы (одна точка правки).
 */
function PanelHeader({ icon, title }: { icon: string; title: string }) {
  return (
    <CardHeader>
      <span aria-hidden>{icon}</span>
      <span>{title}</span>
    </CardHeader>
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
      <CardBody className="space-y-2">
        <div className="text-[13.5px] font-semibold text-ink">{nextStep || "—"}</div>
        <div className="flex flex-wrap gap-x-4 gap-y-1 text-[12px] text-muted">
          <span>
            <span aria-hidden>🕒</span> {datetime || "когда — не задано"}
          </span>
          <span>
            <span aria-hidden>👤</span> {contact || "ответственный не назначен"}
          </span>
        </div>
      </CardBody>
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
      <CardBody className="space-y-2">
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
      </CardBody>
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
      <CardBody className="space-y-2">
        <div className="text-[12px] text-muted">
          плеер · авто-теги (сигналы, возражения) · sentiment · извлечённые договорённости ·
          построчная транскрипция.
        </div>
        <StubNote>
          импорт из Bitrix24 (исторические звонки), транскрипция локально faster-whisper large-v3 →{" "}
          <code>comm_call</code>; подключим отдельным фидом по сделке (не через DealDetail).
        </StubNote>
      </CardBody>
    </Card>
  );
}

function PayStub({ amount }: { amount: number }) {
  // STUB: «к оплате» — из счёта ERP; «оплачено» — факт из 1С (банк/касса).
  // Прогресс-бар вернём, когда придёт pay.paid: бессмысленно держать пустой 0%-bar в DOM.
  return (
    <Card>
      <PanelHeader icon="💵" title="Оплата и деньги" />
      <CardBody className="space-y-2">
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
        <StubNote>
          подключим, когда payments появятся в API (<code>pay.invoiced</code> из ERP,{" "}
          <code>pay.paid</code> из 1С-фида).
        </StubNote>
      </CardBody>
    </Card>
  );
}

function DeliveryStub() {
  // STUB: без визуально-«выбранной» кнопки (a11y: имитация selected без aria-checked сбивает SR).
  return (
    <Card>
      <PanelHeader icon="📦" title="Доставка" />
      <CardBody className="space-y-2">
        <div className="flex gap-2">
          {["Самовывоз", "Доставка по адресу", "Наша машина"].map((opt) => (
            <Button key={opt} variant="secondary" size="sm" disabled className="flex-1">
              {opt}
            </Button>
          ))}
        </div>
        <StubNote>
          метод / адрес / дата — CRM (ввод продавцом); склад отгрузки — справочник WMS
          (синхронизирован с 1С, резерв создаётся в 1С); рейс / машина — модуль{" "}
          <code>logistics</code>.
        </StubNote>
      </CardBody>
    </Card>
  );
}

function RegStub() {
  // STUB: «★ Постоянный клиент». В прототипе условно рендерится при d.reg=true.
  // TODO: показывать только при d.regular?.isRegular; пока всегда виден с note.
  return (
    <Card>
      <PanelHeader icon="★" title="Постоянный клиент" />
      <CardBody className="space-y-2">
        <div className="text-[11px] text-faint">
          плашка будет показываться только для постоянных клиентов —{" "}
          <code>d.regular?.isRegular === true</code>
        </div>
        <StubNote>
          счётчик заказов — из CRM (<code>sales.deal</code>); LTV / средний чек — из 1С (реализации).
          Подключим, когда LTV-витрина начнёт отдавать regular-флаг.
        </StubNote>
      </CardBody>
    </Card>
  );
}

function LinkedStub() {
  return (
    <Card>
      <PanelHeader icon="🔗" title="Сделки клиента" />
      <CardBody>
        <StubNote>
          другие сделки контрагента — запросим по <code>counterparty.id</code> (тот же ключ, что в
          MDM / 1С); при <code>merged_into_id != null</code> покажем плашку «контрагент слит».
        </StubNote>
      </CardBody>
    </Card>
  );
}
