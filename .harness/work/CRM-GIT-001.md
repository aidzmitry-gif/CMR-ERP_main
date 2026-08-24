# CRM-GIT-001 — безопасная разборка грязной рабочей копии

## Goal passport

- Результат: все найденные изменения CRM ERP классифицированы, полезные изменения доведены до проверяемых атомарных коммитов, подмодули и gitlinks согласованы, локальный шум отделён без удаления данных, интеграционные тесты проходят.
- Включено: текущие tracked/untracked файлы, подмодули `sales`, `finance`, `leads`, миграции, OIDC/Keycloak, приглашение сотрудника, приём лидов с microchips.by и почты, Office/Finance/Bank/GSheets, тесты и координационные материалы.
- Исключено: push, merge, deploy, изменение production-данных, реальная отправка email и безвозвратное удаление файлов. Эти действия требуют отдельного разрешения.
- Инварианты: не терять пользовательские/флотские файлы; не использовать broad staging; не смешивать Bank и GSheets в одном коммите; не менять историческую миграцию `0087` без отдельного доказательства.
- Откат: каждый пакет — отдельный коммит; до коммита сохраняется манифест файлов и дифф; откат выполняется только точечным `git revert` после отдельного решения.
- Риск: высокий из-за 1314 untracked-файлов, двух изменённых gitlink, нечистого `finance` и связанной цепочки миграций.

## Исходная точка

- Ветка: `chore/cc-2119-revision`; HEAD: `683ec5e`.
- Индекс: 0 staged; рабочая копия: 30 tracked и 1314 untracked, около 62 MiB.
- Подмодули: `sales` указывает на `aaf899c` вместо индексного `f612f3a`; `finance` — `a7de3ef` вместо `aa0f484` и имеет 6 внутренних изменений; `leads` имеет untracked `planning.py`.
- Сцепленные файлы: `config/settings.py` и `core/services/__init__.py` одновременно содержат Bank и GSheets; их нужно стейджить по ханкам.
- Миграции: `0105` → `0106`; модификация исторической `0087` вынесена в отдельный гейт.

## Goal runner state

- Chain ID: CRM-GIT-001
- Project root: `D:/6 Проекты/CRM ERP/Сlaude CRM - проект`
- Data owner: user and Claude/Codex fleet working in the shared CRM ERP checkout
- Risk class: high
- External-side-effect boundary: local inspection, edits, tests, and atomic local commits only; no push, merge, deploy, production writes, real email, or deletion without separate approval
- Parent outcome: classified and preserved dirty state, tested atomic local commits, coherent submodule pointers and migrations, and no unknown residue
- Status: running
- Plan revision: 1
- Approved passport revision: 1
- Approval provenance: task `019f88eb-66f2-7661-8818-42ba100ebaf9`; user message on 2026-08-24: `Утверждаю CRM-GIT-001 revision 1`
- Primary task ID: `019f88eb-66f2-7661-8818-42ba100ebaf9`
- Current task ID: `019f88eb-66f2-7661-8818-42ba100ebaf9`
- Checkout/worktree policy: primary is the only writer in the dirty base checkout; no worker worktrees until the base is classified and checkpointed
- Commit policy: primary-only
- Integration branch/worktree: `chore/cc-2119-revision` / base checkout
- Last accepted commit: `895a672`
- Current laziness-ladder rung: 2, Python standard library for a deterministic read-only manifest
- Rejected lower rungs: rung 1 cannot prove that every dirty path is preserved and assigned
- Retained exceptions / ponytail triggers: preserve all user and fleet artifacts; historical migration 0087; mixed Bank/GSheets hunks; dirty finance submodule
- Current verified subgoal: G11
- Next minimal slice and acceptance check: G12; recheck classification, preservation hashes, commit history, Goal evidence, and the no-push/no-deploy boundary
- Executable plan snapshot: `.harness/work/CRM-GIT-001.passport.json`
- Last validated plan snapshot/hash: `.harness/work/CRM-GIT-001.passport.json` / `c6671fb4fe645a0f7405143ac36e5fcebd5f65ee`
- Measurement treatment IDs: baseline `CRM-GIT-001-baseline-v1` | treatment `CRM-GIT-001-treatment-v1`
- Metrics path/schema: `.harness/metrics/CRM-GIT-001.jsonl` / schema 1
- Global agent cap: 4
- Active agent count: 0
- Delegation depth cap: 1
- Compaction count: 0
- Context threshold: 45% when visible
- Standing chain authorization: approved
- Standing authorization scope: both
- Archive policy: final-explicit-command

## Subgoals

| ID | Observable result | Depends on | Wave | Subsystem | Risk | Execution | Model | Status | Acceptance/evidence |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| G00 | Паспорт и исходный Git-снимок зафиксированы | none | 1 | orchestration | low | primary | sol | done | Валидатор паспорта PASS; ветка, HEAD, status и подмодули записаны |
| G01 | Каждый tracked/untracked файл и подмодуль отнесён к пакету и владельцу | G00 | 2 | inventory | medium | primary | sol | done | 1396/1396 root+submodule entries; 1391 files; 0 missing hashes; inventory SHA-256 `019166a8a2e1bb4519093a68f0b152c2ee7de67cef508fded412a54e29f3f032` |
| G02 | Артефакты, Obsidian, coordination и runtime-шум разделены без потери данных | G01 | 3 | repository-hygiene | medium | primary | sol | done | 380 exact local excludes; visible status 1396→297; 1387 protected files rehashed with 0 failures; rollback copy retained |
| G03 | Подмодули `sales`, `finance`, `leads` и родительские gitlinks согласованы | G01 | 3 | git-submodules | high | primary | sol | done | all five inner statuses clean; finance `ccc3c2c`, leads `a04feb0`, marketing `c40f0cf`, sales `aaf899c`, procurement unchanged `282339c`; 34+3 tests PASS |
| G04 | Сцепленные файлы разделены на атомарные пакеты | G01 | 3 | change-composition | high | primary | sol | done | B01-B17 map recorded; 12 tests PASS; root commits `53d5e97`, `80517b0`, `f232415`, `7e8d055`; empty index |
| G05 | Цепочка миграций доказана на чистой тестовой БД | G03,G04 | 4 | migrations | high | primary | sol | done | Один head `0106`; чистая PostgreSQL прошла `0001→0106→0104→0106`; объекты `0105/0106` проверены; историческая `0087` перенесена отдельным коммитом `1c9d251` из `0c585d1` |
| G06 | OIDC и приглашение сотрудника по email готовы локально | G04,G05 | 5 | identity-access | high | primary | sol | done | OIDC commits `8c6b545`..`f0f5e20`; identity commit `9136ac6`; 30 backend tests + 29 frontend tests + typecheck PASS; isolated Keycloak 26 + Mailpit proved delivery, password setup/login and one-time link; Alembic `0106↔0107` PASS |
| G07 | Приём лидов с microchips.by и email доказан локально | G04,G05 | 5 | lead-intake | high | primary | sol | done | Commit `79cda14`; 97 SQLite API/domain tests + isolated PostgreSQL relay test PASS; invalid token=403, production missing token=403, site/email source, UTM, dedupe and persistence proven |
| G08 | Office/Finance/Bank/GSheets собраны в независимые пакеты | G03,G04,G05 | 5 | finance-integrations | high | primary | sol | done | Commits `668ec22` Office, `89f8323` claim status, `216b728` Bank, `6e98484` GSheets; 43 tests + Ruff + compose config PASS; Alembic single head `0107` |
| G09 | Sales touch history и Leads planning доведены до атомарных пакетов | G03,G04 | 5 | sales-leads | medium | primary | sol | done | Commits `3d63901` (sales `aaf899c`) and `d81e877` (leads `a04feb0`); 23 focused tests + Ruff PASS; inner statuses clean before parent gitlinks |
| G10 | Frontend auth/UI и тестовое покрытие собраны без случайного UX-сдвига | G04,G06 | 6 | frontend | medium | primary | sol | done | Commits `f963a0e` and `3bce82a`; focused 157 tests and full 80-file/934-test Vitest suite PASS; typecheck and lint PASS; manual diff review found no UX behavior change |
| G11 | Все пакеты имеют атомарные локальные коммиты и общую матрицу тестов | G02,G05,G06,G07,G08,G09,G10 | 7 | integration | high | primary | sol | done | 178 affected backend tests, 934 frontend tests, production build, Ruff, py_compile, Compose and Alembic PASS; five gitlinks match clean inner trees; index empty; commits through `895a672` |
| G12 | Независимая финальная проверка и пакет к push/deploy готовы | G11 | 8 | acceptance | high | primary | sol | running | Нет неклассифицированных изменений; итоговый test report и commit list записаны; push/deploy не выполнены |

## Agent registry

| Agent/task | Parent | Subgoal | Role | Model/effort | Worktree/files | Status | Report/evidence |
| --- | --- | --- | --- | --- | --- | --- | --- |
| primary | root | G00-G12 | sole writer and verifier while base is dirty | sol/current | base checkout; exact-path staging only | planning | no subagents dispatched before approval |

## Task chain

| Seq | Task ID | Title | Purpose | Status | Verified successor | Archive status |
| --- | --- | --- | --- | --- | --- | --- |
| 01 | `019f88eb-66f2-7661-8818-42ba100ebaf9` | CRM-GIT-001 · 01 · Plan | parent | active | n/a | keep |

## Decisions and plan revisions

| Revision/time | Evidence | Decision | DAG impact |
| --- | --- | --- | --- |
| 1 / 2026-08-24 | live Git status, submodule status, diff grouping | one primary writer; no deletion; no push/deploy; include employee invite and microchips/email intake in local acceptance | created G00-G12 |
| 1 / 2026-08-24 | explicit user approval and laziness-ladder review | chain running; G01 ready; use standard-library manifest generator | unlocked wave 2 |
| 1 / 2026-08-24 | `.harness/work/CRM-GIT-001.inventory.json` | G01 accepted with complete hash coverage; G02 ready | unlocked repository hygiene |
| 1 / 2026-08-24 | `.harness/work/CRM-GIT-001.hygiene.md` | G02 accepted; use reversible local excludes, preserve coordination, defer submodule caches to G03 | unlocked submodule stabilization |
| 1 / 2026-08-24 | targeted pytest and clean inner status | G03 accepted; preserve existing sales/claim commits and create finance/leads/marketing commits | unlocked root bundle decomposition |
| 1 / 2026-08-24 | `.harness/work/CRM-GIT-001.bundles.md` and four root commits | G04 accepted; exact B01-B17 ownership and ordering recorded | unlocked migration proof |
| 1 / 2026-08-24 | clean local PostgreSQL `crm-git-001-g05`, Alembic output and commit `1c9d251` | G05 accepted; one head, full clean upgrade and reversible `0105/0106` proven; historical `0087` preserved as its known atomic commit | unlocked identity, intake and finance bundles |
| 1 / 2026-08-25 | commits `8c6b545`..`f0f5e20`, `9136ac6`, 30 backend + 29 frontend tests, isolated Keycloak 26 and Mailpit smoke | G06 accepted; OIDC and department-gated employee invitation with one-time password setup proven locally | unlocked frontend G10 and started lead intake G07 |
| 1 / 2026-08-25 | commit `79cda14`, 97 SQLite tests and isolated PostgreSQL intake test | G07 accepted; microchips.by site and inbound email paths are token-gated, deduplicated and persisted locally | started independent finance/integration bundles G08 |
| 1 / 2026-08-25 | commits `668ec22`, `89f8323`, `216b728`, `6e98484`; 43 tests, Ruff, compose config, Alembic head | G08 accepted as four independent bundles; Bank and GSheets remain fail-soft without credentials | started sales/leads gitlink integration G09 |
| 1 / 2026-08-25 | commits `3d63901`, `d81e877`; sales/leads inner commits and 23 focused tests | G09 accepted; submodule changes precede and match their parent gitlinks | unlocked final frontend composition G10 |
| 1 / 2026-08-25 | commits `f963a0e`, `3bce82a`; 157 focused and 934 full frontend tests, typecheck, lint, manual diff review | G10 accepted; frontend coverage is separate from no-behavior lint cleanup | started final integration matrix G11 |
| 1 / 2026-08-25 | commits `22920a6`..`895a672`; 178 affected backend tests, 934 frontend tests, production build, Ruff, py_compile, Compose, Alembic and five clean gitlinks | G11 accepted; all repository bundles are atomic and the index is empty; redundant full pytest stopped after its documented 10-minute budget | started final classification and evidence gate G12 |

## Автономный режим после утверждения

- После явного утверждения ревизии 1 цепочка идёт без промежуточных вопросов в пределах паспорта.
- Автоматические остановки: риск потери данных; чужой активный писатель в тех же файлах; необходимость production-write, push/deploy или реальной email-рассылки; две неудачные независимые диагностики.
