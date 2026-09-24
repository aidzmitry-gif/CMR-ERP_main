"use client";

import { useEffect, useRef } from "react";

const warning = "Есть несохранённые изменения документа. Уйти без сохранения?";

export function confirmDiscardUnsaved(pending: boolean): boolean {
  return !pending || window.confirm(warning);
}

export function useUnsavedDocumentGuard(pending: boolean, onPendingChange?: (pending: boolean) => void) {
  const pendingRef = useRef(pending);

  useEffect(() => { pendingRef.current = pending; }, [pending]);
  useEffect(() => { onPendingChange?.(pending); }, [onPendingChange, pending]);
  useEffect(() => () => onPendingChange?.(false), [onPendingChange]);
  useEffect(() => {
    const beforeUnload = (event: BeforeUnloadEvent) => {
      if (!pendingRef.current) return;
      event.preventDefault();
      event.returnValue = "";
    };
    const linkClick = (event: MouseEvent) => {
      if (!pendingRef.current || event.defaultPrevented || event.button !== 0
        || event.metaKey || event.ctrlKey || event.shiftKey || event.altKey) return;
      const link = event.target instanceof Element ? event.target.closest("a[href]") as HTMLAnchorElement | null : null;
      if (!link || link.hasAttribute("download") || (link.target && link.target !== "_self")) return;
      const destination = new URL(link.href, window.location.href);
      const current = new URL(window.location.href);
      if (destination.origin !== current.origin
        || (destination.pathname === current.pathname && destination.search === current.search)) return;
      if (!confirmDiscardUnsaved(pendingRef.current)) {
        event.preventDefault();
        event.stopImmediatePropagation();
      }
    };
    window.addEventListener("beforeunload", beforeUnload);
    document.addEventListener("click", linkClick, true);
    return () => {
      window.removeEventListener("beforeunload", beforeUnload);
      document.removeEventListener("click", linkClick, true);
    };
  }, []);
  return () => confirmDiscardUnsaved(pendingRef.current);
}
