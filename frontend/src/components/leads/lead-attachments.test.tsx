import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("@/lib/api", () => ({
  fetchLeadAttachments: vi.fn(),
  uploadLeadAttachment: vi.fn(),
  leadAttachmentDownloadUrl: (leadId: number, attachmentId: number) =>
    `/api/leads/${leadId}/attachments/${attachmentId}/download`,
}));

import { LeadAttachments } from "@/components/leads/lead-attachments";
import * as api from "@/lib/api";
import type { LeadAttachment } from "@/lib/types";

const attachments: LeadAttachment[] = [
  {
    id: 1,
    leadId: 7,
    filename: "tender-scan.pdf",
    contentType: "application/pdf",
    sizeBytes: 512_000,
    source: "tender",
    createdAt: "2026-07-01T10:00:00Z",
  },
  {
    id: 2,
    leadId: 7,
    filename: "letter.docx",
    contentType: "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    sizeBytes: 2_500_000,
    source: "email",
    createdAt: "2026-07-02T10:00:00Z",
  },
];

beforeEach(() => vi.clearAllMocks());

describe("LeadAttachments", () => {
  it("рендерит список вложений с именем/размером/бейджем источника", async () => {
    (api.fetchLeadAttachments as ReturnType<typeof vi.fn>).mockResolvedValue(attachments);

    render(<LeadAttachments leadId={7} />);

    expect(await screen.findByText("tender-scan.pdf")).toBeInTheDocument();
    expect(screen.getByText("letter.docx")).toBeInTheDocument();
    expect(screen.getByText("500 КБ")).toBeInTheDocument();
    expect(screen.getByText("2.4 МБ")).toBeInTheDocument();
    expect(screen.getByText("с тендера")).toBeInTheDocument();
    expect(screen.getByText("с почты")).toBeInTheDocument();
  });

  it("показывает «Вложений нет» для пустого списка", async () => {
    (api.fetchLeadAttachments as ReturnType<typeof vi.fn>).mockResolvedValue([]);

    render(<LeadAttachments leadId={7} />);

    expect(await screen.findByText("Вложений нет")).toBeInTheDocument();
  });

  it("загрузка файла через input добавляет новое вложение в список", async () => {
    (api.fetchLeadAttachments as ReturnType<typeof vi.fn>).mockResolvedValue([]);
    const newAttachment: LeadAttachment = {
      id: 3,
      leadId: 7,
      filename: "manual.png",
      contentType: "image/png",
      sizeBytes: 1024,
      source: "manual",
      createdAt: "2026-07-04T10:00:00Z",
    };
    (api.uploadLeadAttachment as ReturnType<typeof vi.fn>).mockResolvedValue({
      attachment: newAttachment,
    });

    const { container } = render(<LeadAttachments leadId={7} />);
    await screen.findByText("Вложений нет");

    const input = container.querySelector('input[type="file"]') as HTMLInputElement;
    const file = new File(["data"], "manual.png", { type: "image/png" });
    fireEvent.change(input, { target: { files: [file] } });

    await waitFor(() => expect(api.uploadLeadAttachment).toHaveBeenCalledWith(7, file));
    expect(await screen.findByText("manual.png")).toBeInTheDocument();
  });
});
