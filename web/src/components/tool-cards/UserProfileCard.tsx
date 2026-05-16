import { User } from "lucide-react";
import type { ToolAction, UserProfileData } from "@/types/ui-envelope";

interface Props {
  data: UserProfileData;
  actions: ToolAction[];
}

export default function UserProfileCard({ data }: Props) {
  return (
    <div className="rounded-card border border-border bg-bg-card p-4 shadow-sm">
      <div className="flex items-start gap-3">
        <User className="mt-0.5 size-5 text-accent" aria-hidden />
        <div className="flex-1">
          <h3 className="text-sm font-medium">WhatsApp profile</h3>
          <p className="mt-1 font-mono text-xs text-fg-muted">{data.jid}</p>
          {data.verified_name ? (
            <p className="mt-2 text-sm font-medium">{data.verified_name}</p>
          ) : null}
          {data.status ? (
            <p className="mt-1 text-sm text-fg-muted">{data.status}</p>
          ) : (
            <p className="mt-1 text-sm text-fg-muted">(no status)</p>
          )}
          {data.picture_id ? (
            <p className="mt-2 text-xs text-fg-muted">picture id: {data.picture_id}</p>
          ) : null}
        </div>
      </div>
    </div>
  );
}
