const TOKEN_KEY = "canopy_token";

export function getToken(): string | null {
  return localStorage.getItem(TOKEN_KEY);
}

export function setToken(token: string | null): void {
  if (token) localStorage.setItem(TOKEN_KEY, token);
  else localStorage.removeItem(TOKEN_KEY);
}

export class ApiError extends Error {
  constructor(public status: number, message: string) {
    super(message);
  }
}

async function request<T>(path: string, options: RequestInit = {}): Promise<T> {
  const token = getToken();
  const headers = new Headers(options.headers);
  if (token) headers.set("Authorization", `Bearer ${token}`);
  if (options.body && !headers.has("Content-Type") && !(options.body instanceof FormData)) {
    // Let the browser set the multipart boundary for FormData uploads.
    headers.set("Content-Type", "application/json");
  }
  const resp = await fetch(`/api/v1${path}`, { ...options, headers });
  if (resp.status === 401) {
    setToken(null);
    throw new ApiError(401, "Unauthorized");
  }
  if (!resp.ok) {
    const detail = await resp.text();
    throw new ApiError(resp.status, detail || resp.statusText);
  }
  if (resp.status === 204) return undefined as T;
  return (await resp.json()) as T;
}

export const api = {
  get: <T>(path: string) => request<T>(path),
  post: <T>(path: string, body?: unknown) =>
    request<T>(path, { method: "POST", body: body ? JSON.stringify(body) : undefined }),
  patch: <T>(path: string, body: unknown) =>
    request<T>(path, { method: "PATCH", body: JSON.stringify(body) }),
  del: (path: string) => request<void>(path, { method: "DELETE" }),
  upload: <T>(path: string, form: FormData) =>
    request<T>(path, { method: "POST", body: form }),
};

/** Fetch a binary/file endpoint and trigger a browser download. Honors the server's
 *  Content-Disposition filename when present, else uses `fallbackName`. */
export async function downloadExport(path: string, fallbackName: string): Promise<void> {
  const token = getToken();
  const headers = new Headers();
  if (token) headers.set("Authorization", `Bearer ${token}`);
  const resp = await fetch(`/api/v1${path}`, { headers });
  if (!resp.ok) {
    const detail = await resp.text();
    throw new ApiError(resp.status, detail || resp.statusText);
  }
  const blob = await resp.blob();
  const disposition = resp.headers.get("content-disposition") ?? "";
  const match = /filename="?([^";]+)"?/.exec(disposition);
  const filename = match ? match[1] : fallbackName;
  const url = URL.createObjectURL(blob);
  const anchor = document.createElement("a");
  anchor.href = url;
  anchor.download = filename;
  document.body.appendChild(anchor);
  anchor.click();
  anchor.remove();
  URL.revokeObjectURL(url);
}

export async function login(email: string, password: string): Promise<string> {
  const form = new URLSearchParams({ username: email, password });
  const resp = await fetch("/api/v1/auth/login", {
    method: "POST",
    headers: { "Content-Type": "application/x-www-form-urlencoded" },
    body: form,
  });
  if (!resp.ok) throw new ApiError(resp.status, "Login failed");
  const data = (await resp.json()) as { access_token: string };
  return data.access_token;
}
