import { type ReactNode, useState } from "react";
import { Smartphone, Clock, Settings, Users, BookOpen } from "lucide-react";
import { ClerkNavAuth } from "./ClerkNavAuth";
import StatusDot from "./StatusDot";
import StatusPopover from "./StatusPopover";
import { useStore } from "@/store";

export default function TopBar() {
  const [popoverOpen, setPopoverOpen] = useState(false);
  const open = useStore((s) => s.openSlideOver);
  const overall = useStore((s) => s.readiness.overall);

  return (
    <header className="sticky top-0 z-30 flex h-14 items-center justify-between border-b border-border bg-bg-app/80 px-4 backdrop-blur">
      <div className="relative">
        <button
          onClick={() => setPopoverOpen((o) => !o)}
          className="inline-flex items-center gap-2 font-medium tracking-tight"
          aria-haspopup="dialog"
          aria-expanded={popoverOpen}
        >
          <span>wabot-agent</span>
          <StatusDot variant={overall} />
        </button>
        {popoverOpen && <StatusPopover onClose={() => setPopoverOpen(false)} />}
      </div>
      <nav className="flex items-center gap-1" aria-label="Workspace">
        <ClerkNavAuth className="mr-1 border-r border-border pr-2" />
        <IconBtn
          onClick={() => {
            window.location.href = "/knowledge";
          }}
          label="Knowledge base"
        >
          <BookOpen className="size-4" />
        </IconBtn>
        <IconBtn onClick={() => open("qr")} label="WhatsApp pairing">
          <Smartphone className="size-4" />
        </IconBtn>
        <IconBtn onClick={() => open("runs")} label="Runs history">
          <Clock className="size-4" />
        </IconBtn>
        <IconBtn onClick={() => open("groups")} label="WhatsApp groups">
          <Users className="size-4" />
        </IconBtn>
        <IconBtn onClick={() => open("settings")} label="Settings">
          <Settings className="size-4" />
        </IconBtn>
      </nav>
    </header>
  );
}

interface IconBtnProps {
  children: ReactNode;
  onClick: () => void;
  label: string;
}

function IconBtn({ children, onClick, label }: IconBtnProps) {
  return (
    <button
      onClick={onClick}
      aria-label={label}
      title={label}
      className="grid size-9 place-items-center rounded-pill text-fg-muted transition hover:bg-bg-card hover:text-fg"
    >
      {children}
    </button>
  );
}
