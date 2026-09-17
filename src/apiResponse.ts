export async function readApiErrorMessage(response: Response): Promise<string> {
  const raw = await response.text();
  if (!raw.trim()) return `API 请求失败（HTTP ${response.status}）`;
  try {
    const payload = JSON.parse(raw);
    const detail = payload?.detail ?? payload;
    return typeof detail === "string" ? detail : JSON.stringify(detail);
  } catch {
    return raw;
  }
}
