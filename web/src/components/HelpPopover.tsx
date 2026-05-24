import { useEffect, useId, useRef, useState } from "react";
import type { ReactNode } from "react";
import { HelpCircle } from "lucide-react";

export interface HelpPopoverProps {
  /** The term being explained — used as the trigger's accessible name suffix. */
  term: string;
  /** The explanation body. */
  children: ReactNode;
}

const FOCUSABLE_SELECTOR =
  'a[href], button:not([disabled]), textarea:not([disabled]), input:not([disabled]), select:not([disabled]), [tabindex]:not([tabindex="-1"])';

/**
 * Inline "What is this?" affordance for surfacing curated jargon explanations
 * (MCP, Composio, skill_action, subagents). Renders a small HelpCircle icon
 * button next to the term; clicking opens a popover with the explanation and
 * a Close button. ESC and outside-click both dismiss; focus returns to the
 * trigger. Tab cycles through the popover's focusable elements.
 *
 * Pure presentational primitive — owners pass the term + body via children.
 */
export function HelpPopover({ term, children }: HelpPopoverProps) {
  const [open, setOpen] = useState(false);
  const triggerRef = useRef<HTMLButtonElement | null>(null);
  const popoverRef = useRef<HTMLSpanElement | null>(null);
  const wrapperRef = useRef<HTMLSpanElement | null>(null);
  const popoverId = useId();

  // Register ESC + outside-click handlers only while open. Focus restoration
  // happens in the close callback so we don't fight the consumer's own focus.
  useEffect(() => {
    if (!open) return;
    function onKeyDown(event: KeyboardEvent) {
      if (event.key === "Escape") {
        event.stopPropagation();
        close();
        return;
      }
      if (event.key !== "Tab") return;
      const root = popoverRef.current;
      if (!root) return;
      const focusable = Array.from(
        root.querySelectorAll<HTMLElement>(FOCUSABLE_SELECTOR),
      ).filter((el) => !el.hasAttribute("disabled"));
      const trigger = triggerRef.current;
      if (focusable.length === 0) {
        // Nothing to cycle inside — bounce back to the trigger.
        if (trigger) {
          event.preventDefault();
          trigger.focus();
        }
        return;
      }
      const first = focusable[0]!;
      const last = focusable[focusable.length - 1]!;
      const active = document.activeElement as HTMLElement | null;
      if (event.shiftKey) {
        if (active === first || !root.contains(active)) {
          event.preventDefault();
          (trigger ?? last).focus();
        }
      } else if (active === last) {
        event.preventDefault();
        (trigger ?? first).focus();
      }
    }
    function onMouseDown(event: MouseEvent) {
      const wrapper = wrapperRef.current;
      if (!wrapper) return;
      if (event.target instanceof Node && wrapper.contains(event.target)) {
        return;
      }
      close();
    }
    document.addEventListener("keydown", onKeyDown);
    document.addEventListener("mousedown", onMouseDown);
    return () => {
      document.removeEventListener("keydown", onKeyDown);
      document.removeEventListener("mousedown", onMouseDown);
    };
    // close is stable for the lifetime of the component (defined inline below);
    // we only need to re-bind when `open` flips.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open]);

  function close() {
    setOpen(false);
    triggerRef.current?.focus();
  }

  return (
    <span ref={wrapperRef} className="relative inline-flex items-center">
      <button
        ref={triggerRef}
        type="button"
        aria-label={`What is ${term}?`}
        aria-expanded={open}
        aria-controls={open ? popoverId : undefined}
        onClick={() => setOpen((prev) => !prev)}
        className="inline-flex items-center justify-center rounded-pill p-1 text-fg-muted hover:text-fg focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent"
      >
        <HelpCircle className="size-3" aria-hidden="true" />
      </button>
      {open ? (
        <span
          ref={popoverRef}
          id={popoverId}
          role="dialog"
          aria-label={`${term} — explanation`}
          className="absolute left-full top-full z-40 ml-1 mt-1 block w-64 rounded-card border border-border bg-bg-card p-3 text-xs text-fg shadow-lg"
        >
          <span className="block text-fg-muted">{children}</span>
          <span className="mt-3 flex justify-end">
            <button
              type="button"
              onClick={close}
              className="rounded-pill border border-border px-2 py-0.5 text-xs text-fg hover:bg-bg-app focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent"
            >
              Close
            </button>
          </span>
        </span>
      ) : null}
    </span>
  );
}

export default HelpPopover;
