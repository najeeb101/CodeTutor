"use client";

import { useState } from "react";

import { ApiError } from "@/lib/api";
import { useUser } from "@/lib/user";

export function LoginBox() {
  const { user, ready, startGuest, logout } = useUser();
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  if (!ready) return null; // don't flash the button for a visitor who already has a session

  async function start() {
    setBusy(true);
    setError(null);
    try {
      await startGuest();
    } catch (caught) {
      setError(caught instanceof ApiError ? caught.detail : "Could not start a session");
    } finally {
      setBusy(false);
    }
  }

  if (user) {
    return (
      <div className="login">
        <span>
          Logged in as <strong>{user.name}</strong>
        </span>
        <button type="button" onClick={() => void logout()}>
          Log out
        </button>
      </div>
    );
  }

  return (
    <div className="login">
      <button type="button" onClick={() => void start()} disabled={busy}>
        Start as a guest
      </button>
      <span className="muted">No sign-up. Your work stays with this browser.</span>
      {error && (
        <span className="error" role="alert">
          {error}
        </span>
      )}
    </div>
  );
}
