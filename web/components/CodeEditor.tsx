"use client";

import Editor, { loader } from "@monaco-editor/react";
import { useEffect, useState } from "react";

// Load Monaco from our own server (public/monaco, copied by scripts/copy-monaco.mjs at
// npm install), not from the default CDN (cdn.jsdelivr.net).
loader.config({ paths: { vs: "/monaco/vs" } });

function usePrefersDark(): boolean {
  const [dark, setDark] = useState(false);
  useEffect(() => {
    const query = window.matchMedia("(prefers-color-scheme: dark)");
    setDark(query.matches);
    const onChange = (event: MediaQueryListEvent) => setDark(event.matches);
    query.addEventListener("change", onChange);
    return () => query.removeEventListener("change", onChange);
  }, []);
  return dark;
}

interface CodeEditorProps {
  value: string;
  onChange: (code: string) => void;
  label: string;
}

export function CodeEditor({ value, onChange, label }: CodeEditorProps) {
  const dark = usePrefersDark();
  return (
    <div className="editor" aria-label={label}>
      <Editor
        height="420px"
        language="python"
        theme={dark ? "vs-dark" : "light"}
        value={value}
        onChange={(code) => onChange(code ?? "")}
        loading="Loading the editor…"
        options={{
          ariaLabel: label,
          fontSize: 14,
          tabSize: 4, // Python style (PEP 8)
          insertSpaces: true,
          minimap: { enabled: false },
          scrollBeyondLastLine: false,
          automaticLayout: true, // resize with the page
        }}
      />
    </div>
  );
}
