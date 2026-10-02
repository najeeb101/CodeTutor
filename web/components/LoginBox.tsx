"use client";

import { useState, type FormEvent } from "react";

import { ApiError, apiFetch } from "@/lib/api";
import type { User } from "@/lib/types";
import { useUser } from "@/lib/user";

export function LoginBox() {
  const { user, ready, login, logout } = useUser();
  const [name, setName] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  if (!ready) return null; // don't flash the form for a user who is already logged in

  if (user) {
    return (
      <div className="login">
        <span>
          Logged in as <strong>{user.name}</strong>
        </span>
        <button type="button" onClick={logout}>
          Log out
        </button>
      </div>
    );
  }

  async function submit(event: FormEvent) {
    event.preventDefault();
    setBusy(true);
    setError(null);
    try {
      login(await apiFetch<User>("/api/login", { method: "POST", body: { name } }));
      setName("");
    } catch (caught) {
      setError(caught instanceof ApiError ? caught.detail : "Login failed");
    } finally {
      setBusy(false);
    }
  }

  return (
    <form className="login" onSubmit={submit}>
      <label>
        Name{" "}
        <input
          value={name}
          onChange={(event) => setName(event.target.value)}
          maxLength={40}
          required
          autoComplete="username"
        />
      </label>
      <button type="submit" disabled={busy}>
        Log in
      </button>
      <span className="muted" title="Anyone can use any name. Real login comes before hosting.">
        dev login, not secure
      </span>
      {error && (
        <span className="error" role="alert">
          {error}
        </span>
      )}
    </form>
  );
}
