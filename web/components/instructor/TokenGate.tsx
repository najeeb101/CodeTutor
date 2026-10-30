"use client";

import { useState, type FormEvent, type ReactNode } from "react";

import { useInstructorToken } from "@/lib/instructorToken";

// Shows the children only when a teacher token is set; otherwise a box to enter it.
// The token is checked by the first request, not here (a wrong one sends the box back).
export function TokenGate({ children }: { children: ReactNode }) {
  const { token, ready, setToken } = useInstructorToken();
  const [text, setText] = useState("");

  if (!ready) return null;

  if (token !== null) {
    return (
      <>
        <div className="login">
          <span>Teacher view</span>
          <button type="button" onClick={() => setToken(null)}>
            Forget token
          </button>
        </div>
        {children}
      </>
    );
  }

  function submit(event: FormEvent) {
    event.preventDefault();
    if (text.trim() !== "") setToken(text.trim());
  }

  return (
    <form className="login" onSubmit={submit}>
      <label>
        Teacher token{" "}
        <input
          type="password"
          value={text}
          onChange={(event) => setText(event.target.value)}
          required
          autoComplete="off"
        />
      </label>
      <button type="submit">Open dashboard</button>
      <span className="muted" title="One shared secret from the INSTRUCTOR_TOKEN setting of the API.">
        dev token, not real login
      </span>
    </form>
  );
}
