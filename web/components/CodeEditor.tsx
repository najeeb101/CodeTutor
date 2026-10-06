"use client";

import Editor, { loader, type OnMount } from "@monaco-editor/react";
import { useEffect, useState } from "react";

import type { EditorTracker } from "@/lib/editorStats";

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
  tracker: EditorTracker; // counts typed and pasted characters (lib/editorStats.ts)
  label: string;
}

export function CodeEditor({ value, onChange, tracker, label }: CodeEditorProps) {
  // Monaco calls this once, when the editor exists. Its listeners end with the editor.
  const onMount: OnMount = (editor) => {
    tracker.onMount(editor.getValue());
    editor.onDidChangeModelContent((event) => tracker.onEdit(event, editor.getValue()));
    editor.onDidPaste((event) => {
      const model = editor.getModel();
      if (model) tracker.onPaste(model.getValueLengthInRange(event.range));
    });
  };

  const dark = usePrefersDark();
  return (
    <div className="editor" aria-label={label}>
      <Editor
        height="420px"
        language="python"
        theme={dark ? "vs-dark" : "light"}
        value={value}
        onChange={(code) => onChange(code ?? "")}
        onMount={onMount}
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
