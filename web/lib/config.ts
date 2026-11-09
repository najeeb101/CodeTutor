// Where the FastAPI server runs (`make api`). Server components call it directly; the browser
// goes through the /api rewrite in next.config.ts. Override with CODETUTOR_API_URL.
export const API_URL = process.env.CODETUTOR_API_URL ?? "http://127.0.0.1:8000";

// The read-only demo API (a simulated class, Deploy Step 2c): its own process, reached through
// the /demo-api rewrite. Override with CODETUTOR_DEMO_API_URL.
export const DEMO_API_URL = process.env.CODETUTOR_DEMO_API_URL ?? "http://127.0.0.1:8011";
