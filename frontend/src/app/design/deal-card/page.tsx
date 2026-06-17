import { Card, CardHeader, CardBody, Badge, Button } from "@/components/ui";
import {
  Phone, Sparkles, CreditCard, Send, Link2, Check, FileText, Truck,
  Mail, MessageSquare, Play, Star, ArrowRight,
} from "lucide-react";

/**
 * ДЕМО (не продакшн): полная карточка сделки (аналог sales-card-full.html)
 * на примитивах components/ui + токены Stripe/Notion, по приоритетам платформы:
 * маржа — №1 (на видном месте), опасные действия отделены — №2.
 * Реальные экраны не тронуты. Открыть: /design/deal-card
 */

const items = [
  { name: "АКБ 6СТ-190", sub: "Минск · свободно 40", qty: 12, price: "3 600", margin: "+24%", sum: "43 200" },
  { name: "Доставка по Минску", sub: "авто рейса", qty: 1, price: "600", margin: "+40%", sum: "600" },
  { name: "Утилизация старых АКБ", sub: "допуслуга", qty: 12, price: "250", margin: "+62%", sum: "3 000" },
];

const stages = ["Новая", "В работе", "Квалиф.", "Цена запр.", "Есть цена", "Встреча", "Счёт", "Защищён", "Договор"];
const curStage = 6; // «Счёт»

const docs = [
  { name: "Счёт СЧ-0462", sub: "от 14.06 · 46 800 BYN", tone: "emerald" as const, label: "Проведён" },
  { name: "Договор поставки ДГ-0125", sub: "черновик · ждёт подписи", tone: "amber" as const, label: "Черновик" },
  { name: "Заказ-наряд ЗН-0207", sub: "комплектация и отгрузка", tone: "accent" as const, label: "В работе" },
  { name: "ТТН (отгрузка)", sub: "формирует логистика · при отгрузке", tone: "slate" as const, label: "При отгрузке" },
  { name: "Спецификация", sub: "не создана", tone: "slate" as const, label: "Нет" },
  { name: "Акт приёма-передачи", sub: "после доставки 18.06", tone: "slate" as const, label: "Нет" },
];

const contacts = [
  { name: "Ткачёв Виктор Анатольевич", role: "Главный инженер · ЛПР", phone: "+375 29 612-44-18", main: true },
  { name: "Гурко Елена Сергеевна", role: "Специалист отдела снабжения", phone: "+375 29 555-10-02", main: false },
];

// блок звонка с транскрибацией
const call = {
  meta: "Исходящий · 09.06 14:35 · 4:12 · позитивный",
  talkMgr: 45,
  talkCli: 55,
  tags: ["📈 buying signal: парк вырос", "💡 повод к допродаже"],
  summary:
    "Клиент подтвердил готовность к поставке, согласовал дату доставки 18.06. Упомянул, что парк вырос до 40 машин.",
  extract: [
    "🤝 Договорённость: доставка 18.06 к 14:00",
    "✅ Задача: прислать трек рейса утром 14.06",
    "💡 Допродажа: парк вырос 38→40 — предложить +2 АКБ и ЗУ",
  ],
};

const tasks = [
  { t: "Постпродажа: позвонить, всё ли ок по поставке", m: "20.06 (+2 дня после доставки)", kind: "Звонок", done: false },
  { t: "Поставить напоминание о перезаказе", m: "~25.08 (за 2 нед. до цикла)", kind: "Авто", done: false },
  { t: "Подписать акт приёма-передачи", m: "после доставки 18.06", kind: "Документ", done: false },
  { t: "Согласовать договор у юриста", m: "выполнено 02.06", kind: "Документ", done: true },
];

const timeline = [
  { type: "ship" as const, t: "Рейс TR-0418 отправлен поставщиком", m: "логистика · 14.06 09:10" },
  { type: "call" as const, t: "Исходящий звонок · 4:12 · позитивный", m: "Сидоров К. ↔ Ткачёв В.А. · 09.06 14:35" },
  { type: "pay" as const, t: "Предоплата 46 800 BYN зачислена", m: "финансы · 06.06 11:40" },
  { type: "stage" as const, t: "Стадия → Договор / предоплата", m: "Сидоров К. · 05.06 16:20" },
  { type: "note" as const, t: "ЛПР — гл.инженер, решение принимает он", m: "Сидоров К. · 28.05" },
];

const reg = { orders: 7, interval: "~90 дн", last: "12.03.2026", avg: "43 200 BYN", trend: "↗ +8%" };

const linked = [
  { n: "CRM-0815 · поставка 2025", sum: "39 800 BYN", label: "выиграна" },
  { n: "CRM-0640 · поставка 2024", sum: "36 400 BYN", label: "выиграна" },
];

const evDot: Record<string, string> = { ship: "#B45309", call: "#0E9384", pay: "#0F9D58", stage: "#635BFF", note: "#7C3AED" };

export default function DealCardDemoPage() {
  return (
    <main className="mx-auto max-w-[1340px] space-y-4 p-6">
      <p className="text-[11px] font-semibold uppercase tracking-wide text-faint">
        Демо · полная карточка сделки на примитивах
      </p>

      {/* ШАПКА */}
      <Card className="p-5">
        <div className="flex flex-wrap items-start gap-3">
          <div>
            <div className="text-xs font-semibold tabular-nums text-faint">CRM-1029 · в работе 11 дн</div>
            <h1 className="mt-0.5 text-xl font-bold tracking-tight">ООО «БелТранс» — поставка АКБ</h1>
            <p className="mt-0.5 text-[12.5px] text-muted">Аккумуляторные батареи 6СТ-190 · 12 шт · рейс CN→MSK</p>
            <div className="mt-2 flex flex-wrap gap-1.5">
              <Badge tone="emerald">★ Постоянный клиент</Badge>
              <Badge tone="red">Высокий приоритет</Badge>
              <Badge tone="amber">🚚 Едет в машине</Badge>
              <Badge tone="slate">4 дня в стадии «Счёт»</Badge>
            </div>
          </div>
          <div className="ml-auto flex gap-2">
            <Button variant="call" size="sm" icon={<Phone />}>Позвонить</Button>
            <Button variant="violet" size="sm" icon={<Sparkles />}>Спросить AI</Button>
          </div>
        </div>

        {/* ДЕНЬГИ: маржа — главное число (№1) */}
        <div className="mt-4 grid grid-cols-2 overflow-hidden rounded-xl border border-line bg-sunken sm:grid-cols-3 lg:grid-cols-5">
          <div className="bg-money-soft p-3.5 lg:col-span-1">
            <div className="flex items-center gap-1 text-[10px] font-bold uppercase tracking-wide text-money">💰 Маржа сделки</div>
            <div className="mt-1 text-2xl font-bold tabular-nums tracking-tight text-money">+12 400 BYN</div>
            <div className="text-[11px] font-medium text-[#3f7a5a]">26.5% · норма ≥ 18%</div>
          </div>
          <MoneyCell label="Сумма" value="46 800" sub="счёт СЧ-0462 · BYN" />
          <MoneyCell label="Оплачено" value="20 000" sub="43% · аванс" valueClass="text-money" />
          <MoneyCell label="К доплате" value="26 800" sub="остаток до отгрузки" />
          <div className="bg-[#FCF1DD] p-3.5">
            <div className="text-[10px] font-bold uppercase tracking-wide text-[#B45309]">🚚 Товар приедет</div>
            <div className="mt-1 text-lg font-bold tabular-nums text-[#8a4a0a]">18.06</div>
            <div className="text-[11px] text-[#B45309]">рейс CN→MSK · резерв до 19.06</div>
          </div>
        </div>

        {/* стадии */}
        <div className="mt-4 flex items-start overflow-x-auto pb-1">
          {stages.map((s, i) => (
            <div key={s} className="relative min-w-[64px] flex-1 text-center">
              {i < stages.length - 1 && (
                <div
                  className="absolute left-1/2 top-[9px] -z-0 h-0.5 w-full"
                  style={{ background: i < curStage ? "#635BFF" : "#E2E2E8" }}
                />
              )}
              <div
                className="relative z-10 mx-auto flex size-[19px] items-center justify-center rounded-full text-[9px] font-bold text-white"
                style={{
                  background: i < curStage ? "#635BFF" : i === curStage ? "#B45309" : "#E4E4EA",
                  boxShadow: i === curStage ? "0 0 0 4px rgba(180,83,9,.16)" : undefined,
                }}
              >
                {i < curStage ? "✓" : i + 1}
              </div>
              <div className={`mt-1.5 text-[10px] leading-tight ${i <= curStage ? "font-semibold text-ink" : "text-faint"}`}>
                {s}
              </div>
            </div>
          ))}
        </div>
      </Card>

      {/* ACTION-BAR: следующее действие → деньги */}
      <Card className="border-[#E2D9FB] bg-gradient-to-b from-[#FBFAFF] to-[#F6F4FF]">
        <div className="flex flex-wrap items-center gap-4 p-5">
          <div className="min-w-[280px] flex-1">
            <div className="flex items-center gap-1.5 text-[10px] font-bold uppercase tracking-wide text-[#7C3AED]">
              <Sparkles className="size-3" /> Следующее лучшее действие · AI
            </div>
            <div className="mt-1 text-[17px] font-bold leading-tight">Дожать доплату 26 800 BYN и отправить договор</div>
            <p className="mt-1 text-[12.5px] leading-snug text-[#6d5a9c]">
              Аванс 43% получен. До отгрузки 18.06 закрыть остаток <b className="text-money">26 800 BYN</b> — иначе товар
              уедет неоплаченным. Прибыль собственнику — <b className="text-money">+12 400 BYN</b>.
            </p>
          </div>
          <div className="flex flex-shrink-0 flex-wrap gap-2">
            <Button variant="money" size="lg" icon={<CreditCard />}>Запросить доплату</Button>
            <Button variant="ghost">Позже</Button>
          </div>
        </div>
        <div className="flex flex-wrap items-center gap-2 border-t border-[#EBE3FB] bg-white/50 px-5 py-2.5">
          <span className="mr-0.5 text-[10.5px] font-bold uppercase tracking-wide text-faint">Стадия «Счёт»:</span>
          <Button variant="primary" size="sm" icon={<Send />}>Отправить счёт</Button>
          <Button variant="secondary" size="sm" icon={<Link2 />}>Договор на подпись</Button>
          <Button variant="call" size="sm" icon={<Phone />}>Позвонить ЛПР</Button>
          <Button variant="money" size="sm" icon={<Check />} className="ml-auto">Перевести в «Защищён»</Button>
        </div>
      </Card>

      <div className="grid gap-4 lg:grid-cols-[1.6fr_1fr]">
        <div className="space-y-4">
          {/* СОСТАВ + СКИДКА (безопасность №2) */}
          <Card>
            <CardHeader>📦 Состав счёта и маржа<span className="ml-auto text-xs font-semibold text-accent-ink">＋ со склада</span></CardHeader>
            <CardBody>
              <table className="w-full text-[13px]">
                <thead>
                  <tr className="text-[10px] uppercase tracking-wide text-faint">
                    <th className="pb-2 text-left font-semibold">Позиция</th>
                    <th className="pb-2 text-right font-semibold">Кол-во</th>
                    <th className="pb-2 text-right font-semibold">Цена</th>
                    <th className="pb-2 text-right font-semibold">Маржа</th>
                    <th className="pb-2 text-right font-semibold">Сумма</th>
                  </tr>
                </thead>
                <tbody>
                  {items.map((it) => (
                    <tr key={it.name} className="border-t border-line">
                      <td className="py-2">
                        <div className="font-medium">{it.name}</div>
                        <div className="text-[11px] text-faint">{it.sub}</div>
                      </td>
                      <td className="py-2 text-right tabular-nums">{it.qty}</td>
                      <td className="py-2 text-right tabular-nums">{it.price}</td>
                      <td className="py-2 text-right text-[12px] font-bold tabular-nums text-money">{it.margin}</td>
                      <td className="py-2 text-right tabular-nums">{it.sum}</td>
                    </tr>
                  ))}
                  <tr className="border-t border-line-strong font-bold">
                    <td className="py-2.5">Итого · маржа 26.5%</td>
                    <td /><td />
                    <td className="py-2.5 text-right text-[13px] tabular-nums text-money">+12 400</td>
                    <td className="py-2.5 text-right tabular-nums">46 800</td>
                  </tr>
                </tbody>
              </table>

              {/* скидка → влияние на прибыль + порог (безопасность) */}
              <div className="mt-3 rounded-xl border border-line bg-sunken p-3.5">
                <div className="flex flex-wrap items-center gap-2.5">
                  <span className="text-xs font-semibold text-muted">Скидка на счёт</span>
                  <span className="w-16 rounded-lg border border-line-strong px-2 py-1.5 text-right text-[13px] tabular-nums">15</span>
                  <span>%</span>
                  <span className="text-[11.5px] text-muted">порог без согласования — до 10%</span>
                </div>
                <div className="mt-2.5 flex justify-between text-[12.5px]">
                  <span className="text-muted">При скидке 15% прибыль:</span>
                  <span>
                    <b className="tabular-nums text-money">+12 400</b> <span className="text-faint">→</span>{" "}
                    <b className="tabular-nums text-[#DC2626]">+5 380 BYN</b>
                  </span>
                </div>
                <div className="mt-2.5 flex items-center gap-1.5 rounded-lg bg-[#FCEAEA] px-3 py-2 text-[12px] font-medium text-[#DC2626]">
                  🔒 Скидка 15% превышает порог 10% — <b>требует согласования РОПа</b>. Отправка счёта заблокирована.
                </div>
              </div>
            </CardBody>
          </Card>

          {/* КАССА */}
          <Card>
            <CardHeader>💰 Касса по сделке<span className="ml-auto text-[11.5px] font-medium text-muted">landed cost 34 400 BYN</span></CardHeader>
            <CardBody>
              <div className="grid grid-cols-3 gap-2.5">
                <PayCell l="Оплачено" v="20 000" green />
                <PayCell l="К доплате" v="26 800" />
                <PayCell l="Прибыль" v="+12 400" green />
              </div>
              <div className="my-3 h-2.5 overflow-hidden rounded-full bg-[#EEEEF1]">
                <div className="h-full rounded-full bg-money" style={{ width: "43%" }} />
              </div>
              <div className="flex items-center gap-1.5 rounded-lg bg-[#FCF1DD] px-3 py-2 text-[11.5px] text-[#B45309]">
                🔒 Отгрузка при неполной оплате — только с подтверждения РОПа. Остаток не закрыт.
              </div>
              <div className="mt-3 flex flex-wrap gap-2">
                <Button variant="money" size="sm" icon={<CreditCard />}>Запросить доплату</Button>
                <Button variant="secondary" size="sm">Сверка платежей</Button>
              </div>
            </CardBody>
          </Card>

          {/* Задачи */}
          <Card>
            <CardHeader>✅ Задачи<span className="ml-auto text-[11.5px] font-medium text-muted">{tasks.filter((t) => !t.done).length} активных</span></CardHeader>
            <CardBody>
              {tasks.map((t) => (
                <div key={t.t} className="flex items-start gap-2.5 border-t border-line py-2.5 first:border-t-0">
                  <span
                    className={`mt-0.5 flex size-[18px] flex-shrink-0 items-center justify-center rounded-md border-2 ${
                      t.done ? "border-money bg-money text-white" : "border-[#CBD5E1]"
                    }`}
                  >
                    {t.done && <Check className="size-3" />}
                  </span>
                  <div className="min-w-0 flex-1">
                    <div className={`text-[13px] ${t.done ? "text-faint line-through" : ""}`}>{t.t}</div>
                    <div className="text-[11px] text-muted">{t.m}</div>
                  </div>
                  <Badge tone="slate">{t.kind}</Badge>
                </div>
              ))}
            </CardBody>
          </Card>
        </div>

        <div className="space-y-4">
          {/* AI на деньги */}
          <Card className="border-[#E4DBFB]">
            <CardHeader className="text-[#5B21B6]">✦ AI · возможности заработать</CardHeader>
            <CardBody className="space-y-2.5">
              <p className="text-[12.5px] leading-snug text-[#3b2d63]">Клиент платит вовремя, парк вырос до 40 машин.</p>
              <div className="rounded-xl border border-[#E4DBFB] bg-[#F2EBFE] p-3">
                <div className="text-[10px] font-bold uppercase tracking-wide text-[#7C3AED]">💡 Допродажа</div>
                <div className="mt-1 text-[12.5px] text-[#3b2d63]">
                  Годовой контракт на обслуживание — <b className="text-money">+48 000 BYN/год</b>.
                </div>
              </div>
              <Button variant="violet" size="sm" block icon={<Sparkles />}>Предложить контракт</Button>
            </CardBody>
          </Card>

          {/* Контакты */}
          <Card>
            <CardHeader>👤 Контакты<span className="ml-auto text-xs font-semibold text-accent-ink">＋</span></CardHeader>
            <CardBody>
              {contacts.map((c) => (
                <div key={c.name} className="flex items-start gap-2.5 border-t border-line py-2.5 first:border-t-0">
                  <div
                    className={`flex size-9 flex-shrink-0 items-center justify-center rounded-[10px] text-[12.5px] font-bold ${
                      c.main ? "bg-money-soft text-money" : "bg-accent-soft text-accent-ink"
                    }`}
                  >
                    {c.name.split(" ")[0][0]}
                    {c.name.split(" ")[1]?.[0]}
                  </div>
                  <div className="min-w-0 flex-1">
                    <div className="flex flex-wrap items-center gap-1.5 text-[13px] font-semibold">
                      {c.name}
                      {c.main && <Badge tone="emerald">ЛПР</Badge>}
                    </div>
                    <div className="text-[11.5px] text-muted">{c.role}</div>
                    <div className="mt-0.5 text-[12px] tabular-nums text-[#334155]">{c.phone}</div>
                    <div className="mt-1.5 flex gap-1.5">
                      <Button variant="call" size="sm" icon={<Phone />}>Звонок</Button>
                      <Button variant="secondary" size="sm" icon={<Mail />} aria-label="email" />
                      <Button variant="secondary" size="sm" icon={<MessageSquare />} aria-label="чат" />
                    </div>
                  </div>
                </div>
              ))}
            </CardBody>
          </Card>

          {/* Последний звонок + транскрибация */}
          <Card>
            <CardHeader>📞 Последний звонок<span className="ml-auto text-[11.5px] font-medium text-muted">{call.meta}</span></CardHeader>
            <CardBody className="space-y-3">
              <div className="flex flex-wrap items-center gap-2">
                <Badge tone="teal">Исходящий</Badge>
                <Badge tone="emerald">Позитив</Badge>
              </div>
              {/* talk-ratio */}
              <div className="flex items-center gap-2 text-[11.5px] text-muted">
                <span>Менеджер {call.talkMgr}%</span>
                <div className="flex h-[7px] flex-1 overflow-hidden rounded-full bg-[#EEF0F2]">
                  <div className="bg-accent" style={{ width: `${call.talkMgr}%` }} />
                  <div className="bg-money" style={{ width: `${call.talkCli}%` }} />
                </div>
                <span>Клиент {call.talkCli}%</span>
              </div>
              <div className="rounded-xl border border-[#E4DBFB] bg-[#F2EBFE] p-3">
                <div className="text-[10px] font-bold uppercase tracking-wide text-[#7C3AED]">✦ Итог звонка · AI</div>
                <div className="mt-1.5 text-[12.5px] leading-snug text-[#3b2d63]">{call.summary}</div>
                <div className="mt-2 space-y-1">
                  {call.extract.map((e) => (
                    <div key={e} className="text-[12px] text-[#3b2d63]">{e}</div>
                  ))}
                </div>
                <div className="mt-2 flex flex-wrap gap-1.5">
                  {call.tags.map((t) => (
                    <Badge key={t} tone="violet">{t}</Badge>
                  ))}
                </div>
              </div>
              <Button variant="ghost" size="sm" icon={<Play />}>Прослушать · транскрипт</Button>
            </CardBody>
          </Card>

          {/* Постоянный клиент */}
          <Card>
            <CardHeader><Star className="size-4 text-[#F59E0B]" /> Постоянный клиент</CardHeader>
            <CardBody>
              <div className="grid grid-cols-2 gap-x-4 gap-y-1.5 text-[12.5px]">
                <Kv k="Заказов" v={`${reg.orders}`} />
                <Kv k="Частота" v={reg.interval} />
                <Kv k="Последний" v={reg.last} />
                <Kv k="Средний чек" v={reg.avg} />
                <Kv k="Тренд чека" v={reg.trend} green />
              </div>
              <div className="mt-3 rounded-xl border border-[#A7F3D0] bg-[#ECFDF5] p-3 text-[12.5px] leading-snug text-[#065F46]">
                💡 Ни разу не брал ЗУ и тестеры. Парк 38→40 → предложить <b>+2 АКБ и комплект ЗУ</b>. Чек можно поднять ~12%.
              </div>
            </CardBody>
          </Card>

          {/* Документы */}
          <Card>
            <CardHeader>📄 Документы<span className="ml-auto text-[11.5px] font-medium text-muted">пакет по сделке</span></CardHeader>
            <CardBody>
              {docs.map((d) => (
                <div key={d.name} className="flex items-center gap-2.5 border-t border-line py-2.5 first:border-t-0">
                  <div className="min-w-0 flex-1">
                    <div className="text-[13px] font-medium">{d.name}</div>
                    <div className="text-[11px] text-faint">{d.sub}</div>
                  </div>
                  <Badge tone={d.tone}>{d.label}</Badge>
                </div>
              ))}
              <div className="mt-3 flex flex-wrap gap-1.5 border-t border-dashed border-line-strong pt-3">
                <span className="w-full text-[10.5px] font-bold uppercase tracking-wide text-faint">Создать документ</span>
                {["Счёт", "Договор", "Спецификация", "Заказ-наряд", "ТТН", "Акт", "КП"].map((t) => (
                  <Button key={t} variant="secondary" size="sm" icon={<FileText />}>{t}</Button>
                ))}
              </div>
            </CardBody>
          </Card>

          {/* Отгрузка */}
          <Card>
            <CardHeader><Truck className="size-4" /> Отгрузка · рейс CN→MSK</CardHeader>
            <CardBody>
              <div className="flex flex-wrap items-center gap-2.5 rounded-xl border border-[#F0D9A8] bg-[#FCF1DD] px-3 py-2.5">
                <div>
                  <div className="text-[12.5px] font-bold text-[#8a4a0a]">Машина MAR-218 в пути</div>
                  <div className="text-[11px] text-[#B45309]">Граница пройдена · едет в Минск</div>
                </div>
                <div className="ml-auto text-right">
                  <div className="text-[9.5px] font-semibold uppercase text-[#B45309]">ETA</div>
                  <div className="text-[15px] font-bold tabular-nums text-[#8a4a0a]">18.06</div>
                </div>
              </div>
            </CardBody>
          </Card>
        </div>
      </div>

      {/* НИЖНЯЯ ПОЛОСА: Хронология + Сделки клиента */}
      <div className="grid gap-4 lg:grid-cols-[1.6fr_1fr]">
        <Card>
          <CardHeader>🕑 Хронология</CardHeader>
          <CardBody>
            <div className="relative space-y-3 pl-5 before:absolute before:bottom-1 before:left-[5px] before:top-1 before:w-0.5 before:bg-line">
              {timeline.map((e) => (
                <div key={e.t} className="relative">
                  <span
                    className="absolute -left-5 top-0.5 size-[11px] rounded-full border-2 border-white"
                    style={{ background: evDot[e.type], boxShadow: `0 0 0 1px ${evDot[e.type]}` }}
                  />
                  <div className="text-[12.5px] font-semibold">{e.t}</div>
                  <div className="text-[11px] text-muted">{e.m}</div>
                </div>
              ))}
            </div>
          </CardBody>
        </Card>

        <Card>
          <CardHeader>🔗 Сделки клиента<span className="ml-auto text-[11.5px] font-medium text-muted">история</span></CardHeader>
          <CardBody>
            {linked.map((l) => (
              <button
                key={l.n}
                className="flex w-full items-center justify-between gap-2 rounded-lg border-t border-line px-2 py-2.5 text-left transition-colors first:border-t-0 hover:bg-accent-soft"
              >
                <div>
                  <div className="text-[12.5px] font-medium">{l.n}</div>
                  <div className="text-[11px] tabular-nums text-muted">{l.sum}</div>
                </div>
                <span className="flex items-center gap-1.5">
                  <Badge tone="emerald">{l.label}</Badge>
                  <ArrowRight className="size-3.5 text-accent-ink" />
                </span>
              </button>
            ))}
          </CardBody>
        </Card>
      </div>
    </main>
  );
}

function Kv({ k, v, green }: { k: string; v: string; green?: boolean }) {
  return (
    <div className="flex justify-between gap-2">
      <span className="text-muted">{k}</span>
      <span className={`font-semibold tabular-nums ${green ? "text-money" : ""}`}>{v}</span>
    </div>
  );
}

function MoneyCell({ label, value, sub, valueClass = "" }: { label: string; value: string; sub: string; valueClass?: string }) {
  return (
    <div className="bg-surface p-3.5">
      <div className="text-[10px] font-bold uppercase tracking-wide text-faint">{label}</div>
      <div className={`mt-1 text-lg font-bold tabular-nums tracking-tight ${valueClass}`}>{value}</div>
      <div className="text-[11px] text-muted">{sub}</div>
    </div>
  );
}

function PayCell({ l, v, green }: { l: string; v: string; green?: boolean }) {
  return (
    <div className="rounded-xl border border-line bg-sunken p-3">
      <div className="text-[10.5px] font-semibold uppercase tracking-wide text-muted">{l}</div>
      <div className={`mt-0.5 text-base font-bold tabular-nums tracking-tight ${green ? "text-money" : ""}`}>{v}</div>
    </div>
  );
}
