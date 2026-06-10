/** Mirrors backend normalized chat blocks for the transport shell. */

export type StructuredOutput =
  | { type: "text"; role?: string; content: string }
  | { type: "system_status"; level?: string; message?: string; status?: Record<string, unknown> };

export function isStructuredOutput(x: unknown): x is StructuredOutput {
  return typeof x === "object" && x !== null && "type" in x;
}
