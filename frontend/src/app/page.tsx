"use client";

import { useState, useEffect } from "react";
import { queryRAG, getStoredToken, getStoredUser, QueryResponse, RetrievedChunk } from "@/lib/api";
import Link from "next/link";

export default function SearchPage() {
  const [query, setQuery] = useState("");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [result, setResult] = useState<QueryResponse | null>(null);
  const [user, setUser] = useState<{ username: string; groups: string[] } | null>(null);
  const [token, setToken] = useState<string | null>(null);

  useEffect(() => {
    const t = getStoredToken();
    const u = getStoredUser();
    setToken(t);
    setUser(u);
  }, []);

  const handleSearch = async (e?: React.FormEvent) => {
    if (e) e.preventDefault();
    if (!query.trim()) return;
    if (!token) {
      setError("Please log in or select a demo role first.");
      return;
    }

    setLoading(true);
    setError(null);
    try {
      const data = await queryRAG(query, token);
      setResult(data);
    } catch (err: any) {
      setError(err.message || "Search failed");
    } finally {
      setLoading(false);
    }
  };

  const sampleQueries = [
    "What is the annual leave and PTO policy?",
    "Show me the executive salary and compensation details",
    "What were the key decisions in the engineering Slack channel?",
    "What are the travel reimbursement limits for managers?",
  ];

  return (
    <div className="space-y-8">
      {/* User Session Banner */}
      <div className="glass-panel rounded-2xl p-5 flex flex-wrap items-center justify-between gap-4 border-l-4 border-l-blue-500">
        <div>
          <div className="flex items-center gap-2">
            <span className="text-xs uppercase tracking-wider text-slate-400 font-semibold">Active Session:</span>
            <span className="text-sm font-bold text-white">
              {user ? user.username : "Not Authenticated"}
            </span>
          </div>
          <div className="flex items-center gap-1.5 mt-2 flex-wrap">
            <span className="text-xs text-slate-400">Assigned ACL Groups:</span>
            {user?.groups && user.groups.length > 0 ? (
              user.groups.map((g) => (
                <span
                  key={g}
                  className="px-2 py-0.5 rounded text-xs font-mono font-medium bg-slate-800 text-blue-300 border border-slate-700"
                >
                  {g}
                </span>
              ))
            ) : (
              <span className="text-xs text-amber-400">Public Only</span>
            )}
          </div>
        </div>
        <div>
          <Link
            href="/login"
            className="text-xs px-3.5 py-1.5 rounded-lg bg-slate-800 hover:bg-slate-700 text-slate-200 border border-slate-700 transition"
          >
            Switch User Role →
          </Link>
        </div>
      </div>

      {/* Hero & Search Box */}
      <div className="text-center max-w-3xl mx-auto space-y-4 pt-4">
        <h1 className="text-4xl font-extrabold tracking-tight text-white sm:text-5xl">
          Enterprise Search with <span className="gradient-text">Zero-Trust ACLs</span>
        </h1>
        <p className="text-slate-400 text-sm sm:text-base">
          Query private corporate documents, scanned policies, Excel spreadsheets, and live Slack threads with database-enforced permissions and Presidio PII redaction.
        </p>

        <form onSubmit={handleSearch} className="relative mt-6 max-w-2xl mx-auto">
          <input
            type="text"
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            placeholder="Ask a question about policies, finances, or Slack threads..."
            className="w-full px-5 py-4 rounded-2xl bg-slate-900/90 border border-slate-700 text-white placeholder-slate-500 focus:outline-none focus:ring-2 focus:ring-blue-500 focus:border-transparent text-sm sm:text-base shadow-xl pr-28"
          />
          <button
            type="submit"
            disabled={loading}
            className="absolute right-2.5 top-2.5 bottom-2.5 px-5 rounded-xl bg-blue-600 hover:bg-blue-500 text-white font-medium text-sm transition-all shadow-md shadow-blue-600/30 flex items-center justify-center disabled:opacity-50"
          >
            {loading ? (
              <span className="inline-block animate-spin h-4 w-4 border-2 border-white border-t-transparent rounded-full" />
            ) : (
              "Search"
            )}
          </button>
        </form>

        {/* Suggested Queries */}
        <div className="flex flex-wrap items-center justify-center gap-2 pt-2">
          <span className="text-xs text-slate-500">Try asking:</span>
          {sampleQueries.map((q) => (
            <button
              key={q}
              onClick={() => {
                setQuery(q);
              }}
              className="text-xs px-2.5 py-1 rounded-full bg-slate-900 hover:bg-slate-800 text-slate-400 hover:text-slate-200 border border-slate-800 transition"
            >
              {q}
            </button>
          ))}
        </div>
      </div>

      {/* Error Message */}
      {error && (
        <div className="max-w-3xl mx-auto p-4 rounded-xl bg-rose-500/10 border border-rose-500/30 text-rose-300 text-sm">
          ⚠️ {error}
        </div>
      )}

      {/* Result Section */}
      {result && (
        <div className="max-w-4xl mx-auto space-y-6 animate-fadeIn">
          {/* Answer Card */}
          <div className="glass-panel rounded-2xl p-6 relative border-t-2 border-t-indigo-500">
            {result.cached && (
              <div className="absolute top-4 right-4 flex items-center gap-1.5 px-2.5 py-1 rounded-full bg-emerald-500/10 border border-emerald-500/30 text-emerald-400 text-xs font-medium">
                <span>⚡</span> RedisVL Semantic Cache Hit
              </div>
            )}

            <h3 className="text-lg font-bold text-white mb-3 flex items-center gap-2">
              <span>🤖</span> Synthesized Answer
            </h3>
            <div className="text-slate-200 leading-relaxed whitespace-pre-line text-base font-normal">
              {result.answer}
            </div>

            {/* Citations */}
            {result.citations && result.citations.length > 0 && (
              <div className="mt-5 pt-4 border-t border-slate-800">
                <span className="text-xs font-semibold text-slate-400 uppercase tracking-wider">
                  Verified Citations:
                </span>
                <div className="flex flex-wrap gap-2 mt-2">
                  {result.citations.map((c) => (
                    <span
                      key={c}
                      className="px-2.5 py-1 rounded-md bg-blue-950/60 border border-blue-800/60 text-blue-300 text-xs font-mono font-medium flex items-center gap-1"
                    >
                      📄 {c}
                    </span>
                  ))}
                </div>
              </div>
            )}
          </div>

          {/* Lineage & ACL Verification Drawer */}
          <div className="space-y-4">
            <h3 className="text-base font-bold text-white flex items-center gap-2">
              <span>🔍</span> Source Lineage & ACL Validation
              <span className="text-xs font-normal text-slate-400 font-mono">
                ({result.retrieved_chunks.length} chunks retrieved from Qdrant)
              </span>
            </h3>

            <div className="grid grid-cols-1 gap-4">
              {result.retrieved_chunks.map((chunk: RetrievedChunk, idx: number) => {
                const badgeColor =
                  chunk.source_type === "pdf"
                    ? "bg-rose-950/80 text-rose-300 border-rose-800/60"
                    : chunk.source_type === "excel"
                    ? "bg-emerald-950/80 text-emerald-300 border-emerald-800/60"
                    : chunk.source_type === "slack"
                    ? "bg-purple-950/80 text-purple-300 border-purple-800/60"
                    : "bg-sky-950/80 text-sky-300 border-sky-800/60";

                return (
                  <div key={idx} className="glass-panel rounded-xl p-4 card-glow transition-all">
                    <div className="flex flex-wrap items-center justify-between gap-2 mb-2">
                      <div className="flex items-center gap-2">
                        <span
                          className={`px-2 py-0.5 rounded text-[11px] font-bold uppercase tracking-wider border ${badgeColor}`}
                        >
                          {chunk.source_type}
                        </span>
                        <span className="text-sm font-semibold text-white">{chunk.filename}</span>
                      </div>
                      {chunk.rerank_score !== undefined && (
                        <span className="text-xs font-mono text-emerald-400 bg-emerald-950/50 px-2 py-0.5 rounded border border-emerald-800/40">
                          Rerank: {chunk.rerank_score.toFixed(4)}
                        </span>
                      )}
                    </div>

                    <div className="text-xs text-slate-300 bg-slate-950/80 p-3 rounded-lg border border-slate-800/60 font-mono whitespace-pre-wrap leading-relaxed max-h-48 overflow-y-auto">
                      {chunk.text}
                    </div>

                    <div className="mt-2.5 flex items-center gap-2 flex-wrap">
                      <span className="text-[11px] text-slate-500">Allowed Groups:</span>
                      {chunk.allowed_groups?.map((grp) => (
                        <span
                          key={grp}
                          className="px-1.5 py-0.5 rounded text-[10px] font-mono bg-slate-800 text-slate-300 border border-slate-700"
                        >
                          {grp}
                        </span>
                      ))}
                    </div>
                  </div>
                );
              })}
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
