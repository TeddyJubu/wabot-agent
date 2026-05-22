/**
 * Shared form-field primitives for the SettingsPanel section components.
 * Carved out of `SettingsPanel.tsx` as part of MASTER ME-6 so each section
 * can import them without round-tripping through the parent module.
 */

interface FieldProps {
  label: string;
  value: string;
  placeholder?: string;
  type?: string;
  onChange: (v: string) => void;
}

export function Field({ label, value, placeholder, type = "text", onChange }: FieldProps) {
  return (
    <label className="block">
      <span className="text-xs text-fg-muted">{label}</span>
      <input
        type={type}
        value={value}
        placeholder={placeholder}
        autoComplete="off"
        spellCheck={false}
        onChange={(e) => onChange(e.target.value)}
        className="mt-1 w-full rounded-card border border-border bg-bg-card px-3 py-2 text-sm font-mono"
      />
    </label>
  );
}

interface SelectFieldProps {
  label: string;
  value: string;
  choices: string[];
  choiceLabels?: Record<string, string>;
  onChange: (v: string) => void;
}

export function SelectField({
  label,
  value,
  choices,
  choiceLabels,
  onChange,
}: SelectFieldProps) {
  const options = choices.includes(value) ? choices : [value, ...choices];
  return (
    <label className="block">
      <span className="text-xs text-fg-muted">{label}</span>
      <select
        value={value}
        onChange={(e) => onChange(e.target.value)}
        className="mt-1 w-full rounded-card border border-border bg-bg-card px-3 py-2 text-sm"
      >
        {options.map((choice) => (
          <option key={choice} value={choice}>
            {choiceLabels?.[choice] ?? choice}
          </option>
        ))}
      </select>
    </label>
  );
}
