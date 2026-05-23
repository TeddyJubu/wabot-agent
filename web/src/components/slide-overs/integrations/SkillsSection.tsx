import { useRef, useState } from "react";
import {
  listSkills,
  scanLocalSkills,
  installSkillFromZip,
  deleteSkill,
  type SkillRow,
} from "@/api/skills";
import { RegistryBrowserModal } from "./RegistryBrowserModal";

interface Props {
  skills: SkillRow[];
  onRefresh: () => void;
}

export function SkillsSection({ skills, onRefresh }: Props) {
  const [scanning, setScanning] = useState(false);
  const [scanBanner, setScanBanner] = useState<{ added: number; removed: number } | null>(null);
  const [uploading, setUploading] = useState(false);
  const [uploadError, setUploadError] = useState<string | null>(null);
  const [deletingSlug, setDeletingSlug] = useState<string | null>(null);
  const [deleteError, setDeleteError] = useState<string | null>(null);
  const [showRegistry, setShowRegistry] = useState(false);
  const fileInputRef = useRef<HTMLInputElement>(null);

  async function doScan() {
    setScanning(true);
    setScanBanner(null);
    try {
      const result = await scanLocalSkills();
      setScanBanner(result);
      onRefresh();
    } catch (err) {
      setUploadError(err instanceof Error ? err.message : "Scan failed");
    } finally {
      setScanning(false);
    }
  }

  async function doUpload(file: File) {
    setUploading(true);
    setUploadError(null);
    try {
      await installSkillFromZip(file);
      onRefresh();
    } catch (err) {
      setUploadError(err instanceof Error ? err.message : "Upload failed");
    } finally {
      setUploading(false);
      if (fileInputRef.current) fileInputRef.current.value = "";
    }
  }

  async function doDelete(slug: string) {
    if (!window.confirm(`Delete skill "${slug}"? This cannot be undone.`)) return;
    setDeletingSlug(slug);
    setDeleteError(null);
    try {
      await deleteSkill(slug);
      onRefresh();
    } catch (err) {
      setDeleteError(err instanceof Error ? err.message : "Delete failed");
    } finally {
      setDeletingSlug(null);
    }
  }

  return (
    <section aria-label="Skills" className="space-y-3">
      {/* Section header */}
      <div className="flex items-center gap-2">
        <div className="h-px flex-1 bg-border" />
        <p className="text-[10px] font-medium uppercase tracking-wider text-fg-muted whitespace-nowrap">
          Skills ({skills.length} installed)
        </p>
        <div className="h-px flex-1 bg-border" />
      </div>

      {/* Action buttons */}
      <div className="flex flex-wrap gap-2">
        <button
          type="button"
          disabled={scanning}
          onClick={() => void doScan()}
          className="rounded-pill border border-border px-2.5 py-1 text-xs hover:bg-bg-app disabled:opacity-50"
        >
          {scanning ? "Scanning…" : "Scan local folder"}
        </button>

        <button
          type="button"
          disabled={uploading}
          onClick={() => fileInputRef.current?.click()}
          className="rounded-pill border border-border px-2.5 py-1 text-xs hover:bg-bg-app disabled:opacity-50"
        >
          {uploading ? "Uploading…" : "+ Upload .skill"}
        </button>
        <input
          ref={fileInputRef}
          type="file"
          accept=".zip,.skill"
          aria-label="Upload skill zip"
          className="sr-only"
          onChange={(e) => {
            const file = e.target.files?.[0];
            if (file) void doUpload(file);
          }}
        />

        <button
          type="button"
          onClick={() => setShowRegistry(true)}
          className="rounded-pill border border-border px-2.5 py-1 text-xs hover:bg-bg-app"
        >
          Browse registry
        </button>
      </div>

      {/* Scan delta banner */}
      {scanBanner && (
        <div className="flex items-center justify-between rounded-card border border-border bg-bg-app px-3 py-2 text-[10px] text-fg-muted">
          <span>
            Scan complete — {scanBanner.added} added · {scanBanner.removed} removed
          </span>
          <button
            type="button"
            onClick={() => setScanBanner(null)}
            aria-label="Dismiss"
            className="ml-2 text-fg-muted hover:text-fg leading-none"
          >
            ×
          </button>
        </div>
      )}

      {/* Upload/delete errors */}
      {(uploadError ?? deleteError) && (
        <p className="rounded-card border border-bad/40 bg-bad/10 px-3 py-2 text-xs text-bad">
          {uploadError ?? deleteError}
        </p>
      )}

      {/* Skill rows */}
      {skills.length === 0 ? (
        <p className="text-xs text-fg-muted">No skills installed yet.</p>
      ) : (
        <div className="space-y-1.5">
          {skills.map((skill) => (
            <SkillRow
              key={skill.slug}
              skill={skill}
              deleting={deletingSlug === skill.slug}
              onDelete={() => void doDelete(skill.slug)}
            />
          ))}
        </div>
      )}

      {/* Registry modal */}
      {showRegistry && (
        <RegistryBrowserModal
          mode="skills"
          onClose={() => setShowRegistry(false)}
          onInstalled={() => {
            setShowRegistry(false);
            onRefresh();
          }}
        />
      )}
    </section>
  );
}

// ---------------------------------------------------------------------------
// Internal helpers
// ---------------------------------------------------------------------------

interface SkillRowProps {
  skill: SkillRow;
  deleting: boolean;
  onDelete: () => void;
}

function SkillRow({ skill, deleting, onDelete }: SkillRowProps) {
  return (
    <div className="flex items-start gap-3 rounded-card border border-border px-3 py-2">
      <div className="flex-1 min-w-0 space-y-0.5">
        <div className="flex items-center gap-1.5">
          <p className="text-xs font-medium truncate">{skill.display_name}</p>
          <SourcePill source={skill.source} />
          {skill.version && (
            <span className="rounded border border-border px-1.5 py-0.5 text-[9px] text-fg-muted">
              v{skill.version}
            </span>
          )}
        </div>
        {skill.description && (
          <p className="text-[10px] text-fg-muted line-clamp-1">{skill.description}</p>
        )}
        <p
          className="text-[9px] text-fg-muted truncate"
          title={skill.install_path}
        >
          {skill.install_path}
        </p>
      </div>
      <button
        type="button"
        disabled={deleting}
        onClick={onDelete}
        aria-label={`Delete skill ${skill.slug}`}
        className="flex-shrink-0 rounded-pill border border-bad/40 bg-bad/10 px-2.5 py-1 text-[10px] font-medium text-bad hover:bg-bad/20 disabled:opacity-50"
      >
        {deleting ? "Deleting…" : "Delete"}
      </button>
    </div>
  );
}

interface SourcePillProps {
  source: string;
}

function SourcePill({ source }: SourcePillProps) {
  const colours: Record<string, string> = {
    local: "border-border text-fg-muted",
    zip: "border-blue-500/40 bg-blue-500/10 text-blue-400",
    registry: "border-green-500/40 bg-green-500/10 text-green-400",
  };
  const cls = colours[source] ?? "border-border text-fg-muted";
  return (
    <span className={`inline-block rounded border px-1.5 py-0.5 text-[9px] font-medium ${cls}`}>
      {source}
    </span>
  );
}

// Re-export for use in tests / parent
export { listSkills };
