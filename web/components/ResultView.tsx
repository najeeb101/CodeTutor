// One submission's result. Hidden tests never carry details (the API doesn't send any): the
// student sees only *that* a hidden test passed or failed.
import type { GradeStatus, Submission, TestResult } from "@/lib/types";

const STATUS_TEXT: Record<GradeStatus, string> = {
  accepted: "Accepted",
  wrong_answer: "Wrong answer",
  runtime_error: "Runtime error",
  timeout: "Time limit exceeded",
  compile_error: "Your code could not be loaded",
  crashed: "Crashed",
};

function details(test: TestResult): string {
  if (test.status === "passed") return "";
  if (test.error) return test.error;
  if (test.revealed) return `expected ${test.expected_repr}, got ${test.actual_repr}`;
  return "";
}

function TestRow({ test, functionName }: { test: TestResult; functionName: string }) {
  const passed = test.status === "passed";
  return (
    <tr className={passed ? "ok" : "bad"}>
      <td>{test.revealed ? <code>{`${functionName}(${test.args_repr})`}</code> : "hidden test"}</td>
      <td>{passed ? "✓ passed" : `✗ ${test.status.replace("_", " ")}`}</td>
      <td>{details(test)}</td>
    </tr>
  );
}

export function ResultView({ submission, functionName }: { submission: Submission; functionName: string }) {
  if (submission.job_status === "failed") {
    return (
      <div className="result bad" role="status">
        {submission.message}
      </div>
    );
  }
  const result = submission.result;
  if (result === null) {
    return (
      <div className="result pending" role="status">
        Grading… ({submission.job_status})
      </div>
    );
  }

  const hiddenFailed = result.tests.some((test) => test.hidden && test.status !== "passed");
  return (
    <div className={`result ${result.status === "accepted" ? "ok" : "bad"}`} role="status">
      <h3>
        {STATUS_TEXT[result.status]}: {result.passed} of {result.total} tests passed
      </h3>
      {result.compile_error && <pre className="output">{result.compile_error}</pre>}
      {result.error && <p>{result.error}</p>}
      {result.tests.length > 0 && (
        <table className="tests">
          <thead>
            <tr>
              <th>Test</th>
              <th>Result</th>
              <th>Details</th>
            </tr>
          </thead>
          <tbody>
            {result.tests.map((test) => (
              <TestRow key={test.test_id} test={test} functionName={functionName} />
            ))}
          </tbody>
        </table>
      )}
      {hiddenFailed && (
        <p className="muted">
          A hidden test failed. Hidden tests check cases that are not in the examples, like empty
          input or edge values. Read the problem text again: which case does your code miss?
        </p>
      )}
      {result.stdout && (
        <details>
          <summary>Printed output</summary>
          <pre className="output">{result.stdout}</pre>
        </details>
      )}
    </div>
  );
}
