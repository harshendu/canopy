import type { FormValues, SchemaField } from "../../lib/tracking";

/** Inputs for the fields a tracker's JSON Schema describes (a binding's scope). Numbers are
 *  typed as text so a bad value gets a sentence (`formPayload`), not a silently empty input. */
export function SchemaInputs({
  fields,
  values,
  onChange,
  idPrefix,
  disabled = false,
}: {
  fields: readonly SchemaField[];
  values: FormValues;
  onChange: (key: string, value: string) => void;
  idPrefix: string;
  disabled?: boolean;
}) {
  if (fields.length === 0) {
    return <p className="text-sm text-slate-500">This tracker takes no scope — it mirrors everything the connection sees.</p>;
  }
  return (
    <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
      {fields.map((f) => {
        const id = `${idPrefix}-${f.key}`;
        const hint = f.description ? `${id}-hint` : undefined;
        if (f.type === "boolean") {
          return (
            <label key={f.key} htmlFor={id} className="flex items-center gap-2 self-end py-2 text-sm text-slate-700">
              <input
                id={id}
                type="checkbox"
                checked={values[f.key] === "true"}
                onChange={(e) => onChange(f.key, e.target.checked ? "true" : "")}
                disabled={disabled}
                aria-describedby={hint}
              />
              {f.label}
              {f.description && (
                <span id={hint} className="text-xs text-slate-400">
                  {f.description}
                </span>
              )}
            </label>
          );
        }
        const numeric = f.type === "integer" || f.type === "number";
        return (
          <div key={f.key} className="flex flex-col gap-1">
            <label htmlFor={id} className="text-xs font-medium text-slate-500">
              {f.label}
              {f.required ? <span className="text-red-700"> (required)</span> : <span className="font-normal text-slate-400"> (optional)</span>}
            </label>
            <input
              id={id}
              type={f.format === "uri" ? "url" : f.format === "email" ? "email" : "text"}
              inputMode={f.type === "integer" ? "numeric" : f.type === "number" ? "decimal" : undefined}
              value={values[f.key] ?? ""}
              onChange={(e) => onChange(f.key, e.target.value)}
              disabled={disabled}
              required={f.required}
              aria-describedby={hint}
              autoComplete="off"
              spellCheck={false}
              className={`rounded border border-slate-300 px-3 py-2 text-sm text-slate-800 disabled:bg-slate-50 ${numeric ? "tabular-nums" : ""}`}
            />
            {f.description && (
              <span id={hint} className="text-xs text-slate-400">
                {f.description}
              </span>
            )}
          </div>
        );
      })}
    </div>
  );
}
