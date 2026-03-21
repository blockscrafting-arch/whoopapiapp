export async function apiGet(path) {
  const res = await fetch(path, {
    credentials: "include",
    headers: { Accept: "application/json" },
  });
  const text = await res.text();
  let data = null;
  try {
    data = text ? JSON.parse(text) : null;
  } catch {
    data = { detail: text || "Неверный ответ сервера" };
  }
  if (!res.ok) {
    const msg = data?.detail || data?.message || `Ошибка ${res.status}`;
    throw new Error(typeof msg === "string" ? msg : JSON.stringify(msg));
  }
  return data;
}

export async function apiPost(path) {
  const res = await fetch(path, {
    method: "POST",
    credentials: "include",
    headers: { Accept: "application/json" },
  });
  const text = await res.text();
  let data = null;
  try {
    data = text ? JSON.parse(text) : null;
  } catch {
    data = { detail: text };
  }
  if (!res.ok) {
    const msg = data?.detail || `Ошибка ${res.status}`;
    throw new Error(typeof msg === "string" ? msg : JSON.stringify(msg));
  }
  return data;
}
