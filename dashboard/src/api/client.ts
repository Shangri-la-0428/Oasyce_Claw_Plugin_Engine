/**
 * HTTP 客户端 — 带 API token 认证、超时、重试
 */
export interface ApiResponse<T> {
  success: boolean;
  data?: T;
  error?: string;
}

// ── Config ─────────────────────────────────────────────────
const REQUEST_TIMEOUT_MS = 30_000;
const TOKEN_TIMEOUT_MS = 5_000;

// ── API Token ──────────────────────────────────────────────
let _token: string | null = null;

async function ensureToken(): Promise<string> {
  if (_token) return _token;
  try {
    const controller = new AbortController();
    const timer = setTimeout(() => controller.abort(), TOKEN_TIMEOUT_MS);
    const res = await fetch('/api/auth/token', { signal: controller.signal });
    clearTimeout(timer);
    if (res.ok) {
      const data = await res.json();
      _token = data.token || '';
    }
  } catch {
    // Token not available (e.g. dev mode without backend)
  }
  return _token || '';
}

function authHeaders(): Record<string, string> {
  if (!_token) return {};
  return { 'Authorization': `Bearer ${_token}` };
}

/** Map HTTP status to an i18n key (resolved by showToast) */
function httpError(status: number, serverError?: string): string {
  if (serverError) return serverError;
  switch (status) {
    case 401: case 403: return 'error-unauthorized';
    case 429: return 'error-rate-limit';
    case 404: return 'error-not-found';
    case 500: case 502: case 503: return 'error-server';
    default: return 'error-generic';
  }
}

/** Classify network errors into i18n keys */
function networkError(e: unknown): string {
  if (e instanceof DOMException && e.name === 'AbortError') {
    return 'error-timeout';
  }
  if (e instanceof TypeError && (e.message.includes('fetch') || e.message.includes('network') || e.message.includes('Failed'))) {
    return 'error-network';
  }
  return 'error-generic';
}

/** Safely parse JSON from a Response, returning null on failure */
async function safeJson(res: Response): Promise<any> {
  try {
    const text = await res.text();
    if (!text) return null;
    return JSON.parse(text);
  } catch {
    return null;
  }
}

/** Create an AbortController with a timeout */
function withTimeout(ms: number = REQUEST_TIMEOUT_MS): { signal: AbortSignal; clear: () => void } {
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), ms);
  return { signal: controller.signal, clear: () => clearTimeout(timer) };
}

// Initialize token on module load
ensureToken();

// ── API Methods ────────────────────────────────────────────

export async function get<T>(url: string): Promise<ApiResponse<T>> {
  const { signal, clear } = withTimeout();
  try {
    await ensureToken();
    const res = await fetch('/api' + url, { headers: authHeaders(), signal });
    clear();
    const data = await safeJson(res);
    return res.ok
      ? { success: true, data: data ?? undefined }
      : { success: false, error: httpError(res.status, data?.error) };
  } catch (e: unknown) {
    clear();
    return { success: false, error: networkError(e) };
  }
}

export async function post<T>(url: string, body?: any): Promise<ApiResponse<T>> {
  const { signal, clear } = withTimeout();
  try {
    await ensureToken();
    const res = await fetch('/api' + url, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', ...authHeaders() },
      body: body ? JSON.stringify(body) : null,
      signal,
    });
    clear();
    const data = await safeJson(res);
    return res.ok
      ? { success: true, data: data ?? undefined }
      : { success: false, error: httpError(res.status, data?.error) };
  } catch (e: unknown) {
    clear();
    return { success: false, error: networkError(e) };
  }
}

export async function postFile<T>(url: string, file: File, fields: Record<string, string> = {}): Promise<ApiResponse<T>> {
  // File uploads get a longer timeout (2 min)
  const { signal, clear } = withTimeout(120_000);
  try {
    await ensureToken();
    const fd = new FormData();
    fd.append('file', file);
    for (const [k, v] of Object.entries(fields)) fd.append(k, v);
    const res = await fetch('/api' + url, {
      method: 'POST',
      headers: authHeaders(),
      body: fd,
      signal,
    });
    clear();
    const data = await safeJson(res);
    return res.ok
      ? { success: true, data: data ?? undefined }
      : { success: false, error: httpError(res.status, data?.error) };
  } catch (e: unknown) {
    clear();
    return { success: false, error: networkError(e) };
  }
}

export async function postBundle<T>(files: File[], fields: Record<string, string> = {}): Promise<ApiResponse<T>> {
  // Bundle uploads get a longer timeout (3 min)
  const { signal, clear } = withTimeout(180_000);
  try {
    await ensureToken();
    const fd = new FormData();
    for (const f of files) fd.append('files', f, f.name);
    for (const [k, v] of Object.entries(fields)) fd.append(k, v);
    const res = await fetch('/api/register-bundle', {
      method: 'POST',
      headers: authHeaders(),
      body: fd,
      signal,
    });
    clear();
    const data = await safeJson(res);
    return res.ok
      ? { success: true, data: data ?? undefined }
      : { success: false, error: httpError(res.status, data?.error) };
  } catch (e: unknown) {
    clear();
    return { success: false, error: networkError(e) };
  }
}

export async function del(url: string): Promise<ApiResponse<any>> {
  const { signal, clear } = withTimeout();
  try {
    await ensureToken();
    const res = await fetch('/api' + url, {
      method: 'DELETE',
      headers: authHeaders(),
      signal,
    });
    clear();
    const data = await safeJson(res);
    return res.ok
      ? { success: true, data: data ?? undefined }
      : { success: false, error: httpError(res.status, data?.error) };
  } catch (e: unknown) {
    clear();
    return { success: false, error: networkError(e) };
  }
}
