import { demoApi } from "./demoApi";

const BASE = "/api/v1";

/** VITE_DEMO_MODE swaps every call here for an in-browser mock (see demoApi.ts) -- it's how the
 * binder designer runs standalone with no FastAPI backend for the portfolio-site embed. */
const DEMO_MODE = import.meta.env.VITE_DEMO_MODE === "true";

export async function api<T>(path: string, init?: RequestInit): Promise<T> {
  if (DEMO_MODE) return demoApi<T>(path, init);

  const res = await fetch(`${BASE}${path}`, {
    headers: { "Content-Type": "application/json" },
    ...init,
  });
  if (!res.ok) throw new Error(`${res.status} ${await res.text()}`);
  if (res.status === 204) return undefined as T;
  return res.json() as Promise<T>;
}
