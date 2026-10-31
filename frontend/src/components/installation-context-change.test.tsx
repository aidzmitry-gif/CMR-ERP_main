import { INSTALLATION_CHANGED,INSTALLATION_STORAGE_KEY } from "@/lib/installation-events";
import { fireEvent,render,screen,waitFor } from "@testing-library/react";
import { useEffect,useState } from "react";
import { afterEach,expect,it,vi } from "vitest";
import { InstanceOrganizationGate } from "./instance-organization-gate";

const context = (id = 7, revision = 1) => ({ configuration: "platform_settings", revision,
  organization: { id, name: `Synthetic seller ${id}`, unp: id === 7 ? "987654321" : "123456789" } });
const ok = (data: unknown) => ({ ok: true, status: 200, json: async () => data });
afterEach(() => vi.unstubAllGlobals());
function Form({ mounted }: { mounted: () => void }) {
  const [value, setValue] = useState("");
  useEffect(mounted, [mounted]);
  return <input aria-label="Unsaved value" value={value} onChange={event => setValue(event.target.value)} />;
}
it.each(["event", "focus", "storage"])("blocks a stale page after %s without remounting its unsaved form", async kind => {
  const request = vi.fn().mockResolvedValueOnce(ok(context())).mockResolvedValueOnce(ok(context(8, 2)));
  const mounted = vi.fn(); vi.stubGlobal("fetch", request);
  render(<InstanceOrganizationGate>{() => <Form mounted={mounted} />}</InstanceOrganizationGate>);
  fireEvent.change(await screen.findByLabelText("Unsaved value"), { target: { value: "Unsubmitted draft" } });
  if (kind === "event") window.dispatchEvent(new Event(INSTALLATION_CHANGED));
  else if (kind === "focus") fireEvent.focus(window);
  else window.dispatchEvent(new StorageEvent("storage", { key: INSTALLATION_STORAGE_KEY }));
  expect(await screen.findByRole("alert")).toHaveTextContent("форма заблокирована");
  expect(screen.getByLabelText("Unsaved value")).toHaveValue("Unsubmitted draft");
  expect(screen.getByLabelText("Unsaved value").closest("[inert]")).not.toBeNull();
  expect(mounted).toHaveBeenCalledOnce();
});
it("detects A-to-B-to-A through the saved revision", async () => {
  vi.stubGlobal("fetch", vi.fn().mockResolvedValueOnce(ok(context())).mockResolvedValueOnce(ok(context(7, 3))));
  render(<InstanceOrganizationGate>{() => <span>Original form</span>}</InstanceOrganizationGate>);
  await screen.findByText("Original form"); window.dispatchEvent(new Event(INSTALLATION_CHANGED));
  expect(await screen.findByRole("alert")).toHaveTextContent("изменились");
});
it("observes installation changes from the first mounted form effect", async () => {
  const request = vi.fn().mockResolvedValueOnce(ok(context())).mockResolvedValueOnce(ok(context(7, 3)));
  const mounted = vi.fn(); vi.stubGlobal("fetch", request);
  function MountedForm() {
    useEffect(() => { mounted(); window.dispatchEvent(new Event(INSTALLATION_CHANGED)); }, []);
    return <input aria-label="Original draft" defaultValue="Preserved draft" />;
  }
  render(<InstanceOrganizationGate>{() => <MountedForm />}</InstanceOrganizationGate>);
  expect(await screen.findByRole("alert")).toHaveTextContent("форма заблокирована");
  expect(screen.getByLabelText("Original draft")).toHaveValue("Preserved draft");
  expect(screen.getByLabelText("Original draft").closest("[inert]")).not.toBeNull();
  expect(mounted).toHaveBeenCalledOnce();
  expect(request).toHaveBeenCalledTimes(2);
});
it("keeps the form usable when the verified installation has not changed", async () => {
  const request = vi.fn().mockResolvedValue(ok(context())); vi.stubGlobal("fetch", request);
  render(<InstanceOrganizationGate>{() => <span>Same form</span>}</InstanceOrganizationGate>);
  await screen.findByText("Same form"); fireEvent.focus(window);
  await waitFor(() => expect(request).toHaveBeenCalledTimes(2));
  expect(screen.queryByRole("alert")).not.toBeInTheDocument();
});
it("blocks the old form if access cannot be revalidated", async () => {
  vi.stubGlobal("fetch", vi.fn().mockResolvedValueOnce(ok(context())).mockResolvedValueOnce({ ok: false, status: 403 }));
  render(<InstanceOrganizationGate>{() => <span>Protected form</span>}</InstanceOrganizationGate>);
  await screen.findByText("Protected form"); fireEvent.focus(window);
  expect(await screen.findByRole("alert")).toHaveTextContent("доступ изменились");
});
