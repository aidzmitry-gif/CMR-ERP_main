"use client";

import "../themes/themes.css";
import { useState } from "react";
import { Sun, Moon } from "lucide-react";
import { FullDealCard, FullKanban, FullRop } from "../full/themed-screens";

/**
 * Финальный превью: 2 темы C (светлая) + D (тёмная) с КНОПКОЙ ПЕРЕКЛЮЧЕНИЯ.
 * C — по умолчанию. Открыть: /design/preview
 */
const SCREENS = [
  { id: "deal-card", label: "Карточка сделки", render: FullDealCard },
  { id: "kanban", label: "Доска (канбан)", render: FullKanban },
  { id: "rop", label: "Обзор РОП", render: FullRop },
];

export default function PreviewPage() {
  const [dark, setDark] = useState(false);
  const [screen, setScreen] = useState("deal-card");
  const theme = dark ? "theme-D" : "theme-C";
  const Screen = SCREENS.find((s) => s.id === screen)!.render;

  return (
    <div className={`tw-theme ${theme}`} style={{ minHeight: "100vh", background: "var(--t-canvas)", color: "var(--t-ink)", fontFamily: "var(--t-font)", transition: "background .25s, color .25s" }}>
      {/* шапка с переключателями */}
      <div style={{ position: "sticky", top: 0, zIndex: 30, background: "var(--t-surface)", borderBottom: "1px solid var(--t-line)", padding: "10px 24px", display: "flex", gap: 14, alignItems: "center", flexWrap: "wrap" }}>
        <span style={{ fontWeight: 700, fontSize: 14 }}>Финальный стиль</span>
        <span style={{ fontSize: 12, color: "var(--t-muted)" }}>{dark ? "D · Dark cockpit" : "C · Enterprise"}</span>

        {/* выбор экрана */}
        <div style={{ display: "flex", gap: 6, marginLeft: 12 }}>
          {SCREENS.map((s) => (
            <button
              key={s.id}
              onClick={() => setScreen(s.id)}
              style={{
                fontSize: 12.5, fontWeight: 600, padding: "6px 12px", borderRadius: "var(--t-radius-sm)", cursor: "pointer", border: "1px solid transparent",
                background: screen === s.id ? "var(--t-accent)" : "var(--t-surface)",
                color: screen === s.id ? "#fff" : "var(--t-muted)",
                borderColor: screen === s.id ? "var(--t-accent)" : "var(--t-line-strong)",
              }}
            >
              {s.label}
            </button>
          ))}
        </div>

        {/* КНОПКА ПЕРЕКЛЮЧЕНИЯ ТЕМЫ */}
        <button
          onClick={() => setDark((v) => !v)}
          title={dark ? "Светлая тема" : "Тёмная тема"}
          style={{
            marginLeft: "auto", display: "inline-flex", alignItems: "center", gap: 8, cursor: "pointer",
            background: "var(--t-sunken)", border: "1px solid var(--t-line-strong)", borderRadius: 999, padding: "5px 6px",
          }}
        >
          <span style={{ display: "inline-flex", alignItems: "center", justifyContent: "center", width: 30, height: 26, borderRadius: 999, background: !dark ? "var(--t-accent)" : "transparent", color: !dark ? "#fff" : "var(--t-faint)" }}>
            <Sun size={15} />
          </span>
          <span style={{ display: "inline-flex", alignItems: "center", justifyContent: "center", width: 30, height: 26, borderRadius: 999, background: dark ? "var(--t-accent)" : "transparent", color: dark ? "#fff" : "var(--t-faint)" }}>
            <Moon size={15} />
          </span>
        </button>
      </div>

      <div style={{ maxWidth: 1280, margin: "0 auto", padding: 24 }}>
        <Screen />
      </div>
    </div>
  );
}
