// A share (0..1) as a small bar plus the percentage. null = nothing to show yet.
export function Bar({ share }: { share: number | null }) {
  if (share === null) return <span className="muted">–</span>;
  const percent = Math.round(share * 100);
  return (
    <span className="bar" title={`${percent}%`}>
      <span className="bar-fill" style={{ width: `${percent}%` }} />
      <span className="bar-text">{percent}%</span>
    </span>
  );
}
