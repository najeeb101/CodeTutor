import Link from "next/link";
import { notFound } from "next/navigation";

import { InlineCode } from "@/components/InlineCode";
import { Workspace } from "@/components/Workspace";
import { ApiError, apiFetch } from "@/lib/api";
import { parseDescription } from "@/lib/description";
import type { CompareMode, Problem } from "@/lib/types";

export const dynamic = "force-dynamic";

// The same notes the eval prompt gives models (src/codetutor/evals/prompt.py).
const COMPARE_NOTE: Record<CompareMode, string | null> = {
  exact: null,
  float: "floats are compared with a small tolerance",
  unordered: "any order",
};

// Code lines lose the indentation they all share (the description indents its examples).
function dedent(lines: string[]): string {
  const indent = Math.min(...lines.map((line) => line.length - line.trimStart().length));
  return lines.map((line) => line.slice(indent)).join("\n");
}

// The problem text: paragraphs re-wrap to the screen, code lines stay as written.
function Description({ text, lang }: { text: string; lang?: "ar" }) {
  return (
    <div className="description" lang={lang} dir={lang === "ar" ? "rtl" : undefined}>
      {parseDescription(text).map((block, index) => {
        if (block.kind === "paragraph") {
          return (
            <p key={index}>
              <InlineCode text={block.text} />
            </p>
          );
        }
        if (block.kind === "list") {
          return (
            <ul key={index}>
              {block.items.map((item, itemIndex) => (
                <li key={itemIndex}>
                  <InlineCode text={item} />
                </li>
              ))}
            </ul>
          );
        }
        return (
          <pre key={index} className="output">
            {dedent(block.lines)}
          </pre>
        );
      })}
    </div>
  );
}

async function loadProblem(id: string): Promise<Problem> {
  try {
    return await apiFetch<Problem>(`/api/problems/${encodeURIComponent(id)}`);
  } catch (error) {
    if (error instanceof ApiError && error.status === 404) notFound();
    throw error;
  }
}

export default async function ProblemPage({ params }: { params: Promise<{ id: string }> }) {
  const problem = await loadProblem((await params).id);
  return (
    <div className="problem-page">
      <section className="problem-text">
        <p className="muted">
          <Link href="/">Problems</Link> / Module {problem.module}: {problem.module_name}
        </p>
        <h1>
          {problem.title} <span className={`badge ${problem.difficulty}`}>{problem.difficulty}</span>
        </h1>
        <Description text={problem.description_en} />
        {problem.description_ar && <Description text={problem.description_ar} lang="ar" />}

        <h2>Visible tests</h2>
        <ul className="examples">
          {problem.examples.map((example) => {
            const note = COMPARE_NOTE[example.compare];
            return (
              <li key={example.id}>
                <code>
                  {problem.function_name}({example.args_repr})
                </code>{" "}
                → <code>{example.expected_repr}</code>
                {note && <span className="muted"> ({note})</span>}
              </li>
            );
          })}
        </ul>
        <p className="muted">
          Your code must pass these and some hidden tests (cases not shown here). Time limit:{" "}
          {problem.time_limit_s} s per test.
          {problem.check_input_unchanged && " Your function must not change its input."}
        </p>
      </section>
      <Workspace problem={problem} />
    </div>
  );
}
