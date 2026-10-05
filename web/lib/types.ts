// The API's JSON answers (docs/api.md), written by hand from the pydantic models in
// src/codetutor/api/schemas.py. They can drift from the Python side: keep them in sync.
// Values the student sees are shown with the *_repr fields (Python's repr): JSON.parse turns
// the float 32.0 into 32, so raw values are never displayed.

export type JsonValue = string | number | boolean | null | JsonValue[] | { [key: string]: JsonValue };

export type Difficulty = "easy" | "medium" | "hard";
export type CompareMode = "exact" | "unordered" | "float";
export type JobStatus = "queued" | "running" | "done" | "failed";
export type GradeStatus =
  | "accepted"
  | "wrong_answer"
  | "runtime_error"
  | "timeout"
  | "compile_error"
  | "crashed";
export type TestStatus = "passed" | "wrong_answer" | "runtime_error" | "timeout";

export interface User {
  id: number;
  name: string;
}

export interface ProblemSummary {
  id: string;
  title: string;
  module: number;
  module_name: string;
  order: number;
  difficulty: Difficulty;
}

export interface Example {
  id: string;
  input: JsonValue[];
  expected: JsonValue;
  compare: CompareMode;
  note: string | null;
  args_repr: string; // e.g. "[1, 2], 3"
  expected_repr: string; // e.g. "32.0", "'Fizz'", "None"
}

export interface Problem {
  id: string;
  version: number;
  title: string;
  module: number;
  module_name: string;
  order: number;
  difficulty: Difficulty;
  concepts: string[];
  function_name: string;
  description_en: string;
  description_ar: string | null;
  starter_code: string;
  time_limit_s: number;
  check_input_unchanged: boolean;
  examples: Example[];
}

export interface TestResult {
  test_id: string;
  hidden: boolean;
  status: TestStatus;
  error: string | null;
  revealed: boolean; // false for hidden tests: no input, expected or actual
  input: JsonValue[] | null;
  expected: JsonValue;
  actual: JsonValue;
  duration_ms: number;
  args_repr: string | null;
  expected_repr: string | null;
  actual_repr: string | null; // null when the test has an error
}

export interface GradeResult {
  problem_id: string;
  problem_version: number;
  status: GradeStatus;
  passed: number;
  total: number;
  reward: number;
  tests: TestResult[]; // empty for compile_error, crashed and a total timeout
  compile_error: string | null;
  error: string | null;
  stdout: string;
  duration_ms: number;
  grader_version: string;
}

export interface SubmissionCreated {
  id: number;
  job_status: JobStatus;
}

export interface SubmissionSummary {
  id: number;
  problem_id: string;
  problem_version: number;
  created_at: string; // ISO 8601 with time zone
  job_status: JobStatus;
  result_status: GradeStatus | null;
  passed: number | null;
  total: number | null;
  reward: number | null;
}

export interface Submission extends SubmissionSummary {
  code: string;
  finished_at: string | null;
  message: string | null; // set when job_status is "failed"
  result: GradeResult | null; // null until job_status is "done"
}

// "model": the tutor wrote it; "fallback": the tutor's hints were blocked or failed, so the
// teacher's hint of that level; "reference": level 3, the teacher's last hint.
export type HintSource = "model" | "fallback" | "reference";

export interface HintCreated {
  id: number;
  job_status: JobStatus;
}

export interface Hint {
  id: number;
  problem_id: string;
  problem_version: number;
  submission_id: number | null; // the graded submission it is about, or null (editor code)
  level: number; // 1-2: the tutor; 3: the teacher's last hint
  question: string | null;
  created_at: string;
  job_status: JobStatus;
  text: string | null; // null until job_status is "done"
  source: HintSource | null;
  rating: 1 | -1 | null;
  message: string | null; // set when job_status is "failed"
}
