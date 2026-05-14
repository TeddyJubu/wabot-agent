import { Suggestion } from "@/components/ai-elements/suggestion";

const SUGGESTIONS = [
  "show me the WhatsApp pairing QR",
  "is wabot healthy?",
  "what's the send policy and which recipients are allowed?",
];

interface Props {
  onPick: (text: string) => void;
}

export default function EmptyState({ onPick }: Props) {
  return (
    <div className="flex flex-col items-center gap-6 py-16">
      <p className="text-fg-muted">What would you like to ask the agent?</p>
      <div className="flex flex-wrap justify-center gap-2">
        {SUGGESTIONS.map((s) => (
          <Suggestion key={s} onClick={() => onPick(s)}>
            {s}
          </Suggestion>
        ))}
      </div>
    </div>
  );
}
