"use client";

// The logged-in user (dev login: a name only, NOT secure), shared through a React context and
// remembered in localStorage. Every request that needs a user sends its id as X-User-Id.
import { createContext, useCallback, useContext, useEffect, useState, type ReactNode } from "react";

import { readStored, writeStored } from "./storage";
import type { User } from "./types";

const STORAGE_KEY = "codetutor.user";

interface UserState {
  user: User | null;
  ready: boolean; // false until localStorage was read (the server render knows no user)
  login: (user: User) => void;
  logout: () => void;
}

const UserContext = createContext<UserState | null>(null);

function parseUser(raw: string | null): User | null {
  try {
    const value: unknown = raw === null ? null : JSON.parse(raw);
    if (value && typeof value === "object" && "id" in value && "name" in value) {
      const { id, name } = value;
      if (typeof id === "number" && typeof name === "string") return { id, name };
    }
  } catch {
    // a broken stored value counts as "not logged in"
  }
  return null;
}

export function UserProvider({ children }: { children: ReactNode }) {
  const [user, setUser] = useState<User | null>(null);
  const [ready, setReady] = useState(false);

  // localStorage exists only in the browser, so it is read after the first render.
  useEffect(() => {
    setUser(parseUser(readStored(STORAGE_KEY)));
    setReady(true);
  }, []);

  const login = useCallback((next: User) => {
    writeStored(STORAGE_KEY, JSON.stringify(next));
    setUser(next);
  }, []);

  const logout = useCallback(() => {
    writeStored(STORAGE_KEY, null);
    setUser(null);
  }, []);

  return <UserContext value={{ user, ready, login, logout }}>{children}</UserContext>;
}

export function useUser(): UserState {
  const state = useContext(UserContext);
  if (state === null) throw new Error("useUser must be used inside <UserProvider>");
  return state;
}
