// The editor summary sent with each submit (Week 5 Step 0, docs/api.md): how long the student
// worked and how much they typed or pasted since the page was opened or since the last submit.
// Times and counts only, never keystrokes. The server checks the same rules (EditorStats in
// src/codetutor/api/schemas.py), so a summary that breaks one would turn a submit into a 422:
// every number here is a whole number and stays inside the server's bounds.

import type { EditorStats } from "@/lib/types";

const MAX_MS = 30 * 24 * 3600 * 1000; // MAX_EDITOR_MS on the server
const MAX_COUNT = 10_000_000; // MAX_EDITOR_COUNT on the server

function bounded(value: number, max: number): number {
  return Math.min(max, Math.max(0, Math.round(value)));
}

// The parts of a Monaco content-change event the tracker needs.
export interface EditEvent {
  changes: readonly { text: string }[];
  isFlush: boolean; // a whole-model setValue: not the student's edit
}

export class EditorTracker {
  private windowStart: number;
  private firstEdit: number | null = null;
  private insertedChars = 0; // every inserted character, pastes included
  private pastedChars = 0;
  private pasteCount = 0;
  private largestPaste = 0;
  private edits = 0;
  private restoredDraft = false;
  private pendingReplace: string | null = null; // text our own code is about to put in

  constructor(private readonly now: () => number = () => performance.now()) {
    this.windowStart = now();
  }

  // Before the page itself replaces the code (a restored draft, "Reset"): the editor applies
  // it as a normal edit, so the next change that leaves exactly this text is not counted.
  expectReplace(text: string, restoredDraft = false): void {
    this.pendingReplace = text;
    if (restoredDraft) this.restoredDraft = true;
  }

  // The editor started with this text (no change event): a pending replace is used up.
  onMount(text: string): void {
    if (this.pendingReplace === text) this.pendingReplace = null;
  }

  // `textAfter`: the whole editor text after the change.
  onEdit(event: EditEvent, textAfter: string): void {
    if (event.isFlush) return;
    if (this.pendingReplace !== null && textAfter === this.pendingReplace) {
      this.pendingReplace = null;
      return;
    }
    this.firstEdit ??= this.now();
    this.edits += 1;
    for (const change of event.changes) this.insertedChars += change.text.length;
  }

  // A paste of `chars` characters (also reported to onEdit as an edit).
  onPaste(chars: number): void {
    if (chars <= 0) return;
    this.pastedChars += chars;
    this.pasteCount += 1;
    this.largestPaste = Math.max(this.largestPaste, chars);
  }

  summary(): EditorStats {
    const at = this.now();
    const sinceOpen = bounded(at - this.windowStart, MAX_MS);
    const active = this.firstEdit === null ? 0 : bounded(at - this.firstEdit, MAX_MS);
    const pasted = bounded(this.pastedChars, MAX_COUNT);
    return {
      since_open_ms: sinceOpen,
      active_ms: Math.min(sinceOpen, active),
      typed_chars: bounded(this.insertedChars - this.pastedChars, MAX_COUNT),
      pasted_chars: pasted,
      paste_count: pasted === 0 ? 0 : bounded(this.pasteCount, MAX_COUNT),
      largest_paste_chars: Math.min(pasted, bounded(this.largestPaste, MAX_COUNT)),
      edit_count: bounded(this.edits, MAX_COUNT),
      restored_draft: this.restoredDraft,
    };
  }

  // After a submit was accepted: the next summary covers only the work after it.
  reset(): void {
    this.windowStart = this.now();
    this.firstEdit = null;
    this.insertedChars = 0;
    this.pastedChars = 0;
    this.pasteCount = 0;
    this.largestPaste = 0;
    this.edits = 0;
    this.restoredDraft = false;
  }
}
