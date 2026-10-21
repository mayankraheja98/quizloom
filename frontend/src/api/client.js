const BASE = "/api";

async function req(method, path, body, isForm = false) {
  const opts = { method, headers: {} };
  const token = localStorage.getItem("token");
  if (token) opts.headers["Authorization"] = `Bearer ${token}`;
  if (body) {
    if (isForm) {
      opts.body = body; // FormData — no Content-Type header (browser sets boundary)
    } else {
      opts.headers["Content-Type"] = "application/json";
      opts.body = JSON.stringify(body);
    }
  }
  const res = await fetch(`${BASE}${path}`, opts);
  if (res.status === 401 && !path.startsWith("/auth/")) {
    localStorage.removeItem("token");
    window.location.href = "/login";
  }
  if (!res.ok) {
    const err = await res.json().catch(() => ({ detail: res.statusText }));
    throw new Error(err.detail || "Request failed");
  }
  return res.json();
}

// ── Auth ──────────────────────────────────────────────────────────────────────
export const signup = (body) => req("POST", "/auth/signup", body);
export const getAuthConfig = () => req("GET", "/auth/config");
export const login = (body) => req("POST", "/auth/login", body);

// ── Upload ────────────────────────────────────────────────────────────────────
export const uploadFile = (formData) => req("POST", "/upload", formData, true);
export const getLabelStatus = (name) => req("GET", `/upload/status/${encodeURIComponent(name)}`);
export const generateFromTopic = (body) => req("POST", "/upload/generate-from-topic", body);
export const fromNotion = (body) => req("POST", "/upload/from-notion", body);
export const getLimits = () => req("GET", "/upload/limits");
export const getProviders = () => req("GET", "/upload/providers");

// ── Question bank ─────────────────────────────────────────────────────────────
export const getLabels = () => req("GET", "/labels");
export const getQuestions = (labelId, page = 1, size = 20) =>
  req("GET", `/questions?${new URLSearchParams({ label_id: labelId, page, size })}`);
export const deleteQuestion = (id) => req("DELETE", `/questions/${id}`);
export const deleteLabel = (id) => req("DELETE", `/labels/${id}`);

// ── Exam ──────────────────────────────────────────────────────────────────────
export const createExam = (body) => req("POST", "/exam/create", body);
export const startExam = (id) => req("POST", `/exam/${id}/start`);
export const getExam = (id) => req("GET", `/exam/${id}`);
export const submitExam = (id, answers) => req("POST", `/exam/${id}/submit`, { answers });
export const getResults = (id) => req("GET", `/exam/${id}/results`);
export const listExams = () => req("GET", "/exam");
