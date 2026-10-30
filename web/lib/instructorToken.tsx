"use client";

// The teacher's dev token (a shared secret, NOT real authentication), shared through a React
// context. It lives in sessionStorage, so it is gone when the tab closes (localStorage would
// keep a secret on the computer for good).
import { createContext, useCallback, useContext, useEffect, useState, type ReactNode } from "react";

import { ApiError, apiFetch } from "./api";

const STORAGE_KEY = "codetutor.instructorToken";

interface TokenState {
  token: string | null;
  ready: boolean; // false until sessionStorage was read
  setToken: (token: string | null) => void;
}

const TokenContext = createContext<TokenState | null>(null);

function readToken(): string | null {
  try {
    return window.sessionStorage.getItem(STORAGE_KEY);
  } catch {
    return null;
  }
}

function writeToken(token: string | null): void {
  try {
    if (token === null) window.sessionStorage.removeItem(STORAGE_KEY);
    else window.sessionStorage.setItem(STORAGE_KEY, token);
  } catch {
    // not remembered: the teacher types it again after a reload
  }
}

export function InstructorTokenProvider({ children }: { children: ReactNode }) {
  const [token, setTokenState] = useState<string | null>(null);
  const [ready, setReady] = useState(false);

  useEffect(() => {
    setTokenState(readToken());
    setReady(true);
  }, []);

  const setToken = useCallback((next: string | null) => {
    writeToken(next);
    setTokenState(next);
  }, []);

  return <TokenContext value={{ token, ready, setToken }}>{children}</TokenContext>;
}

export function useInstructorToken(): TokenState {
  const state = useContext(TokenContext);
  if (state === null) throw new Error("useInstructorToken must be used inside its provider");
  return state;
}

interface Loaded<T> {
  data: T | null;
  error: string | null;
  loading: boolean;
}

// One GET with the token. A wrong token (401/403) is forgotten, so the token box comes back.
export function useInstructorData<T>(path: string): Loaded<T> {
  const { token, ready, setToken } = useInstructorToken();
  const [state, setState] = useState<Loaded<T>>({ data: null, error: null, loading: true });

  useEffect(() => {
    if (!ready || token === null) return;
    let current = true; // ignore an answer that arrives after the token or path changed
    setState({ data: null, error: null, loading: true });
    apiFetch<T>(path, { instructorToken: token })
      .then((data) => current && setState({ data, error: null, loading: false }))
      .catch((caught: unknown) => {
        if (!current) return;
        if (caught instanceof ApiError && (caught.status === 401 || caught.status === 403)) {
          setToken(null);
        }
        const text = caught instanceof ApiError ? describe(caught) : "Could not load the data";
        setState({ data: null, error: text, loading: false });
      });
    return () => {
      current = false;
    };
  }, [path, token, ready, setToken]);

  return state;
}

function describe(error: ApiError): string {
  if (error.status === 401 || error.status === 403) return "Wrong teacher token.";
  if (error.status === 503) {
    return "The server has no teacher token (set INSTRUCTOR_TOKEN, 16+ characters, and restart the API).";
  }
  return error.detail;
}
