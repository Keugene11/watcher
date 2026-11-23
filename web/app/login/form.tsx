"use client";
import { useState } from "react";
import { Eye } from "lucide-react";

export default function LoginForm() {
  const [pw, setPw] = useState("");
  const [err, setErr] = useState("");
  const [busy, setBusy] = useState(false);
  async function submit(e: React.FormEvent) {
    e.preventDefault();
    setBusy(true); setErr("");
    const r = await fetch("/api/login", { method: "POST", headers: { "content-type": "application/json" }, body: JSON.stringify({ password: pw }) });
    if (r.ok) location.href = "/";
    else { setErr((await r.json().catch(() => ({}))).error ?? "Wrong password"); setBusy(false); }
  }
  return (
    <div className="wrap login">
      <form className="card" onSubmit={submit}>
        <span className="brand"><Eye size={19} />watcher</span>
        <input type="password" autoFocus placeholder="Password" aria-label="Password" value={pw} onChange={(e) => setPw(e.target.value)} />
        <button className="primary" disabled={busy || !pw}>{busy ? "Checking…" : "Log in"}</button>
        {err && <div className="err" role="alert">{err}</div>}
      </form>
    </div>
  );
}
