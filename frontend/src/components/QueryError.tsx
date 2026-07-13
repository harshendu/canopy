/**
 * Inline error state for a failed data query. Use this instead of falling through to an
 * empty/"all-clear" state on `isError` — a failed `/risks` must not read as "No risks logged",
 * and a failed `/alerts` must not read as "On track". Distinct from the empty state.
 */
export function QueryError({
  error,
  onRetry,
  label = "Couldn’t load this",
}: {
  error: unknown;
  onRetry?: () => void;
  label?: string;
}) {
  const message = error instanceof Error ? error.message : "Something went wrong.";
  return (
    <div
      role="alert"
      className="rounded-lg border border-red-200 bg-red-50 p-4 text-sm text-red-800"
    >
      <p className="font-medium">{label}</p>
      <p className="mt-1 text-red-700">{message}</p>
      {onRetry && (
        <button
          type="button"
          onClick={onRetry}
          className="mt-2 rounded-md border border-red-300 bg-white px-3 py-1 text-xs font-medium text-red-700 hover:bg-red-100"
        >
          Retry
        </button>
      )}
    </div>
  );
}
