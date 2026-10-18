import { useEffect, useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { getAuthConfig, login, signup } from "../api/client";

export default function Login() {
  const [mode, setMode] = useState("login");
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [err, setErr] = useState("");
  const [cfg, setCfg] = useState({});
  const nav = useNavigate();

  useEffect(() => { getAuthConfig().then(setCfg).catch(() => {}); }, []);

  const finish = (r) => {
    localStorage.setItem("token", r.token);
    localStorage.setItem("username", r.username);
    nav("/");
  };

  const submit = async (e) => {
    e.preventDefault();
    setErr("");
    try {
      finish(await (mode === "login" ? login : signup)({ username, password }));
    } catch (e2) {
      setErr(e2.message);
    }
  };

  const tryDemo = async () => {
    setErr("");
    try {
      finish(await login({ username: cfg.demo_username, password: cfg.demo_password }));
    } catch (e2) {
      setErr(e2.message);
    }
  };

  return (
    <div className="max-w-sm mx-auto mt-12">
      <div className="bg-white border border-gray-200 rounded-xl p-6">
        <h1 className="text-xl font-bold mb-4">{mode === "login" ? "Log in" : "Sign up"}</h1>
        <form onSubmit={submit} className="space-y-3">
          <input value={username} onChange={(e) => setUsername(e.target.value)} placeholder="Username"
            required minLength={3} className="w-full border rounded px-3 py-2 text-sm" />
          <input type="password" value={password} onChange={(e) => setPassword(e.target.value)}
            placeholder="Password (min 8 chars)" required minLength={8}
            className="w-full border rounded px-3 py-2 text-sm" />
          {err && <p className="text-sm text-red-600">{err}</p>}
          <button className="w-full bg-indigo-600 text-white py-2 rounded-lg text-sm font-medium hover:bg-indigo-700">
            {mode === "login" ? "Log in" : "Create account"}
          </button>
        </form>
        <button onClick={() => { setMode(mode === "login" ? "signup" : "login"); setErr(""); }}
          className="mt-3 text-xs text-indigo-600 underline">
          {mode === "login" ? "No account? Sign up" : "Have an account? Log in"}
        </button>

        {cfg.demo_enabled && (
          <div className="mt-5 pt-4 border-t border-gray-100">
            <button onClick={tryDemo}
              className="w-full border border-indigo-300 text-indigo-700 py-2 rounded-lg text-sm font-medium hover:bg-indigo-50">
              Try the demo (no signup)
            </button>
            <p className="text-[11px] text-gray-500 mt-1">
              Shared read-only account with a sample CIPP/E question bank. Take exams; uploads are disabled.
            </p>
          </div>
        )}
      </div>
      <p className="text-[11px] text-gray-500 mt-3 text-center">
        Don't reuse an important password. Questions are AI-generated and may be wrong; this is a study aid,
        not affiliated with IAPP or ISC2. <Link to="/about" className="underline">Privacy &amp; disclaimer</Link>
      </p>
    </div>
  );
}
