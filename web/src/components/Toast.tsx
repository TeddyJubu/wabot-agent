import { useEffect } from "react";
import { useToastStore } from "@/store/toast";
import type { ToastItem, ToastVariant } from "@/store/toast";

export { useToast } from "@/store/toast";

const VARIANT_ACCENT: Record<ToastVariant, string> = {
  success: "border-l-green-500",
  error: "border-l-red-500",
  info: "border-l-sky-500",
};

function ariaLiveFor(variant: ToastVariant): "polite" | "assertive" {
  return variant === "error" ? "assertive" : "polite";
}

interface ToastCardProps {
  toast: ToastItem;
  onDismiss: (id: number) => void;
}

function ToastCard({ toast, onDismiss }: ToastCardProps) {
  const { id, variant, message, durationMs } = toast;

  useEffect(() => {
    if (durationMs <= 0) return;
    const handle = window.setTimeout(() => {
      onDismiss(id);
    }, durationMs);
    return () => {
      window.clearTimeout(handle);
    };
  }, [id, durationMs, onDismiss]);

  return (
    <div
      role="status"
      aria-live={ariaLiveFor(variant)}
      className={`flex items-start gap-3 bg-bg-card text-fg border border-border rounded-card px-4 py-3 shadow-md border-l-4 ${VARIANT_ACCENT[variant]} min-w-[16rem] max-w-sm`}
    >
      <span className="flex-1 text-sm leading-snug">{message}</span>
      <button
        type="button"
        onClick={() => onDismiss(id)}
        aria-label="Dismiss notification"
        className="text-fg-muted hover:text-fg rounded-pill px-2 py-0.5 text-sm leading-none focus:outline-none focus:ring-2 focus:ring-accent"
      >
        ×
      </button>
    </div>
  );
}

export default function ToastViewport() {
  const toasts = useToastStore((s) => s.toasts);
  const dismiss = useToastStore((s) => s.dismiss);

  if (toasts.length === 0) return null;

  return (
    <div className="fixed bottom-4 right-4 z-50 flex flex-col gap-2">
      {toasts.map((t) => (
        <ToastCard key={t.id} toast={t} onDismiss={dismiss} />
      ))}
    </div>
  );
}
