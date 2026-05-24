import { useState } from "react";

/** A controlled chip input for free-form tags. Normalises (trim/lowercase/dedupe) on add. */
export default function TagEditor({
  tags,
  onChange,
  disabled = false,
  placeholder = "add tag…",
}: {
  tags: string[];
  onChange: (next: string[]) => void;
  disabled?: boolean;
  placeholder?: string;
}) {
  const [draft, setDraft] = useState("");

  const add = () => {
    const cleaned = draft.trim().toLowerCase();
    if (cleaned && !tags.includes(cleaned)) onChange([...tags, cleaned]);
    setDraft("");
  };

  return (
    <div className="flex flex-wrap items-center gap-1">
      {tags.map((t) => (
        <span
          key={t}
          className="inline-flex items-center gap-1 rounded bg-slate-100 px-2 py-0.5 text-xs text-slate-600"
        >
          {t}
          {!disabled && (
            <button
              type="button"
              onClick={() => onChange(tags.filter((x) => x !== t))}
              className="text-slate-400 hover:text-red-600"
              aria-label={`Remove ${t}`}
            >
              ×
            </button>
          )}
        </span>
      ))}
      {!disabled && (
        <input
          value={draft}
          onChange={(e) => setDraft(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === "Enter" || e.key === ",") {
              e.preventDefault();
              add();
            }
          }}
          onBlur={add}
          placeholder={placeholder}
          className="w-24 rounded border border-slate-300 px-2 py-0.5 text-xs"
        />
      )}
      {disabled && tags.length === 0 && <span className="text-xs text-slate-400">—</span>}
    </div>
  );
}
