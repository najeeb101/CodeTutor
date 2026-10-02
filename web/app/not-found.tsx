import Link from "next/link";

export default function NotFound() {
  return (
    <div className="error-page">
      <h1>Not found</h1>
      <p>There is no such problem (or it was retired).</p>
      <Link href="/">Back to the problem list</Link>
    </div>
  );
}
