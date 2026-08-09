"use client";

import { useState } from "react";
import { loginUser, setStoredSession, clearStoredSession, API_URL } from "@/lib/api";
import { useRouter } from "next/navigation";

export default function LoginPage() {
  const router = useRouter();
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [success, setSuccess] = useState<string | null>(null);

  const demoRoles = [
    {
      title: "Guest User",
      desc: "Simulates unprivileged public access. Cannot view HR payroll or management plans.",
      user: "guest",
      pass: "guest123",
      groups: ["Public"],
      badge: "bg-slate-800 text-slate-300",
    },
    {
      title: "HR Specialist",
      desc: "Simulates HR personnel. Can view employee salary spreadsheets and compensation policies.",
      user: "hr_staff",
      pass: "hr123",
      groups: ["HR", "Public"],
      badge: "bg-emerald-950 text-emerald-300 border border-emerald-800",
    },
    {
      title: "Engineering Manager",
      desc: "Simulates management role. Can query strategic documents and team Slack archives.",
      user: "manager",
      pass: "manager123",
      groups: ["Management", "Public"],
      badge: "bg-purple-950 text-purple-300 border border-purple-800",
    },
    {
      title: "System Administrator",
      desc: "Full administrative access. Can view audit logs, trigger seed ingestion, and manage DLQ.",
      user: "admin",
      pass: "admin123",
      groups: ["HR", "Management", "Engineering", "admin", "Public"],
      badge: "bg-blue-950 text-blue-300 border border-blue-800",
    },
  ];

  const handleCustomLogin = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!username || !password) return;

    setLoading(true);
    setError(null);
    try {
      const data = await loginUser(username, password);
      setStoredSession(data.access_token, username, data.groups || ["Public"]);
      setSuccess(`Logged in as ${username}`);
      setTimeout(() => router.push("/"), 800);
    } catch (err: any) {
      setError(err.message || "Authentication failed");
    } finally {
      setLoading(false);
    }
  };

  const handleQuickRole = async (role: typeof demoRoles[0]) => {
    setLoading(true);
    setError(null);
    try {
      const data = await loginUser(role.user, role.pass);
      setStoredSession(data.access_token, role.user, data.groups || role.groups);
      setSuccess(`Switched to role: ${role.title} (${role.user})`);
      setTimeout(() => router.push("/"), 700);
    } catch (err: any) {
      setError(err.message || "Failed to switch role");
    } finally {
      setLoading(false);
    }
  };

  const handleLogout = () => {
    clearStoredSession();
    setSuccess("Logged out successfully");
  };

  return (
    <div className="max-w-4xl mx-auto space-y-8 py-4">
      <div className="text-center space-y-2">
        <h1 className="text-3xl font-extrabold text-white">Identity & Access Management</h1>
        <p className="text-slate-400 text-sm">
          Simulate enterprise roles to verify payload-level ACL enforcement, or connect via OIDC SSO.
        </p>
      </div>

      {error && (
        <div className="p-4 rounded-xl bg-rose-500/10 border border-rose-500/30 text-rose-300 text-sm">
          ⚠️ {error}
        </div>
      )}

      {success && (
        <div className="p-4 rounded-xl bg-emerald-500/10 border border-emerald-500/30 text-emerald-300 text-sm">
          ✅ {success}
        </div>
      )}

      {/* Quick Role Switcher Grid */}
      <div>
        <h2 className="text-sm font-semibold text-slate-300 uppercase tracking-wider mb-4">
          ⚡ 1-Click Role Simulation (ACL Verification)
        </h2>
        <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
          {demoRoles.map((role) => (
            <div
              key={role.user}
              className="glass-panel rounded-2xl p-5 flex flex-col justify-between space-y-4 card-glow transition border border-slate-800"
            >
              <div>
                <div className="flex items-center justify-between gap-2 mb-1.5">
                  <h3 className="font-bold text-white text-base">{role.title}</h3>
                  <span className={`px-2 py-0.5 rounded text-[11px] font-mono font-medium ${role.badge}`}>
                    {role.user}
                  </span>
                </div>
                <p className="text-xs text-slate-400 leading-relaxed">{role.desc}</p>
                <div className="mt-3 flex items-center gap-1.5 flex-wrap">
                  <span className="text-[11px] text-slate-500">Groups:</span>
                  {role.groups.map((g) => (
                    <span
                      key={g}
                      className="px-1.5 py-0.5 rounded text-[10px] font-mono bg-slate-800 text-slate-300 border border-slate-700"
                    >
                      {g}
                    </span>
                  ))}
                </div>
              </div>

              <button
                onClick={() => handleQuickRole(role)}
                disabled={loading}
                className="w-full py-2 px-4 rounded-xl bg-slate-800 hover:bg-blue-600 text-slate-200 hover:text-white font-medium text-xs transition duration-200 border border-slate-700 hover:border-blue-500 disabled:opacity-50"
              >
                Log In as {role.title} →
              </button>
            </div>
          ))}
        </div>
      </div>

      {/* Direct Login Form & OIDC SSO */}
      <div className="grid grid-cols-1 md:grid-cols-2 gap-6 pt-4 border-t border-slate-800">
        {/* Custom Credentials Form */}
        <div className="glass-panel rounded-2xl p-6 space-y-4">
          <h2 className="text-base font-bold text-white">Direct Local Authentication</h2>
          <form onSubmit={handleCustomLogin} className="space-y-3">
            <div>
              <label className="block text-xs text-slate-400 mb-1">Username</label>
              <input
                type="text"
                value={username}
                onChange={(e) => setUsername(e.target.value)}
                className="w-full px-3.5 py-2.5 rounded-xl bg-slate-950 border border-slate-700 text-white text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
                placeholder="e.g., admin"
              />
            </div>
            <div>
              <label className="block text-xs text-slate-400 mb-1">Password</label>
              <input
                type="password"
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                className="w-full px-3.5 py-2.5 rounded-xl bg-slate-950 border border-slate-700 text-white text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
                placeholder="••••••••"
              />
            </div>
            <button
              type="submit"
              disabled={loading}
              className="w-full py-2.5 rounded-xl bg-blue-600 hover:bg-blue-500 text-white font-medium text-sm transition shadow-md shadow-blue-600/20 disabled:opacity-50"
            >
              Sign In
            </button>
          </form>
        </div>

        {/* Enterprise OIDC / Keycloak SSO */}
        <div className="glass-panel rounded-2xl p-6 flex flex-col justify-between space-y-4">
          <div>
            <h2 className="text-base font-bold text-white flex items-center gap-2">
              <span>🏢</span> Enterprise SSO (OIDC)
            </h2>
            <p className="text-xs text-slate-400 mt-2 leading-relaxed">
              Connect to your organization's Identity Provider (Keycloak, Okta, Ping, or Azure Active Directory) via standard OpenID Connect protocols.
            </p>
            <div className="mt-4 p-3 rounded-xl bg-slate-950 border border-slate-800 text-[11px] text-slate-400 font-mono space-y-1">
              <div>AUTH_MODE: {process.env.NEXT_PUBLIC_AUTH_MODE || "local"}</div>
              <div>SSO Endpoint: Keycloak /protocol/openid-connect/auth</div>
            </div>
          </div>

          <div className="space-y-2">
            <button
              onClick={() => {
                alert("OIDC SSO redirect placeholder. Configure OIDC_ISSUER_URL in backend .env to connect live Keycloak instance.");
              }}
              className="w-full py-2.5 rounded-xl bg-indigo-600 hover:bg-indigo-500 text-white font-medium text-xs transition shadow-md shadow-indigo-600/20"
            >
              Log in with Keycloak / Okta SSO →
            </button>
            <button
              onClick={handleLogout}
              className="w-full py-2 rounded-xl bg-slate-900 hover:bg-rose-950/60 text-slate-400 hover:text-rose-300 font-medium text-xs transition border border-slate-800"
            >
              Clear Current Session / Logout
            </button>
          </div>
        </div>
      </div>
    </div>
  );
}
