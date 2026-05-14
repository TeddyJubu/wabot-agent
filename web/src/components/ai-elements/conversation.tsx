import { type ReactNode } from "react";
import { clsx } from "clsx";

export function Conversation({ children, className }: { children: ReactNode; className?: string }) {
  return (
    <div className={clsx("flex flex-col gap-4", className)} role="log" aria-live="polite">
      {children}
    </div>
  );
}

type MessageRole = "user" | "assistant";

export function Message({ from, children }: { from: MessageRole; children: ReactNode }) {
  const isUser = from === "user";
  return (
    <div
      className={clsx(
        "flex w-full gap-3",
        isUser ? "justify-end" : "justify-start",
      )}
    >
      {!isUser && <MessageAvatar />}
      <div className={clsx("max-w-[85%]", isUser && "order-1")}>{children}</div>
    </div>
  );
}

export function MessageAvatar() {
  return (
    <div
      aria-hidden
      className="mt-1 grid size-7 shrink-0 place-items-center rounded-full bg-accent/15 text-[10px] font-medium text-accent"
    >
      W
    </div>
  );
}

export function MessageContent({ children, role = "assistant" }: { children: ReactNode; role?: MessageRole }) {
  const isUser = role === "user";
  return (
    <div
      className={clsx(
        "rounded-card px-4 py-2.5 text-sm leading-relaxed",
        isUser
          ? "bg-accent text-accent-fg"
          : "bg-bg-card border border-border text-fg",
      )}
    >
      {children}
    </div>
  );
}
