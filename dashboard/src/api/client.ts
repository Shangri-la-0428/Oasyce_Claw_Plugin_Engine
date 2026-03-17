/**
 * HTTP 客户端 — 带 API token 认证
 */
export interface ApiResponse<T> {
  success: boolean;
  data?: T;
  error?: string;
}

// ── API Token ──────────────────────────────────────────────
let _token: string | null = null;

async function ensureToken(): Promise<string> {
  if (_token) return _token;
  try {
    const res = await fetch('/api/auth/token');
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

// Initialize token on module load
ensureToken();

// ── API Methods ────────────────────────────────────────────

export async function get<T>(url: string): Promise<ApiResponse<T>> {
  try {
    const res = await fetch('/api' + url);
    const data = await res.json();
    return res.ok ? { success: true, data } : { success: false, error: data.error };
  } catch (e: any) {
    return { success: false, error: e.message };
  }
}

export async function post<T>(url: string, body?: any): Promise<ApiResponse<T>> {
  try {
    await ensureToken();
    const res = await fetch('/api' + url, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', ...authHeaders() },
      body: body ? JSON.stringify(body) : null,
    });
    const data = await res.json();
    return res.ok ? { success: true, data } : { success: false, error: data.error };
  } catch (e: any) {
    return { success: false, error: e.message };
  }
}

export async function postFile<T>(url: string, file: File, fields: Record<string, string> = {}): Promise<ApiResponse<T>> {
  try {
    await ensureToken();
    const fd = new FormData();
    fd.append('file', file);
    for (const [k, v] of Object.entries(fields)) fd.append(k, v);
    const res = await fetch('/api' + url, {
      method: 'POST',
      headers: authHeaders(),
      body: fd,
    });
    const data = await res.json();
    return res.ok ? { success: true, data } : { success: false, error: data.error };
  } catch (e: any) {
    return { success: false, error: e.message };
  }
}

export async function postBundle<T>(files: File[], fields: Record<string, string> = {}): Promise<ApiResponse<T>> {
  try {
    await ensureToken();
    const fd = new FormData();
    for (const f of files) fd.append('files', f, f.name);
    for (const [k, v] of Object.entries(fields)) fd.append(k, v);
    const res = await fetch('/api/register-bundle', {
      method: 'POST',
      headers: authHeaders(),
      body: fd,
    });
    const data = await res.json();
    return res.ok ? { success: true, data } : { success: false, error: data.error };
  } catch (e: any) {
    return { success: false, error: e.message };
  }
}

export async function del(url: string): Promise<ApiResponse<any>> {
  try {
    await ensureToken();
    const res = await fetch('/api' + url, {
      method: 'DELETE',
      headers: authHeaders(),
    });
    const data = await res.json();
    return res.ok ? { success: true, data } : { success: false, error: data.error };
  } catch (e: any) {
    return { success: false, error: e.message };
  }
}
