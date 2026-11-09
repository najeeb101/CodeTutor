"use client";

// The logged-in user, shared through a React context. The session lives in an HttpOnly cookie
// (Deploy Step 2a): the browser sends it with every /api request, but this page can't read it,
// so on load we ask the server who we are (GET /api/me). Nothing about the user is stored here.
import { createContext, useCallback, useContext, useEffect, useState, type ReactNode } from "react";

import { ApiError, apiFetch } from "./api";
import { writeStored } from "./storage";
import type { User } from "./types";

const OLD_STORAGE_KEY = "codetutor.user"; // the dev login kept {id, name} here before 2b

interface UserState {
  user: User | null;
  ready: boolean; // false until the server said who we are (the server render knows no user)
  startGuest: () => Promise<void>; // throws ApiError (e.g. 429 / 503) for the caller to show
  logout: () => Promise<void>;
  forget: () => void; // the session ended on the server (a 401): only clear this page's state
}

const UserContext = createContext<UserState | null>(null);

export function UserProvider({ children }: { children: ReactNode }) {
  const [user, setUser] = useState<User | null>(null);
  const [ready, setReady] = useState(false);

  useEffect(() => {
    writeStored(OLD_STORAGE_KEY, null);
    let active = true;
    apiFetch<User>("/api/me")
      .then((me) => active && setUser(me))
      .catch((error: unknown) => {
        // 401 = no session; anything else (API down) also shows the guest button
        if (!(error instanceof ApiError)) throw error;
      })
      .finally(() => active && setReady(true));
    return () => {
      active = false;
    };
  }, []);

  const startGuest = useCallback(async () => {
    setUser(await apiFetch<User>("/api/guest", { method: "POST" }));
  }, []);

  const logout = useCallback(async () => {
    try {
      await apiFetch("/api/logout", { method: "POST" });
    } finally {
      setUser(null); // even if the request failed, this page shows "logged out"
    }
  }, []);

  const forget = useCallback(() => setUser(null), []);

  return <UserContext value={{ user, ready, startGuest, logout, forget }}>{children}</UserContext>;
}

export function useUser(): UserState {
  const state = useContext(UserContext);
  if (state === null) throw new Error("useUser must be used inside <UserProvider>");
  return state;
}
