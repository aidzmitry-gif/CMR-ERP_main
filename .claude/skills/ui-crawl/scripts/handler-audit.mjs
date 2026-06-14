#!/usr/bin/env node
// Статический аудит инлайн-обработчиков HTML-макетов.
// Использование: node handler-audit.mjs file1.html [file2.html ...]
// Выдаёт по каждому файлу: функции из on*-атрибутов, не имеющие определения, и синтаксис <script>.
import fs from 'node:fs';
import vm from 'node:vm';

const IGNORE = new Set([
  'if','for','while','return','event','this','window','document','toggle','classList',
  'contains','closest','querySelector','querySelectorAll','getElementById','focus',
  'scrollIntoView','includes','location','forEach','remove','add','replace','split','map',
  'filter','value','textContent','parentElement','preventDefault','stopPropagation','dispatchEvent',
  'push','pop','shift','unshift','slice','join','trim','setAttribute','getAttribute','dataset',
  'reduce','some','every','find','indexOf','match','matchAll','toLocaleString','round','parseInt','parseFloat',
]);

const files = process.argv.slice(2);
if (!files.length) { console.error('usage: node handler-audit.mjs <file.html> [...]'); process.exit(2); }

let anyFail = false;
for (const f of files) {
  let s;
  try { s = fs.readFileSync(f, 'utf8'); }
  catch { console.log(`=== ${f} ===\n  НЕ ПРОЧИТАН`); anyFail = true; continue; }

  // определения: function NAME( и const/let/var NAME = function|(arrow)
  const defined = new Set([...s.matchAll(/function\s+([a-zA-Z_$][\w$]*)\s*\(/g)].map(m => m[1]));
  for (const m of s.matchAll(/(?:const|let|var)\s+([a-zA-Z_$][\w$]*)\s*=\s*(?:async\s*)?(?:function|\()/g)) defined.add(m[1]);

  // использования в on*-атрибутах
  const used = new Set();
  for (const m of s.matchAll(/on(?:click|input|change|keydown|keyup|submit|mouseenter|mouseleave)\s*=\s*"([^"]*)"/g))
    for (const c of m[1].matchAll(/([a-zA-Z_$][\w$]*)\s*\(/g)) used.add(c[1]);

  const missing = [...used].filter(n => !IGNORE.has(n) && !defined.has(n));

  // синтаксис каждого <script>-блока
  const blocks = [...s.matchAll(/<script>([\s\S]*?)<\/script>/g)].map(m => m[1]);
  // Проверка синтаксиса без исполнения: vm.Script компилирует, но НЕ запускает код.
  let syntax = 'JS OK ✓', synFail = false;
  blocks.forEach((b, i) => { try { new vm.Script(b); } catch (e) { synFail = true; syntax = (synFail ? syntax + '\n' : '') + `  SYNTAX block#${i}: ${e.message}`; } });

  console.log(`=== ${f} ===`);
  console.log(`  handlers used: ${used.size} | function defs: ${defined.size} | <script> blocks: ${blocks.length}`);
  console.log(`  MISSING: ${missing.length ? missing.join(', ') : 'none ✓'}`);
  console.log(`  ${syntax}`);
  if (missing.length || synFail) anyFail = true;
}
process.exit(anyFail ? 1 : 0);
