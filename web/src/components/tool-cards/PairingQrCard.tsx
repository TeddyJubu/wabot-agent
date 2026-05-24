import { useState } from "react";
import { QrCode, RefreshCw, Smartphone } from "lucide-react";
import type { ToolAction, PairingQrData } from "@/types/ui-envelope";

interface Props {
  data: PairingQrData;
  actions: ToolAction[];
  onAction: (id: string) => void;
}

export default function PairingQrCard({ data, actions, onAction }: Props) {
  const [bust, setBust] = useState(0);
  const src = data.available ? `/api/whatsapp/pairing.svg?b=${bust}` : null;
  return (
    <div className="rounded-card border border-border bg-bg-card p-4 shadow-sm">
      <div className="flex items-start gap-3">
        <Smartphone className="mt-0.5 size-5 text-accent" aria-hidden />
        <div className="flex-1">
          <div className="flex items-baseline justify-between gap-3">
            <h3 className="text-sm font-medium">WhatsApp pairing</h3>
            <span className="text-xs text-fg-muted">{data.linked_device ?? "not linked"}</span>
          </div>
          <div className="mt-3 grid place-items-center rounded-card border border-border/60 bg-white p-4">
            {src ? (
              <img
                src={src}
                alt="WhatsApp pairing QR code"
                className="size-48 rounded-sm bg-white"
                style={{ imageRendering: "pixelated" }}
              />
            ) : (
              <p className="text-xs text-fg-muted">No QR available right now.</p>
            )}
          </div>
          {actions.length > 0 && (
            <div className="mt-3 flex gap-2">
              {actions.map((a) => (
                <button
                  key={a.id}
                  onClick={() => {
                    if (a.id === "refresh" || a.id === "new_qr") {
                      setBust((b) => b + 1);
                    }
                    onAction(a.id);
                  }}
                  className="inline-flex items-center gap-1.5 rounded-pill border border-border px-2.5 py-1 text-xs hover:bg-bg-app"
                >
                  {a.id === "new_qr" ? (
                    <QrCode className="size-3" aria-hidden />
                  ) : (
                    <RefreshCw className="size-3" aria-hidden />
                  )}{" "}
                  {a.label}
                </button>
              ))}
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
