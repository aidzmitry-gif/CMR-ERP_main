"use client";

import { useState } from "react";

import { SpravImport } from "./sprav-import";
import { SpravImportRefs } from "./sprav-import-refs";

function TabBtn({
  active,
  onClick,
  children,
}: {
  active: boolean;
  onClick: () => void;
  children: React.ReactNode;
}) {
  return (
    <button
      onClick={onClick}
      className={`rounded-full px-3.5 py-1.5 text-[13px] font-semibold transition ${
        active ? "bg-brand text-white" : "text-muted hover:bg-sunken"
      }`}
    >
      {children}
    </button>
  );
}

/** Импорт справочников: контрагенты (1С/Синк) и классификаторы (bulk-upsert) — разными табами. */
export function SpravImportShell() {
  const [tab, setTab] = useState<"cp" | "refs">("cp");
  return (
    <div className="flex flex-1 flex-col overflow-y-auto">
      <div className="mx-auto w-full max-w-[1100px] px-6 pt-6">
        <div className="flex flex-wrap gap-1.5">
          <TabBtn active={tab === "cp"} onClick={() => setTab("cp")}>
            Контрагенты (1С)
          </TabBtn>
          <TabBtn active={tab === "refs"} onClick={() => setTab("refs")}>
            Справочники-классификаторы
          </TabBtn>
        </div>
      </div>
      {tab === "cp" ? (
        <SpravImport />
      ) : (
        <div className="mx-auto w-full max-w-[1100px] px-6 pb-6 pt-4">
          <SpravImportRefs />
        </div>
      )}
    </div>
  );
}
