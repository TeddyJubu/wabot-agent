import type {
  MemoryData,
  PairingQrData,
  SendConfirmData,
  UiEnvelope,
  WabotStatusData,
} from "@/types/ui-envelope";
import WabotStatusCard from "./WabotStatusCard";
import PairingQrCard from "./PairingQrCard";
import SendConfirmCard from "./SendConfirmCard";
import MemoryCard from "./MemoryCard";

interface Props {
  envelope: UiEnvelope;
  onAction: (actionId: string) => void;
}

export default function ToolCard({ envelope, onAction }: Props) {
  switch (envelope.kind) {
    case "wabot_status":
      return (
        <WabotStatusCard
          data={envelope.data as unknown as WabotStatusData}
          actions={envelope.actions}
          onAction={onAction}
        />
      );
    case "pairing_qr":
      return (
        <PairingQrCard
          data={envelope.data as unknown as PairingQrData}
          actions={envelope.actions}
          onAction={onAction}
        />
      );
    case "send_confirm":
      return (
        <SendConfirmCard
          data={envelope.data as unknown as SendConfirmData}
          actions={envelope.actions}
          onAction={onAction}
        />
      );
    case "memory":
      return (
        <MemoryCard
          data={envelope.data as unknown as MemoryData}
          actions={envelope.actions}
          onAction={onAction}
        />
      );
    default:
      return null;
  }
}
