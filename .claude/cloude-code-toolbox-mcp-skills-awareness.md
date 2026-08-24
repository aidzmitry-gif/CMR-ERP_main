# Cloude Code ToolBox — MCP & Skills awareness

> 🛑 **УСТАРЕЛО — НЕ ДОВЕРЯТЬ (проверено 2026-07-25).** Снимок сделан 11.06.2026 и с тех пор
> врёт по обоим своим предметам: (1) MCP — заявляет «серверов нет», хотя в воркспейсе есть
> `.mcp.json` с `github` и подключены плагинные MCP (playwright, context7 и др.);
> (2) Скиллы — перечисляет ОДИН проектный скилл `orkestrator-lead`, тогда как их шесть
> (deploy-release, html-first, lane-onboard, orkestrator-lead, ship-cycle, ui-crawl).
> Файл по своему же описанию грузится в контекст рядом с CLAUDE.md, то есть активно
> дезинформирует. Claude Code и так подставляет актуальный список скиллов и MCP сам.
> **Решение оператору:** перегенерировать отчёт расширением ToolBox либо удалить файл
> (и его копию в `D:\6 Проекты\CRM ERP\.claude\`). До этого — читать только как историю.

_Generated: 2026-06-11T17:06:06.333Z_

## How to use this report

- **Saved copy:** This file is **`.claude/cloude-code-toolbox-mcp-skills-awareness.md`** — refreshed whenever the toolbox runs an MCP & Skills scan (including on workspace open when auto-scan is enabled). It is meant for **Claude Code workspace context** together with `CLAUDE.md` (which gets a shorter replaceable summary when auto-merge is on).
- **MCP:** Lists **configured** servers from Claude Code config (`~/.claude.json` for user scope, `.mcp.json` for project scope). Use `/mcp` in the Claude Code panel to connect servers for your session.
- **Skills:** **On-disk** folders with `SKILL.md`. Claude Code does not auto-load them; attach `SKILL.md` or paths in chat when useful.
- **Task routing:** When the user’s request matches a server’s purpose (e.g. Confluence → Confluence/Atlassian MCP), prefer that **server id** from the tables below.

---

## MCP — workspace

Workspace `mcp.json` _(folder: Сlaude CRM - проект)_

- **d:\6 Проекты\CRM ERP\Сlaude CRM - проект\.mcp.json** — _File missing_

_No active workspace servers in mcp.json._

## MCP — user profile

- **C:\Users\aidzm\.claude.json** — _File exists — no servers defined_

_No active user-scoped servers in mcp.json._

## Skills (local `SKILL.md` folders)

### Project-scoped

- **orkestrator-lead** — `d:\6 Проекты\CRM ERP\Сlaude CRM - проект\.claude\skills\orkestrator-lead`
  - OrkestratorLEAD — оркестратор параллельных Claude-воркеров для этого проекта (CRM ERP, Windows). Используй, когда пользователь хочет распараллелить большую задачу, разбить её на подзадачи и гонять несколько воркеров; зап

### User-scoped

- **algorithmic-art** — `C:\Users\aidzm\.claude\skills\algorithmic-art`
  - Creating algorithmic art using p5.js with seeded randomness and interactive parameter exploration. Use this when users request creating art using code, generative art, algorithmic art, flow fields, or particle systems. C

- **brand-guidelines** — `C:\Users\aidzm\.claude\skills\brand-guidelines`
  - Applies Anthropic's official brand colors and typography to any sort of artifact that may benefit from having Anthropic's look-and-feel. Use it when brand colors or style guidelines, visual formatting, or company design 

- **canvas-design** — `C:\Users\aidzm\.claude\skills\canvas-design`
  - Create beautiful visual art in .png and .pdf documents using design philosophy. You should use this skill when the user asks to create a poster, piece of art, design, or other static piece. Create original visual designs

- **claude-api** — `C:\Users\aidzm\.claude\skills\claude-api`
  - |-

- **doc-coauthoring** — `C:\Users\aidzm\.claude\skills\doc-coauthoring`
  - Guide users through a structured workflow for co-authoring documentation. Use when user wants to write documentation, proposals, technical specs, decision docs, or similar structured content. This workflow helps users ef

- **docx** — `C:\Users\aidzm\.claude\skills\docx`
  - Use this skill whenever the user wants to create, read, edit, or manipulate Word documents (.docx files). Triggers include: any mention of 'Word doc', 'word document', '.docx', or requests to produce professional documen

- **frontend-design** — `C:\Users\aidzm\.claude\skills\frontend-design`
  - Guidance for distinctive, intentional visual design when building new UI or reshaping an existing one. Helps with aesthetic direction, typography, and making choices that don't read as templated defaults.

- **internal-comms** — `C:\Users\aidzm\.claude\skills\internal-comms`
  - A set of resources to help me write all kinds of internal communications, using the formats that my company likes to use. Claude should use this skill whenever asked to write some sort of internal communications (status 

- **karpathy-guidelines** — `C:\Users\aidzm\.claude\skills\karpathy-guidelines`
  - Behavioral guidelines to reduce common LLM coding mistakes. Use when writing, reviewing, or refactoring code to avoid overcomplication, make surgical changes, surface assumptions, and define verifiable success criteria.

- **mcp-builder** — `C:\Users\aidzm\.claude\skills\mcp-builder`
  - Guide for creating high-quality MCP (Model Context Protocol) servers that enable LLMs to interact with external services through well-designed tools. Use when building MCP servers to integrate external APIs or services, 

- **pdf** — `C:\Users\aidzm\.claude\skills\pdf`
  - Use this skill whenever the user wants to do anything with PDF files. This includes reading or extracting text/tables from PDFs, combining or merging multiple PDFs into one, splitting PDFs apart, rotating pages, adding w

- **pptx** — `C:\Users\aidzm\.claude\skills\pptx`
  - Use this skill any time a .pptx file is involved in any way — as input, output, or both. This includes: creating slide decks, pitch decks, or presentations; reading, parsing, or extracting text from any .pptx file (even 

- **skill-creator** — `C:\Users\aidzm\.claude\skills\skill-creator`
  - Create new skills, modify and improve existing skills, and measure skill performance. Use when users want to create a skill from scratch, edit, or optimize an existing skill, run evals to test a skill, benchmark skill pe

- **slack-gif-creator** — `C:\Users\aidzm\.claude\skills\slack-gif-creator`
  - Knowledge and utilities for creating animated GIFs optimized for Slack. Provides constraints, validation tools, and animation concepts. Use when users request animated GIFs for Slack like "make me a GIF of X doing Y for 

- **theme-factory** — `C:\Users\aidzm\.claude\skills\theme-factory`
  - Toolkit for styling artifacts with a theme. These artifacts can be slides, docs, reportings, HTML landing pages, etc. There are 10 pre-set themes with colors/fonts that you can apply to any artifact that has been creatin

- **web-artifacts-builder** — `C:\Users\aidzm\.claude\skills\web-artifacts-builder`
  - Suite of tools for creating elaborate, multi-component claude.ai HTML artifacts using modern frontend web technologies (React, Tailwind CSS, shadcn/ui). Use for complex artifacts requiring state management, routing, or s

- **webapp-testing** — `C:\Users\aidzm\.claude\skills\webapp-testing`
  - Toolkit for interacting with and testing local web applications using Playwright. Supports verifying frontend functionality, debugging UI behavior, capturing browser screenshots, and viewing browser logs.

- **xlsx** — `C:\Users\aidzm\.claude\skills\xlsx`
  - Use this skill any time a spreadsheet file is the primary input or output. This means any task where the user wants to: open, read, edit, or fix an existing .xlsx, .xlsm, .csv, or .tsv file (e.g., adding columns, computi

---

## Suggested next steps

- **MCP:** Use this extension’s hub **MCP** tab, or `claude mcp list` in the terminal. In Claude Code, use `/mcp` to connect servers for the session.
- **Edit config:** Open `~/.claude.json` (user MCP) or `<workspace>/.mcp.json` (project MCP) via the extension commands.
- **Refresh this report:** run **Intelligence — scan MCP & Skills awareness** again after changing MCP config or adding skills.

_Report from Cloude Code ToolBox extension._
