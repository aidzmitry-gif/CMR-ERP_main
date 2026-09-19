# Официальный курс валюты для бухгалтерии

`core.services.nbrb` получает датированный официальный курс НБРБ и сохраняет
запись в `audit_log` с ключом `nbrb:<валюта>:<дата>`. В
доказательстве остаются исходный `official_rate`, `scale`, нормализованный курс,
дата и источник `NBRB`. Повторный запрос читает ту же квитанцию; другой ответ
НБРБ не переписывает уже использованный курс через этот сервис. При чтении
проверяются валюта, дата, курс, масштаб, источник и нормализованное значение.
Повреждённая запись блокирует расчёт. Общий `audit_log` пока не защищён
от изменения на уровне БД; эта запись не заменяет неизменяемое основание проводки.

Доступны маршруты (при первом запросе сохраняется запись курса):

- `GET /system/fx/{currency}?on=YYYY-MM-DD` — получить официальный курс;
- `POST /system/fx/convert` — рассчитать сумму в BYN по этому курсу.

Сервис не использует демонстрационные таблицы и коммерческий резерв. Он не создаёт
бухгалтерскую проводку: бухгалтер переносит проверенные дату, масштаб, источник и
сумму в явный пакет проводки или реестр ВЭД/переоценки. Старый
`modules.finance.fx` остаётся управленческим историческим контуром и не импортируется
в `modules.accounting`.

Локальная проверка `tests/test_nbrb_cache_validation.py` включает точный разбор ответа,
повторное чтение и отказ при повреждённом кеше. Утверждённая учётная политика, production и закрытый месяц этим срезом не сертифицируются.

Проверка интеграции 13.09.2026: публичный GET к НБРБ для USD на 12.09.2026
вернул HTTP 200, курс 3.0197 и масштаб 1. Это разовая проверка доступности
и контракта ответа, не гарантия дальнейшей доступности.
Полная регистрация маршрута в приложении проверена под ролью finance:
кеширование, конвертация по масштабу, отказ неизвестной роли.
Некорректная валюта/будущая дата возвращают 422, недоступность курса — 503.

## 19 сентября 2026: prerequisites for full FX bank statements

Commit d104a14 fixes the double inversion of liability revaluation: foreign balances and their BYN book values are debit-positive for every account category. A USD100 credit balance at BYN300 revalued at3.20 requires Cr liability20 / Dr FX expense20. Falling rate2.80 reverses that direction. Existing test now checks actual account sides and gain/loss accounts for both directions;7FX workflow tests passed. New calculations use rule version fx-revaluation-v2; historical receipt replay remains unchanged. This is an arithmetic correction, not certification of the selected accounts or tax policy.

Unfinished prerequisites identified by bounded source review:

1. Revaluation preview currently selects foreign-currency lines, while earlier revaluation adjustments are BYN-only. Carrying-basis calculation must incorporate prior authenticated valuation adjustments by currency/position, including corrections, before repeated or next-month revaluation is accepted. Do not infer that the sign fix solves this.
2. Bank source dimensions currently contain per-operation bank_transaction_id and bank_statement. FX balances need a stable position identity (organization, ledger account, actual bank account/provider, currency and permanent analytical dimensions), with source identity retained separately as evidence. Grouping by full operation-specific dimensions would split one bank balance into unrelated positions.
3. LineInput requires a foreign line's BYN value to equal rounded original amount times documented rate/scale. Settlement carrying values must use explicit protected valuation adjustments; never fabricate an effective rate to fit a desired total.
4. Monetary cash revaluation and its report treatment need an explicit exchange-rate-effect representation. Existing generic cash-line reporting must not count valuation-only adjustments as receipts/payments. Current policy excludes cash accounts from revaluation; do not remove that guard prematurely.

Reuse existing immutable review/confirm receipts, policy gain/loss accounts, exact Fraction conversion, dated official-rate evidence, source ownership and period locks. Full FX ingestion/posting remains blocked until these accounting primitives have evidence; BYN imports remain available. Actual bank formats, policies and reconciled balances remain external acceptance inputs.

### Repeated valuation carrying basis: local implementation

New rule fx-revaluation-v3 includes prior posted valuation-only BYN lines in each original currency position. It verifies the immutable receipt digest, posting digest and actual ledger lines before attribution; the receipt and entry identifiers/digests become part of the next preview basis. Actual signed ledger amounts are used, including old wrong-sided liability adjustments, without changing historic records. A no-op receipt does not break the link to the latest real entry for a later correction. Unattributed BYN corrections of foreign source entries or valuation entries (including correction chains) block calculation rather than being silently assigned to a currency.

Ten targeted FX workflow tests passed: rising/falling rates, same-rate no-op, correction after no-op, next-month incremental amount, old wrong-sided history, damaged receipt rejection and unattributed correction rejection. This completes the receipt-backed repeated-valuation prerequisite locally; it does not yet implement FX bank position identity, settlement valuation allocation or cash-flow exchange effects. PostgreSQL verification of this new calculation remains a separate pending check.

### Dated valuation cutoff

Rule fx-revaluation-v4 selects foreign postings, prior valuation receipts/corrections, account versions and policy versions no later than the requested posting_date. A September15 calculation excludes September30 postings and September20 configuration changes. Two targeted cutoff cases passed; the ten existing FX workflow cases passed with the cutoff change. Historical receipts are unchanged. Implemented in the bank worktree while the integration a4157c6 verifier retained frozen source files.

### Currency positions in reports

Verified valuation-only BYN lines now contribute to the original currency position in trial balance and opening balances. Attribution reuses receipt/posting/ledger validation; no source line is changed. Drill-down movement currency identifies the position, ledger_currency retains BYN and valuation_only marks the adjustment; the account activity screen labels it Переоценка. Synthetic USD100/BYN300 plus valuation20 reports a single USD position with BYN320 and originalUSD100. Existing ledger/report checks passed25cases; the expanded position test passed both current-period and opening-balance cases. Cash FX valuation remains unsupported by policy; no exchange-effect cash-flow feature is claimed here.

The separate V3 PostgreSQL probe on a4157c6 passed registered0136 migration, repeated/no-op/corrected/next-month calculation, replay, actual old wrong-sided receipt and unknown correction rejection. Previous receipts/lines remained unchanged; owned probe DB cleaned. Evidence: reports/CRM-ERPNext-001/luna-fx-carrying-report.md. Dated cutoff was subsequently integrated as6c14947; that newer change is covered by its two local cutoff cases, not retroactively by the V3 probe.

### Monetary settlement valuation preview API

POST /accounting/organizations/{org_id}/fx-settlement/preview now calculates a read-only quote for an exact noncash monetary position: account, complete selected dimensions, foreign currency and as-of date. The latest approved policy must explicitly save settlement_allocation=proportional_carrying and settlement_rate_date=posting_date; existing policies have no inferred default and cannot use the new calculation until configured. Original and carrying balances come from ledger lines and verified prior valuation receipts. Positive amount must not exceed the position. Partial carrying value uses exact rational allocation rounded half-up; full settlement consumes the remaining carrying amount exactly. The documented rate must have the posting date. Preview returns source and receipt evidence, a basis digest, allocated book value, documentary value, remaining balances and configured exchange-result account/side.

The endpoint does not post, reserve, allocate a bank transaction or create a receipt; posting_available is explicitly false. Bank-side valuation, protected settlement posting, persistent payment allocation, policy UI and user-facing preview workflow remain outstanding. Six targeted API scenarios passed, including partial/full asset and liability quotes, missing-policy method, overpayment and prior revaluation. Existing12FX/cutoff cases passed after schema extension.
