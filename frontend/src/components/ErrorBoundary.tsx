import { Component, type ReactNode } from "react";

/**
 * App-level error boundary: a single uncaught render throw would otherwise unmount the whole
 * React tree to a blank white screen. This catches it and shows a recoverable fallback so one bad
 * view degrades locally instead of taking down the SPA.
 */
export class ErrorBoundary extends Component<
  { children: ReactNode },
  { error: Error | null }
> {
  state: { error: Error | null } = { error: null };

  static getDerivedStateFromError(error: Error): { error: Error } {
    return { error };
  }

  render(): ReactNode {
    if (this.state.error) {
      return (
        <div className="flex min-h-screen items-center justify-center bg-slate-50 p-6">
          <div className="max-w-md rounded-xl border border-slate-200 bg-white p-6 text-center shadow-sm">
            <h1 className="text-lg font-semibold text-slate-800">Something went wrong</h1>
            <p className="mt-2 text-sm text-slate-500">
              This screen hit an unexpected error. Your data is safe — reloading usually fixes it.
            </p>
            <p className="mt-2 break-words font-mono text-xs text-slate-400">
              {this.state.error.message}
            </p>
            <button
              type="button"
              onClick={() => window.location.reload()}
              className="mt-4 rounded-lg bg-emerald-700 px-4 py-2 text-sm font-medium text-white hover:bg-emerald-800"
            >
              Reload
            </button>
          </div>
        </div>
      );
    }
    return this.props.children;
  }
}
