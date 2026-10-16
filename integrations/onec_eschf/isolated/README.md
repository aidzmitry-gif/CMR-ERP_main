# Локальная упаковка для точного будущего P2

Этот каталог не является готовой конфигурацией или разрешением запускать 1С.
Ни BSL-компиляция, ни COM/runtime, ни окончательные native bytes здесь не проверены.
Предыдущие `native_adapter.bsl`, `adapter.py`, `dependencies.json` остаются неизменными.

`package.py` принимает реальный будущий `Configuration.xml` с явно указанным SHA-256,
проверяет формат 2.11, имя/версию КА и единственный ChildObjects, вставляет один новый
CommonModule без повторной сериализации исходного XML. Неподдерживаемая форма отклоняется.
В новом локальном выходном каталоге появляются только изменённый Configuration.xml,
метаданные одного модуля, его BSL, launcher и manifest с хешами. `--host-bundle`
добавляет production EXE и build provenance; synthetic EXE в patch не включается.
Это **частичный patch**:
остальные файлы экспорта seed не копируются, такой каталог нельзя импортировать как полный seed.
Способ применения к новой ИБ требует отдельного ревью конкретного seed и синтаксиса 8.3.18.

```powershell
python -B integrations/onec_eschf/isolated/package.py --seed-configuration <LOCAL-Configuration.xml> --expected-sha256 <SHA256> --new-output <NEW-LOCAL-DIRECTORY>
python -B -m pytest --confcutdir tests/onec_eschf tests/onec_eschf -q
ruff check --no-cache integrations/onec_eschf/isolated/package.py tests/onec_eschf/test_isolated_packaging.py
```

Metadata UUID/маркер фиксированы; исходный native body проверяется по принятому SHA-256.
Для общего модуля предложены Server/ExternalConnection=true, оба Client=false,
ServerCall/Global/Privileged=false, DontUse. Это предложение до native compilation.
BOM для BSL соответствует наблюдённому экспорту; PowerShell source имеет UTF-8 BOM для 5.1.

`capture.bsl` содержит handshake с точной файловой строкой и обёртку захвата сообщений
до/после native body, в том числе при исключении. Сохраняются порядок и точные тексты;
Field/DataKey/Path пока не входят в этот результат. Probe создаёт только синтетическое
сообщение и не создаёт документов, не принимает UUID и не вызывает формирование XML.
Возвращаемые scopes — context/message probe; AC03 всегда false.

Подтверждённая source-цепочка: `common-module.bsl:7492,7525` использует глобальный
`ПолучитьСообщенияПользователю(Истина/Ложь)`, `service-common-module.bsl:221–247`
создаёт СообщениеПользователю и вызывает Сообщить. SHA-256 соответственно:
`3cf79f1b6b1a4c18275f56b6c28f01e2d117e70a3e901d28f5de81397eba5970` и
`25fe8812116e1748500043ad24400a265289323e88b42a50354771b475607b8e`.
Файлы находятся в корневом `.harness/work/CRM-ESCHF-001-handler-evidence`.
Это source evidence, не успешный вызов в 8.3.18.

`candidate_bytes(text, bom=...)` сохраняет явную UTF-8 гипотезу с SHA-256 и scope
`candidate_utf8_nonfinal`; она не используется для заявления о native/pre-sign equality.
Следующий source selector для выяснения bytes найден в `server-module.bsl:79–81`:
`CommonModule.ЭлектронныеДокументыСлужебный_Локализация.Module / ПолучитьДанныеФайла`.
Новый экспорт был отклонён автоматическим approval review до запуска; повторов/обхода нет.

## Fixed COM-host: локальная сборка

`host/FixedComHost.cs` собирается существующим x64 `csc.exe` из Framework64/v4.0.30319,
с фиксированным compiler SHA, C# 5 и четырьмя явно указанными runtime references.
`host/build.ps1` пишет новый каталог с двумя EXE и `build-provenance.json`:
пути/версии/хеши compiler и references, хеши source/build script, точные аргументы,
длительности и хеши обоих результатов. Установок/загрузок нет, воспроизводимость
бинарного хеша не обещается. References локальные 4.8: совместимость с NT6.3 **не проверена**.

```powershell
# Родитель NEW-BUILD должен существовать; каталог сборки должен быть новым.
powershell.exe -NoProfile -NonInteractive -File integrations/onec_eschf/isolated/host/build.ps1 -NewOutputDirectory <NEW-BUILD>
python -B integrations/onec_eschf/isolated/package.py --seed-configuration <LOCAL-Configuration.xml> --expected-sha256 <SHA256> --new-output <NEW-PATCH> --host-bundle <NEW-BUILD>
```

`eschf-probe-synthetic.exe` компилируется отдельно с SYNTHETIC_BACKEND, без NativeProbe.
Только он принимает `--synthetic-case success|hang|output|memory|child --evidence-parent <LOCAL>`.
Эти проверки Win32 Job Object имеют scope `synthetic_nonnative`; они не запускают 1С.
Production `eschf-probe.exe` принимает только `--approved-p2 <PATH> --approved-p2-sha256 <HASH>`
либо внутренний hash-bound worker request. Без допуска native activation не выполняется.
`run-isolated.ps1` теперь только запускает точный EXE и контролирует собственный процесс;
COM в PowerShell отсутствует, переносимость копии PowerShell не предполагается.

## Исходное согласие, setup evidence и допуск запуска

Пользователь сначала утверждает конкретные код/план/имена/ограничения P2. Документ
kind=`CRM-ESCHF-001/P2/approved-plan-v1` связывает реальный `user_approval_reference`,
host=`1CSRV`, target=`D:\CRM-ESCHF-001-Isolated\ka_eschf_test`,
account_name=`1CSRV\CRM_ESCHF_Test`, worker_executable=`D:\CRM-ESCHF-001-Isolated\runtime\eschf-probe.exe`
и `fixed_host_sha256`. Это ещё не свидетельство созданного аккаунта или подготовленной ИБ.
Фактический SID и SHA seed CF появляются в receipts после разрешённой подготовки;
новое согласие пользователя на каждый вычисленный SID/hash не требуется.

Затем независимо проверенные receipts связываются в **производный runtime admission**:
kind=`CRM-ESCHF-001/P2/fixed-host-context-probe-v1`, host, target, account_sid,
worker_executable/worker_executable_sha256, com_dll_sha256, seed_cf_sha256;
пары path/sha256 для source_approval, account_receipt, manifest, test_base_receipt,
isolation_receipt. `ApprovedP2Path`/`ApprovedP2Sha256` launcher указывают именно на этот
документ. Host не создаёт согласие, setup receipts или изоляцию. Ссылку на согласие
проверяет reviewer: произвольная строка или совпавший SHA сами по себе не дают разрешения.

Account receipt связывает исходный approval SHA, account_name и полученный account_sid.
Isolation receipt связывает тот же approval SHA, target, SID, worker image/hash,
initialization_in_scope=true, independent_review_reference и три hash-bound JSON:
key_access_evidence, egress_evidence, child_process_evidence. Test-base receipt связывает
approval SHA, target, marker, manifest_sha256 и seed_cf_sha256. Evidence должен отражать
реальные проверки подготовленного стенда; имя аккаунта/approved=true не заменяют их.
Manifest проверяется целиком по SHA и по хешам перечисленных файлов.

Все эти проверки происходят **до Connect**, поскольку ExternalConnection запускает init
ещё до handshake ([официальное описание](https://1c-dn.com/1c_enterprise/external_connections/),
предоставлено primary). Пример V82 в документации не доказывает регистрацию 8.3.18.
Worker допускает лишь существующий 64-bit V83 COM InprocServer32 с точным DLL path,
version=8.3.18.1661 и утверждённым hash, без пользовательского override и регистрации.
Соединение содержит только фиксированный File; автосоздания, Srvr/Ref и fallback нет.

Supervisor создаёт worker приостановленным, назначает собственный Job, затем делает resume.
Worker проверяет членство и точные limits: ActiveProcessLimit=1, ProcessMemory=3GiB,
KillOnJobClose, без breakaway. Это OS-ограничения обычных CreateProcess-потомков/памяти.
Deadline 60s и 8 файлов/1MiB вывода контролируются каждые 100ms; вывод не является дисковой
квотой. При сбое закрывается собственный Job/handle; cleanup подтверждается ожиданием exit.
При незавершённом native worker `native_com_invoked=null`: зависание не доказывает отсутствие
COM-вызова. Только успешный worker подтверждает true; synthetic backend всегда false.
Внешний launcher ограничен 75s; его остановка host закрывает Job и завершает worker.

Job не изолирует ключи/сеть и не охватывает процессы, созданные сторонним broker,
например WMI. Для конкретного seed/init/call paths нужно отдельное evidence отсутствия
таких запусков; `broker_boundary_verified=false` сохраняется в receipt. Этот host не
проверяет непрочитанный seed и не является sandbox для произвольного кода. Program-rule
для его уникального image также не покрывает Designer/CreateIB при подготовке стенда.
Права аккаунта, сеть/ключи, setup isolation и проверка NT6.3 остаются до допуска P2.
Платформа используется с существующей лицензией: отказ означает STOP без повтора,
покупки, активации или копирования лицензий. Нативные XML/bytes и AC03 здесь не получаются.
