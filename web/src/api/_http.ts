/**
 * Shared HTTP helpers for API modules.
 *
 * TODO: dedupe with groups.ts which has its own copy of parseJson.
 */

export async function parseJson<T>(res: Response): Promise<T> {
  const body = (await res.json().catch(() => ({}))) as T & { detail?: string };
  if (!res.ok) {
    throw new Error(
      typeof body.detail === "string" ? body.detail : `Request failed (${res.status})`,
    );
  }
  return body;
}
