/**
 * HTTP 客户端
 */
export interface ApiResponse<T> {
  success: boolean;
  data?: T;
  error?: string;
}

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
    const res = await fetch('/api' + url, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: body ? JSON.stringify(body) : null,
    });
    const data = await res.json();
    return res.ok ? { success: true, data } : { success: false, error: data.error };
  } catch (e: any) {
    return { success: false, error: e.message };
  }
}

export async function del(url: string): Promise<ApiResponse<any>> {
  try {
    const res = await fetch('/api' + url, { method: 'DELETE' });
    const data = await res.json();
    return res.ok ? { success: true, data } : { success: false, error: data.error };
  } catch (e: any) {
    return { success: false, error: e.message };
  }
}
