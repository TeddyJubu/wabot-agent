import { describe, it, expect, vi } from "vitest";
import { render, screen, fireEvent } from "@testing-library/react";
import WabotStatusCard from "@/components/tool-cards/WabotStatusCard";
import SendConfirmCard from "@/components/tool-cards/SendConfirmCard";
import MemoryCard from "@/components/tool-cards/MemoryCard";
import PairingQrCard from "@/components/tool-cards/PairingQrCard";

describe("WabotStatusCard", () => {
  it("renders ok state with version + uptime + recheck action", () => {
    const onAction = vi.fn();
    render(
      <WabotStatusCard
        data={{ status: "ok", version: "0.4.2", uptime_s: 65, last_seen_s: 1 }}
        actions={[{ id: "recheck", label: "Recheck", tool: "wabot_health", args: {} }]}
        onAction={onAction}
      />,
    );
    expect(screen.getByText("wabot daemon")).toBeInTheDocument();
    expect(screen.getByText("0.4.2")).toBeInTheDocument();
    expect(screen.getByText("1m")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: /Recheck/i }));
    expect(onAction).toHaveBeenCalledWith("recheck");
  });

  it("renders bad state with error and no actions", () => {
    render(
      <WabotStatusCard
        data={{ status: "bad", error: "connect refused" }}
        actions={[]}
        onAction={vi.fn()}
      />,
    );
    expect(screen.getByText("connect refused")).toBeInTheDocument();
    expect(screen.queryByRole("button")).not.toBeInTheDocument();
  });
});

describe("SendConfirmCard", () => {
  it("shows Approve/Cancel and fires when clicked", () => {
    const onAction = vi.fn();
    render(
      <SendConfirmCard
        data={{
          policy: "allowlist",
          recipient_masked: "+1***4567",
          body_preview: "hi",
          needs_approval: true,
          delivered: false,
        }}
        actions={[
          { id: "approve", label: "Approve", tool: "send_whatsapp_text", args: {} },
          { id: "cancel", label: "Cancel", tool: null, args: {} },
        ]}
        onAction={onAction}
      />,
    );
    expect(screen.getByText("to +1***4567")).toBeInTheDocument();
    expect(screen.getByText("Awaiting your approval")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Approve" }));
    expect(onAction).toHaveBeenCalledWith("approve");
    fireEvent.click(screen.getByRole("button", { name: "Cancel" }));
    expect(onAction).toHaveBeenCalledWith("cancel");
  });

  it("hides actions for dry-run drafts", () => {
    render(
      <SendConfirmCard
        data={{
          policy: "dry_run",
          recipient_masked: "+1***4567",
          body_preview: "hi",
          needs_approval: false,
          delivered: false,
        }}
        actions={[]}
        onAction={vi.fn()}
      />,
    );
    expect(screen.queryByRole("button")).not.toBeInTheDocument();
    expect(screen.getByText("Send drafted")).toBeInTheDocument();
  });

  it("surfaces the allow_all warning", () => {
    render(
      <SendConfirmCard
        data={{
          policy: "allow_all",
          recipient_masked: "+1***4567",
          body_preview: "hi",
          needs_approval: true,
          delivered: false,
        }}
        actions={[]}
        onAction={vi.fn()}
      />,
    );
    expect(screen.getByText(/Allow-all bypasses/i)).toBeInTheDocument();
  });
});

describe("MemoryCard", () => {
  it("renders contact + facts as chips", () => {
    render(
      <MemoryCard
        data={{ contact_masked: "+1***4567", facts: [{ id: "f1", text: "prefers async" }] }}
        actions={[]}
        onAction={vi.fn()}
      />,
    );
    expect(screen.getByText("+1***4567")).toBeInTheDocument();
    expect(screen.getByText("prefers async")).toBeInTheDocument();
  });

  it("renders empty state when no facts", () => {
    render(
      <MemoryCard
        data={{ contact_masked: "+1***4567", facts: [] }}
        actions={[]}
        onAction={vi.fn()}
      />,
    );
    expect(screen.getByText(/No facts recorded yet/i)).toBeInTheDocument();
  });
});

describe("PairingQrCard", () => {
  it("renders QR image when available", () => {
    render(
      <PairingQrCard
        data={{ available: true, linked_device: "iPhone" }}
        actions={[{ id: "refresh", label: "Refresh", tool: "__pairing_qr", args: {} }]}
        onAction={vi.fn()}
      />,
    );
    const img = screen.getByAltText("WhatsApp pairing QR code");
    expect(img).toBeInTheDocument();
    expect(img.getAttribute("src")).toContain("/api/whatsapp/pairing.svg");
  });

  it("renders empty state when QR unavailable", () => {
    render(
      <PairingQrCard
        data={{ available: false, linked_device: null }}
        actions={[]}
        onAction={vi.fn()}
      />,
    );
    expect(screen.getByText(/No QR available/i)).toBeInTheDocument();
  });
});
