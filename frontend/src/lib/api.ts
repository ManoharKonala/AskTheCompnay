export const API_URL = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";

export interface RetrievedChunk {
  id: number;
  filename: string;
  source_type: string;
  allowed_groups: string[];
  rerank_score?: number;
  text: string;
}

export interface QueryResponse {
  answer: string;
  citations: string[];
  retrieved_chunks: RetrievedChunk[];
  cached: boolean;
}

export interface AuditLogItem {
  id: number;
  user_id: number | null;
  query: string;
  response: string;
  timestamp: string;
  retrieved_chunks: any;
}

export interface DLQRecord {
  id: number;
  filepath: string;
  source_type: string;
  error_message: string;
  retry_count: number;
  status: string;
  created_at: string;
}

export function getStoredToken(): string | null {
  if (typeof window === "undefined") return null;
  return localStorage.getItem("atc_token");
}

export function getStoredUser(): { username: string; groups: string[] } | null {
  if (typeof window === "undefined") return null;
  const user = localStorage.getItem("atc_user");
  return user ? JSON.parse(user) : null;
}

export function setStoredSession(token: string, username: string, groups: string[]) {
  if (typeof window === "undefined") return;
  localStorage.setItem("atc_token", token);
  localStorage.setItem("atc_user", JSON.stringify({ username, groups }));
}

export function clearStoredSession() {
  if (typeof window === "undefined") return;
  localStorage.removeItem("atc_token");
  localStorage.removeItem("atc_user");
}

export async function loginUser(username: string, password: string) {
  const formData = new URLSearchParams();
  formData.append("username", username);
  formData.append("password", password);

  const res = await fetch(`${API_URL}/auth/token`, {
    method: "POST",
    headers: { "Content-Type": "application/x-www-form-urlencoded" },
    body: formData.toString(),
  });

  if (!res.ok) {
    const err = await res.json().catch(() => ({ detail: "Login failed" }));
    throw new Error(err.detail || "Invalid credentials");
  }

  const data = await res.json();
  return data;
}

export async function queryRAG(query: string, token: string): Promise<QueryResponse> {
  const res = await fetch(`${API_URL}/query`, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      Authorization: `Bearer ${token}`,
    },
    body: JSON.stringify({ query }),
  });

  if (!res.ok) {
    const err = await res.json().catch(() => ({ detail: "Query failed" }));
    throw new Error(err.detail || "Query request failed");
  }

  return res.json();
}

export async function triggerSeedIngest(token: string) {
  const res = await fetch(`${API_URL}/ingest`, {
    method: "POST",
    headers: { Authorization: `Bearer ${token}` },
  });

  if (!res.ok) {
    const err = await res.json().catch(() => ({ detail: "Ingest failed" }));
    throw new Error(err.detail || "Seed ingestion dispatch failed");
  }

  return res.json();
}

export async function uploadAndIngest(file: File, token: string) {
  const formData = new FormData();
  formData.append("file", file);

  const res = await fetch(`${API_URL}/ingest/file`, {
    method: "POST",
    headers: { Authorization: `Bearer ${token}` },
    body: formData,
  });

  if (!res.ok) {
    const err = await res.json().catch(() => ({ detail: "Upload failed" }));
    throw new Error(err.detail || "File upload failed");
  }

  return res.json();
}

export async function fetchAuditLogs(token: string, limit = 50) {
  const res = await fetch(`${API_URL}/admin/logs?limit=${limit}`, {
    headers: { Authorization: `Bearer ${token}` },
  });

  if (!res.ok) throw new Error("Failed to fetch audit logs");
  return res.json();
}

export async function fetchDLQRecords(token: string) {
  const res = await fetch(`${API_URL}/admin/dlq`, {
    headers: { Authorization: `Bearer ${token}` },
  });

  if (!res.ok) throw new Error("Failed to fetch DLQ records");
  return res.json();
}

export async function retryDLQTask(id: number, token: string) {
  const res = await fetch(`${API_URL}/admin/dlq/${id}/retry`, {
    method: "POST",
    headers: { Authorization: `Bearer ${token}` },
  });

  if (!res.ok) throw new Error("Failed to retry DLQ task");
  return res.json();
}
