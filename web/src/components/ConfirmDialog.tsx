import { useEffect, useId, useRef, useState } from "react";
import type { KeyboardEvent as ReactKeyboardEvent, ReactNode } from "react";
import { createPortal } from "react-dom";

export interface ConfirmDialogProps {
  open: boolean;
  title: string;
  description?: ReactNode;
  /**
   * When set, the primary button is disabled until the user types this exact string
   * (case-sensitive) into the confirmation input. When omitted, no typed confirmation
   * is required and the primary button is always enabled.
   */
  requireTyped?: string;
  /** Primary CTA label. Defaults to "Confirm". */
  confirmLabel?: string;
  /** Secondary CTA label. Defaults to "Cancel". */
  cancelLabel?: string;
  /** Visual treatment for the primary button — "danger" for destructive ops. */
  variant?: "default" | "danger";
  onConfirm: () => void;
  onCancel: () => void;
}

const FOCUSABLE_SELECTOR =
  'a[href], button:not([disabled]), textarea:not([disabled]), input:not([disabled]), select:not([disabled]), [tabindex]:not([tabindex="-1"])';

/**
 * Generic confirmation modal. Pure presentational primitive — owners pass
 * `open`, `onConfirm`, and `onCancel`. Reused by destructive flows
 * (allow_all switch, secret deletion, agent removal) so the API is fixed.
 *
 * Backdrop clicks are intentionally inert — destructive confirmations
 * require an explicit cancel-button click or Escape.
 */
export function ConfirmDialog({
  open,
  title,
  description,
  requireTyped,
  confirmLabel = "Confirm",
  cancelLabel = "Cancel",
  variant = "default",
  onConfirm,
  onCancel,
}: ConfirmDialogProps) {
  const [typed, setTyped] = useState("");
  const containerRef = useRef<HTMLDivElement | null>(null);
  const inputRef = useRef<HTMLInputElement | null>(null);
  const cancelButtonRef = useRef<HTMLButtonElement | null>(null);
  const titleId = useId();

  // Reset the typed value whenever the dialog closes or reopens
  useEffect(() => {
    if (!open) setTyped("");
  }, [open]);

  // Focus management: capture previously-focused element, focus first control,
  // restore focus on close.
  useEffect(() => {
    if (!open) return;
    const previouslyFocused = document.activeElement as HTMLElement | null;
    const target =
      requireTyped !== undefined ? inputRef.current : cancelButtonRef.current;
    target?.focus();
    return () => {
      previouslyFocused?.focus?.();
    };
  }, [open, requireTyped]);

  if (!open) return null;

  const confirmDisabled =
    requireTyped !== undefined && typed !== requireTyped;

  function handleKeyDown(event: ReactKeyboardEvent<HTMLDivElement>) {
    if (event.key === "Escape") {
      event.stopPropagation();
      onCancel();
      return;
    }
    if (event.key !== "Tab") return;
    const root = containerRef.current;
    if (!root) return;
    const focusable = Array.from(
      root.querySelectorAll<HTMLElement>(FOCUSABLE_SELECTOR),
    ).filter((el) => !el.hasAttribute("disabled"));
    if (focusable.length === 0) return;
    const first = focusable[0]!;
    const last = focusable[focusable.length - 1]!;
    const active = document.activeElement as HTMLElement | null;
    if (event.shiftKey) {
      if (active === first || !root.contains(active)) {
        event.preventDefault();
        last.focus();
      }
    } else {
      if (active === last) {
        event.preventDefault();
        first.focus();
      }
    }
  }

  const primaryClasses =
    variant === "danger"
      ? "bg-red-600 hover:bg-red-500 text-white"
      : "bg-accent text-white hover:opacity-90";

  return createPortal(
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 p-4"
      // Backdrop click is intentionally inert.
    >
      <div
        ref={containerRef}
        role="dialog"
        aria-modal="true"
        aria-labelledby={titleId}
        onKeyDown={handleKeyDown}
        className="w-full max-w-md rounded-card border border-border bg-bg-card p-5 text-fg shadow-xl"
      >
        <h2 id={titleId} className="text-base font-semibold">
          {title}
        </h2>
        {description ? (
          <div className="mt-2 text-sm text-fg-muted">{description}</div>
        ) : null}
        {requireTyped !== undefined ? (
          <label className="mt-4 block">
            <span className="text-xs text-fg-muted">
              Type <span className="font-mono">{requireTyped}</span> to confirm
            </span>
            <input
              ref={inputRef}
              type="text"
              value={typed}
              onChange={(e) => setTyped(e.target.value)}
              className="mt-1 w-full rounded-card border border-border bg-bg-app px-3 py-2 text-sm font-mono"
              aria-label="Confirmation input"
            />
          </label>
        ) : null}
        <div className="mt-5 flex justify-end gap-2">
          <button
            ref={cancelButtonRef}
            type="button"
            onClick={onCancel}
            className="rounded-pill border border-border px-3 py-1.5 text-sm text-fg hover:bg-bg-app"
          >
            {cancelLabel}
          </button>
          <button
            type="button"
            onClick={onConfirm}
            disabled={confirmDisabled}
            className={`rounded-pill px-3 py-1.5 text-sm font-medium transition disabled:cursor-not-allowed disabled:opacity-50 ${primaryClasses}`}
          >
            {confirmLabel}
          </button>
        </div>
      </div>
    </div>,
    document.body,
  );
}

export default ConfirmDialog;
