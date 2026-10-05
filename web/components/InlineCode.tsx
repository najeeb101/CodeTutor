// Text with `backticks` shown as code (problem descriptions and hints).
export function InlineCode({ text }: { text: string }) {
  const parts = text.split("`");
  return <>{parts.map((part, index) => (index % 2 === 1 ? <code key={index}>{part}</code> : part))}</>;
}
