function normalizeError(path: string, status: number, text: string): string {
  try {
    const parsed = JSON.parse(text) as { detail?: unknown };
    const detail = parsed.detail;
    if (detail === 'workspace_not_initialized') {
      return 'Workspace not initialized. Complete setup before using this feature.';
    }
    if (typeof detail === 'string') {
      if (detail.includes('Traceback')) {
        return 'The operation failed while processing this file. Please verify the selected institution and input format.';
      }
      return detail;
    }
  } catch {
    // no-op
  }

  if (!text.trim()) {
    return `${path} failed (${status})`;
  }
  return text;
}

export async function apiGet<T>(path: string, opts?: { signal?: AbortSignal }): Promise<T> {
  const res = await fetch(path, opts?.signal ? { signal: opts.signal } : undefined);
  if (!res.ok) {
    const text = await res.text();
    throw new Error(normalizeError(path, res.status, text));
  }
  return (await res.json()) as T;
}

export async function apiPost<T>(path: string, body: unknown): Promise<T> {
  const res = await fetch(path, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body)
  });
  if (!res.ok) {
    const text = await res.text();
    throw new Error(normalizeError(path, res.status, text));
  }
  return (await res.json()) as T;
}

export async function apiDelete<T>(path: string): Promise<T> {
  const res = await fetch(path, { method: 'DELETE' });
  if (!res.ok) {
    const text = await res.text();
    throw new Error(normalizeError(path, res.status, text));
  }
  return (await res.json()) as T;
}
