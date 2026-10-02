// A problem description is plain text, hard-wrapped at ~90 characters (problem.yaml):
// paragraphs, "- " list items (continued on indented lines), and indented code lines such
// as the "Examples:" block. This turns it into blocks, so the page can re-wrap paragraphs
// to the screen width but keep code lines as written. Inline `backticks` stay in the text.

export type Block =
  | { kind: "paragraph"; text: string }
  | { kind: "list"; items: string[] }
  | { kind: "code"; lines: string[] };

export function parseDescription(text: string): Block[] {
  const blocks: Block[] = [];
  let current: Block | null = null; // the block the next line may continue

  for (const line of text.split("\n")) {
    const trimmed = line.trim();
    if (trimmed === "") {
      current = null; // a blank line ends the block
    } else if (trimmed.startsWith("- ")) {
      const item = trimmed.slice(2);
      if (current?.kind === "list") current.items.push(item);
      else blocks.push((current = { kind: "list", items: [item] }));
    } else if (line.startsWith(" ") && current?.kind === "list") {
      current.items[current.items.length - 1] += ` ${trimmed}`; // a wrapped list item
    } else if (line.startsWith(" ")) {
      if (current?.kind === "code") current.lines.push(line);
      else blocks.push((current = { kind: "code", lines: [line] }));
    } else if (current?.kind === "paragraph") {
      current.text += ` ${trimmed}`; // a wrapped paragraph line
    } else {
      blocks.push((current = { kind: "paragraph", text: trimmed }));
    }
  }
  return blocks;
}
