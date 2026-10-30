export const INSTALLATION_CHANGED = "erp-installation-organization-changed";
export const INSTALLATION_STORAGE_KEY = "erp-installation-organization-revision";

export function notifyInstallationChanged(revision: number) {
  try { localStorage.setItem(INSTALLATION_STORAGE_KEY, `${revision}:${crypto.randomUUID()}`); }
  catch { /* Other pages still revalidate on focus. */ }
  window.dispatchEvent(new Event(INSTALLATION_CHANGED));
}
