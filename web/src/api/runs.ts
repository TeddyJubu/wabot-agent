export interface Run {
  run_id: string;
  sender: string | null;
  user_input: string;
  final_output: string;
  created_at: string;
}

export async function fetchRuns(limit = 20): Promise<Run[]> {
  const res = await fetch(`/api/runs?limit=${limit}`, { credentials: "include" });
  if (!res.ok) throw new Error(`runs: ${res.status}`);
  const data = await res.json();
  return Array.isArray(data) ? data : [];
}
