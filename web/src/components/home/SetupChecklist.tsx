import { useEffect, useState } from "react";
import { CheckCircle2, Circle, Loader2 } from "lucide-react";
import clsx from "clsx";
import { useStore } from "@/store";
import { fetchKnowledgeIndex } from "@/api/knowledge";

export type StepStatus = "done" | "active" | "pending";

interface ChecklistStep {
  id: string;
  title: string;
  description: string;
  status: StepStatus;
  actionLabel?: string;
  onAction?: () => void;
}

interface SetupChecklistProps {
  /** Whether the user is signed in (read from `useUser()` by the parent). */
  isSignedIn: boolean;
  /** Optional handler that hides the checklist in favour of the digest. */
  onDismiss?: () => void;
}

/**
 * Vertical "first-time setup" checklist. Each row is rendered as a small card
 * with a status icon, a one-line description, and an action button (or a
 * "Done" pill when the step is complete).
 *
 * Foundation steps (Sign in, Pair WhatsApp, Pick a model) are required —
 * HomePanel uses them to decide between the checklist and the digest. The
 * fourth step (Add knowledge) is a soft nudge; it doesn't gate the digest.
 */
export default function SetupChecklist({
  isSignedIn,
  onDismiss,
}: SetupChecklistProps) {
  const pairing = useStore((s) => s.pairing);
  const model = useStore((s) => s.readiness.model);
  const openSlideOver = useStore((s) => s.openSlideOver);

  // Knowledge step — fetch the index once on mount. We mark the step `done`
  // when the user has at least one document, `active` otherwise. A failed
  // fetch leaves the step `active` so the action stays clickable.
  const [knowledgeDone, setKnowledgeDone] = useState<boolean>(false);
  useEffect(() => {
    let cancelled = false;
    fetchKnowledgeIndex()
      .then((idx) => {
        if (!cancelled) setKnowledgeDone(idx.docs.length > 0);
      })
      .catch(() => {
        if (!cancelled) setKnowledgeDone(false);
      });
    return () => {
      cancelled = true;
    };
  }, []);

  const signInStatus: StepStatus = isSignedIn ? "done" : "active";
  const pairingStatus: StepStatus = pairing?.logged_in === true ? "done" : "active";
  const modelStatus: StepStatus = model.variant === "ok" ? "done" : "active";
  const knowledgeStatus: StepStatus = knowledgeDone ? "done" : "active";

  const steps: ChecklistStep[] = [
    {
      id: "sign-in",
      title: "Sign in",
      description: "Create or sign in to an operator account so we can remember you.",
      status: signInStatus,
      actionLabel: signInStatus === "done" ? undefined : "Sign in",
      // The app uses Clerk's <SignInButton mode="modal" /> for the actual
      // trigger (see ClerkNavAuth.tsx). The TopBar already exposes it, so
      // here we link to the fallback Clerk-hosted route in case the modal
      // isn't reachable from the home surface.
      onAction:
        signInStatus === "done"
          ? undefined
          : () => {
              window.location.href = "/sign-in";
            },
    },
    {
      id: "pair-whatsapp",
      title: "Pair WhatsApp",
      description: "Scan the QR code so the bot can read and send messages.",
      status: pairingStatus,
      actionLabel: pairingStatus === "done" ? undefined : "Open /pair",
      onAction:
        pairingStatus === "done"
          ? undefined
          : () => {
              window.open("/pair", "_blank", "noopener");
            },
    },
    {
      id: "pick-model",
      title: "Pick a model",
      description: "Choose which LLM the bot uses to reason and reply.",
      status: modelStatus,
      actionLabel: modelStatus === "done" ? undefined : "Open settings",
      onAction:
        modelStatus === "done"
          ? undefined
          : () => {
              openSlideOver("settings");
            },
    },
    {
      id: "add-knowledge",
      title: "Add knowledge",
      description: "Add at least one document so the bot can answer with context.",
      status: knowledgeStatus,
      actionLabel: knowledgeStatus === "done" ? undefined : "Visit knowledge",
      onAction:
        knowledgeStatus === "done"
          ? undefined
          : () => {
              window.location.href = "/knowledge";
            },
    },
  ];

  return (
    <section className="space-y-4" aria-labelledby="setup-checklist-heading">
      <div>
        <h3
          id="setup-checklist-heading"
          className="text-base font-semibold text-fg"
        >
          Get set up
        </h3>
        <p className="mt-1 text-sm text-fg-muted">
          A few quick steps so the bot can start working for you.
        </p>
      </div>

      <ol aria-label="Setup checklist" className="space-y-2">
        {steps.map((step) => (
          <StepRow key={step.id} step={step} />
        ))}
      </ol>

      {onDismiss && (
        <div className="pt-2">
          <button
            type="button"
            onClick={onDismiss}
            className="rounded-pill px-3 py-1.5 text-xs font-medium text-fg-muted transition hover:bg-bg-card hover:text-fg focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent"
          >
            Skip setup
          </button>
        </div>
      )}
    </section>
  );
}

interface StepRowProps {
  step: ChecklistStep;
}

function StepRow({ step }: StepRowProps) {
  return (
    <li className="flex items-start gap-3 rounded-card border border-border bg-bg-card p-3">
      <StatusIcon status={step.status} />
      <div className="flex-1 min-w-0">
        <p className="text-sm font-medium text-fg">{step.title}</p>
        <p className="mt-0.5 text-xs text-fg-muted">{step.description}</p>
      </div>
      <div className="shrink-0">
        {step.status === "done" ? (
          <span className="inline-flex items-center rounded-pill bg-ok/10 px-2.5 py-1 text-xs font-medium text-ok">
            Done
          </span>
        ) : step.actionLabel && step.onAction ? (
          <button
            type="button"
            onClick={step.onAction}
            className="rounded-pill border border-border bg-bg-app px-3 py-1.5 text-xs font-medium text-fg transition hover:bg-bg-card focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent"
          >
            {step.actionLabel}
          </button>
        ) : null}
      </div>
    </li>
  );
}

function StatusIcon({ status }: { status: StepStatus }) {
  if (status === "done") {
    return (
      <CheckCircle2
        aria-hidden="true"
        className="mt-0.5 size-5 shrink-0 text-ok"
      />
    );
  }
  if (status === "active") {
    return (
      <Loader2
        aria-hidden="true"
        className={clsx("mt-0.5 size-5 shrink-0 text-accent")}
      />
    );
  }
  return (
    <Circle
      aria-hidden="true"
      className="mt-0.5 size-5 shrink-0 text-fg-muted"
    />
  );
}
