import type { Metadata } from "next";
import "./globals.css";
import Link from "next/link";

export const metadata: Metadata = {
  title: "AskTheCompany — Zero-Trust Enterprise RAG",
  description: "Kubernetes-Native, ACL-Aware Enterprise Retrieval-Augmented Generation Platform",
};

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html lang="en" className="dark">
      <body className="min-h-screen flex flex-col bg-[#0b0f19] text-slate-100">
        <header className="sticky top-0 z-50 glass-panel border-b border-slate-800/80 px-6 py-3.5">
          <div className="max-w-7xl mx-auto flex items-center justify-between">
            <Link href="/" className="flex items-center space-x-3 group">
              <div className="w-9 h-9 rounded-xl bg-gradient-to-tr from-blue-600 to-indigo-500 flex items-center justify-center shadow-lg shadow-blue-500/20 group-hover:scale-105 transition-transform">
                <span className="text-xl">🛡️</span>
              </div>
              <div>
                <span className="text-lg font-bold tracking-tight text-white flex items-center gap-2">
                  AskTheCompany
                  <span className="text-[10px] px-2 py-0.5 rounded-full bg-blue-500/10 text-blue-400 border border-blue-500/20 font-mono">
                    ENTERPRISE v2.0
                  </span>
                </span>
                <p className="text-xs text-slate-400">Zero-Trust ACL · PII Redacted · Hybrid RAG</p>
              </div>
            </Link>

            <nav className="flex items-center space-x-6">
              <Link
                href="/"
                className="text-sm font-medium text-slate-300 hover:text-white transition-colors"
              >
                Search & Query
              </Link>
              <Link
                href="/admin"
                className="text-sm font-medium text-slate-300 hover:text-white transition-colors"
              >
                Admin & DLQ
              </Link>
              <Link
                href="/login"
                className="text-xs font-semibold px-4 py-2 rounded-lg bg-blue-600 hover:bg-blue-500 text-white transition-all shadow-md shadow-blue-600/20"
              >
                Switch Role / Login
              </Link>
            </nav>
          </div>
        </header>

        <main className="flex-1 max-w-7xl w-full mx-auto p-6">{children}</main>

        <footer className="glass-panel border-t border-slate-800/80 py-4 px-6 text-center text-xs text-slate-500">
          AskTheCompany Enterprise · 100% Open Source Architecture · Apache/MIT Licensed
        </footer>
      </body>
    </html>
  );
}
