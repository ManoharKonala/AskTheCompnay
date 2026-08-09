"use client";

import { useState, useEffect } from "react";
import {
  getStoredToken,
  triggerSeedIngest,
  uploadAndIngest,
  fetchAuditLogs,
  fetchDLQRecords,
  retryDLQTask,
  AuditLogItem,
  DLQRecord,
} from "@/lib/api";

export default function AdminPage() {
  const [token, setToken] = useState<string | null>(null);
  const [activeTab, setActiveTab] = useState<"ingest" | "dlq" | "audit">("ingest");
  const [loading, setLoading] = useState(false);
  const [message, setMessage] = useState<{ type: "success" | "error"; text: string } | null>(null);

  // File upload state
  const [selectedFile, setSelectedFile] = useState<File | null>(null);

  // DLQ state
  const [dlqRecords, setDlqRecords] = useState<DLQRecord[]>([]);
  const [dlqTotal, setDlqTotal] = useState(0);

  // Audit logs state
  const [auditLogs, setAuditLogs] = useState<AuditLogItem[]>([]);
  const [auditTotal, setAuditTotal] = useState(0);

  useEffect(() => {
    const t = getStoredToken();
    setToken(t);
  }, []);

  const loadDLQ = async () => {
    if (!token) return;
    try {
      const data = await fetchDLQRecords(token);
      setDlqRecords(data.records || []);
      setDlqTotal(data.total || 0);
    } catch (err: any) {
      setMessage({ type: "error", text: err.message || "Failed to load DLQ" });
    }
  };

  const loadAuditLogs = async () => {
    if (!token) return;
    try {
      const data = await fetchAuditLogs(token);
      setAuditLogs(data.logs || []);
      setAuditTotal(data.total || 0);
    } catch (err: any) {
      setMessage({ type: "error", text: err.message || "Failed to load audit logs" });
    }
  };

  useEffect(() => {
    if (token) {
      if (activeTab === "dlq") loadDLQ();
      if (activeTab === "audit") loadAuditLogs();
    }
  }, [activeTab, token]);

  const handleSeedIngest = async () => {
    if (!token) {
      setMessage({ type: "error", text: "Please log in with admin privileges first." });
      return;
    }
    setLoading(true);
    setMessage(null);
    try {
      const res = await triggerSeedIngest(token);
      setMessage({ type: "success", text: res.message || "Seed ingestion triggered!" });
    } catch (err: any) {
      setMessage({ type: "error", text: err.message || "Seed ingestion failed." });
    } finally {
      setLoading(false);
    }
  };

  const handleFileUpload = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!token) {
      setMessage({ type: "error", text: "Please log in with admin privileges first." });
      return;
    }
    if (!selectedFile) {
      setMessage({ type: "error", text: "Please choose a file to upload." });
      return;
    }

    setLoading(true);
    setMessage(null);
    try {
      const res = await uploadAndIngest(selectedFile, token);
      setMessage({ type: "success", text: `Uploaded ${selectedFile.name}. Celery task: ${res.task}` });
      setSelectedFile(null);
    } catch (err: any) {
      setMessage({ type: "error", text: err.message || "Upload failed." });
    } finally {
      setLoading(false);
    }
  };

  const handleRetryDLQ = async (id: number) => {
    if (!token) return;
    try {
      await retryDLQTask(id, token);
      setMessage({ type: "success", text: `Task ${id} re-dispatched to Celery worker.` });
      loadDLQ();
    } catch (err: any) {
      setMessage({ type: "error", text: err.message || "Retry failed." });
    }
  };

  return (
    <div className="space-y-6 max-w-6xl mx-auto py-2">
      <div className="flex flex-wrap items-center justify-between gap-4 border-b border-slate-800 pb-4">
        <div>
          <h1 className="text-2xl font-bold text-white flex items-center gap-2">
            <span>⚙️</span> System Administration Console
          </h1>
          <p className="text-xs text-slate-400">
            Manage asynchronous Celery workers, Dead Letter Queue (DLQ), and query audit trails.
          </p>
        </div>

        {/* Tab Switcher */}
        <div className="flex rounded-xl bg-slate-900 p-1 border border-slate-800">
          <button
            onClick={() => setActiveTab("ingest")}
            className={`px-3.5 py-1.5 rounded-lg text-xs font-medium transition ${
              activeTab === "ingest" ? "bg-blue-600 text-white" : "text-slate-400 hover:text-white"
            }`}
          >
            Data Ingestion
          </button>
          <button
            onClick={() => setActiveTab("dlq")}
            className={`px-3.5 py-1.5 rounded-lg text-xs font-medium transition ${
              activeTab === "dlq" ? "bg-blue-600 text-white" : "text-slate-400 hover:text-white"
            }`}
          >
            Dead Letter Queue (DLQ)
          </button>
          <button
            onClick={() => setActiveTab("audit")}
            className={`px-3.5 py-1.5 rounded-lg text-xs font-medium transition ${
              activeTab === "audit" ? "bg-blue-600 text-white" : "text-slate-400 hover:text-white"
            }`}
          >
            Audit Logs
          </button>
        </div>
      </div>

      {message && (
        <div
          className={`p-4 rounded-xl text-sm border ${
            message.type === "success"
              ? "bg-emerald-500/10 border-emerald-500/30 text-emerald-300"
              : "bg-rose-500/10 border-rose-500/30 text-rose-300"
          }`}
        >
          {message.type === "success" ? "✅ " : "⚠️ "}
          {message.text}
        </div>
      )}

      {/* TAB 1: Ingestion */}
      {activeTab === "ingest" && (
        <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
          {/* Seed Ingestion Card */}
          <div className="glass-panel rounded-2xl p-6 space-y-4">
            <h2 className="text-base font-bold text-white flex items-center gap-2">
              <span>📦</span> Seed Corpus Ingestion
            </h2>
            <p className="text-xs text-slate-400 leading-relaxed">
              Scans all files under <code className="text-blue-300 bg-slate-950 px-1 py-0.5 rounded">data/seed/</code> (PDF policies, Slack conversations, Confluence markdown, and Excel spreadsheets), uploads them to MinIO, and dispatches Celery workers.
            </p>
            <button
              onClick={handleSeedIngest}
              disabled={loading}
              className="w-full py-3 px-4 rounded-xl bg-blue-600 hover:bg-blue-500 text-white font-semibold text-sm transition shadow-lg shadow-blue-600/20 disabled:opacity-50"
            >
              {loading ? "Dispatching Celery Pipeline..." : "🚀 Trigger Batch Seed Ingestion"}
            </button>
          </div>

          {/* Dynamic File Upload */}
          <div className="glass-panel rounded-2xl p-6 space-y-4">
            <h2 className="text-base font-bold text-white flex items-center gap-2">
              <span>📤</span> Direct Document Upload
            </h2>
            <p className="text-xs text-slate-400 leading-relaxed">
              Upload a single document (.pdf, .md, .json, .csv, .xlsx). The system will automatically redact PII, calculate MinHash LSH deduplication, and index into Qdrant.
            </p>
            <form onSubmit={handleFileUpload} className="space-y-3">
              <input
                type="file"
                accept=".pdf,.md,.json,.csv,.xlsx"
                onChange={(e) => setSelectedFile(e.target.files?.[0] || null)}
                className="w-full text-xs text-slate-400 file:mr-3 file:py-2 file:px-3 file:rounded-lg file:border-0 file:text-xs file:font-semibold file:bg-slate-800 file:text-slate-200 hover:file:bg-slate-700 cursor-pointer"
              />
              <button
                type="submit"
                disabled={loading || !selectedFile}
                className="w-full py-2.5 px-4 rounded-xl bg-indigo-600 hover:bg-indigo-500 text-white font-semibold text-sm transition shadow-lg shadow-indigo-600/20 disabled:opacity-50"
              >
                Upload & Ingest to Vector DB
              </button>
            </form>
          </div>
        </div>
      )}

      {/* TAB 2: Dead Letter Queue (DLQ) */}
      {activeTab === "dlq" && (
        <div className="glass-panel rounded-2xl p-6 space-y-4">
          <div className="flex items-center justify-between">
            <div>
              <h2 className="text-base font-bold text-white flex items-center gap-2">
                <span>🛑</span> Dead Letter Queue (Failed Tasks)
              </h2>
              <p className="text-xs text-slate-400">
                Tasks that permanently exhausted their retry limit (3 retries with exponential backoff).
              </p>
            </div>
            <button
              onClick={loadDLQ}
              className="text-xs px-3 py-1.5 rounded-lg bg-slate-800 hover:bg-slate-700 text-slate-300 border border-slate-700"
            >
              🔄 Refresh
            </button>
          </div>

          {dlqRecords.length === 0 ? (
            <div className="text-center py-12 text-slate-500 text-sm">
              ✨ No failed tasks in Dead Letter Queue. All ingestion tasks healthy!
            </div>
          ) : (
            <div className="overflow-x-auto">
              <table className="w-full text-left text-xs border-collapse">
                <thead>
                  <tr className="border-b border-slate-800 text-slate-400 font-semibold uppercase tracking-wider">
                    <th className="py-2.5 px-3">ID</th>
                    <th className="py-2.5 px-3">Filepath / URI</th>
                    <th className="py-2.5 px-3">Source</th>
                    <th className="py-2.5 px-3">Retries</th>
                    <th className="py-2.5 px-3">Error Message</th>
                    <th className="py-2.5 px-3">Status</th>
                    <th className="py-2.5 px-3 text-right">Action</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-slate-800/60 font-mono">
                  {dlqRecords.map((rec) => (
                    <tr key={rec.id} className="hover:bg-slate-900/40">
                      <td className="py-3 px-3 text-slate-400">{rec.id}</td>
                      <td className="py-3 px-3 text-white max-w-xs truncate">{rec.filepath}</td>
                      <td className="py-3 px-3">
                        <span className="px-1.5 py-0.5 rounded text-[10px] bg-slate-800 text-slate-300 uppercase">
                          {rec.source_type}
                        </span>
                      </td>
                      <td className="py-3 px-3 text-amber-400">{rec.retry_count}</td>
                      <td className="py-3 px-3 text-rose-300 max-w-sm truncate" title={rec.error_message}>
                        {rec.error_message}
                      </td>
                      <td className="py-3 px-3">
                        <span
                          className={`px-1.5 py-0.5 rounded text-[10px] ${
                            rec.status === "FAILED"
                              ? "bg-rose-950 text-rose-300 border border-rose-800"
                              : "bg-emerald-950 text-emerald-300 border border-emerald-800"
                          }`}
                        >
                          {rec.status}
                        </span>
                      </td>
                      <td className="py-3 px-3 text-right">
                        <button
                          onClick={() => handleRetryDLQ(rec.id)}
                          className="px-2.5 py-1 rounded bg-blue-600 hover:bg-blue-500 text-white text-[11px] font-sans transition"
                        >
                          Retry Task
                        </button>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </div>
      )}

      {/* TAB 3: Audit Logs */}
      {activeTab === "audit" && (
        <div className="glass-panel rounded-2xl p-6 space-y-4">
          <div className="flex items-center justify-between">
            <div>
              <h2 className="text-base font-bold text-white flex items-center gap-2">
                <span>📜</span> Query Audit & Compliance Log
              </h2>
              <p className="text-xs text-slate-400">
                Immutable query history with user correlation, generated answer, and retrieved chunks.
              </p>
            </div>
            <button
              onClick={loadAuditLogs}
              className="text-xs px-3 py-1.5 rounded-lg bg-slate-800 hover:bg-slate-700 text-slate-300 border border-slate-700"
            >
              🔄 Refresh
            </button>
          </div>

          {auditLogs.length === 0 ? (
            <div className="text-center py-12 text-slate-500 text-sm">
              No audit records recorded yet. Execute queries to see entries.
            </div>
          ) : (
            <div className="overflow-x-auto">
              <table className="w-full text-left text-xs border-collapse">
                <thead>
                  <tr className="border-b border-slate-800 text-slate-400 font-semibold uppercase tracking-wider">
                    <th className="py-2.5 px-3">Time</th>
                    <th className="py-2.5 px-3">User ID</th>
                    <th className="py-2.5 px-3">Query</th>
                    <th className="py-2.5 px-3">Response Snippet</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-slate-800/60 font-mono">
                  {auditLogs.map((log) => (
                    <tr key={log.id} className="hover:bg-slate-900/40">
                      <td className="py-3 px-3 text-slate-400 whitespace-nowrap">
                        {log.timestamp ? new Date(log.timestamp).toLocaleTimeString() : "-"}
                      </td>
                      <td className="py-3 px-3 text-blue-300">{log.user_id ?? "Anon"}</td>
                      <td className="py-3 px-3 text-white max-w-xs truncate">{log.query}</td>
                      <td className="py-3 px-3 text-slate-300 max-w-md truncate">{log.response}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </div>
      )}
    </div>
  );
}
