import { type ReactNode, useEffect } from "react";
import { X } from "lucide-react";

interface Props {
  open: boolean;
  onClose: () => void;
  title: string;
  children: ReactNode;
}

export default function SlideOver({ open, onClose, title, children }: Props) {
  useEffect(() => {
    if (!open) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") onClose();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [open, onClose]);

  return (
    <div aria-hidden={!open} className="pointer-events-none fixed inset-0 z-40">
      <div
        onClick={onClose}
        className={`absolute inset-0 bg-fg/20 transition-opacity duration-200 ease-out ${
          open ? "pointer-events-auto opacity-100" : "opacity-0"
        }`}
      />
      <aside
        role="dialog"
        aria-label={title}
        className={`pointer-events-auto absolute right-0 top-0 h-full w-[420px] max-w-[92vw] border-l border-border bg-bg-card shadow-sm transition-transform duration-200 ease-out ${
          open ? "translate-x-0" : "translate-x-full"
        }`}
      >
        <header className="flex items-center justify-between border-b border-border px-4 py-3">
          <h2 className="text-sm font-medium">{title}</h2>
          <button
            onClick={onClose}
            aria-label="Close"
            className="grid size-8 place-items-center rounded-pill text-fg-muted transition hover:bg-bg-app hover:text-fg"
          >
            <X className="size-4" />
          </button>
        </header>
        <div className="h-[calc(100%-49px)] overflow-y-auto p-4">{children}</div>
      </aside>
    </div>
  );
}
