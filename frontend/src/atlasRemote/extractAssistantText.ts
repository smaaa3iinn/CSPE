import type { StructuredOutput } from "../types/payloads";

/** Pull assistant-visible text from normalized chat blocks. */
export function extractAssistantText(outputs: StructuredOutput[]): string {
  const parts: string[] = [];
  for (const block of outputs) {
    if (block.type !== "text") continue;
    if (block.role && block.role !== "assistant") continue;
    const content = (block.content || "").trim();
    if (content) parts.push(content);
  }
  return parts.join("\n\n").trim();
}
