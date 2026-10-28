// All calls to the backend live here, so the rest of the app never builds URLs.
const API_URL = (import.meta.env.VITE_API_URL || "http://127.0.0.1:8000").replace(/\/$/, "");

async function get(path) {
  const res = await fetch(`${API_URL}${path}`);
  if (!res.ok) throw new Error(`${path} returned ${res.status}`);
  return res.json();
}

export const fetchGames = () => get("/api/games");
export const fetchHeadlines = () => get("/api/headlines?limit=12");
export const fetchModel = () => get("/api/model");
