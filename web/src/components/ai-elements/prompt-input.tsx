import {
  type FormEvent,
  type KeyboardEvent,
  type ReactNode,
  type TextareaHTMLAttributes,
  forwardRef,
} from "react";
import { ArrowUp } from "lucide-react";
import { clsx } from "clsx";

interface PromptInputProps {
  children: ReactNode;
  onSubmit?: (e: FormEvent<HTMLFormElement>) => void;
  className?: string;
}

export function PromptInput({ children, onSubmit, className }: PromptInputProps) {
  return (
    <form
      onSubmit={onSubmit}
      className={clsx(
        "relative rounded-card border border-border bg-bg-card p-2 shadow-sm transition focus-within:border-accent/40",
        className,
      )}
    >
      {children}
    </form>
  );
}

type PromptInputTextareaProps = TextareaHTMLAttributes<HTMLTextAreaElement>;

export const PromptInputTextarea = forwardRef<HTMLTextAreaElement, PromptInputTextareaProps>(
  function PromptInputTextarea({ className, onKeyDown, ...rest }, ref) {
    const handleKey = (e: KeyboardEvent<HTMLTextAreaElement>) => {
      onKeyDown?.(e);
      // Auto-grow handled via rows + CSS field-sizing where supported.
    };
    return (
      <textarea
        ref={ref}
        rows={2}
        onKeyDown={handleKey}
        className={clsx(
          "block max-h-48 w-full resize-none rounded-card bg-transparent px-3 py-2 text-sm placeholder:text-fg-muted focus:outline-none",
          className,
        )}
        {...rest}
      />
    );
  },
);

export function PromptInputSubmit({ disabled }: { disabled?: boolean }) {
  return (
    <div className="flex items-center justify-end px-1 pb-1">
      <button
        type="submit"
        disabled={disabled}
        aria-label="Send message"
        className="grid size-8 place-items-center rounded-pill bg-accent text-accent-fg transition hover:opacity-90 disabled:opacity-40"
      >
        <ArrowUp className="size-4" />
      </button>
    </div>
  );
}
