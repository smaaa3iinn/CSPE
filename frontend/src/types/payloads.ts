/** Mirrors backend normalized blocks (extend as Atlas grows). */

export type StructuredOutput =
  | { type: "text"; role?: string; content: string }
  | {
      type: "visual_board";
      panels: { title: string; query: string; urls: string[] }[];
    }
  | { type: "image_results"; images: { url: string; caption?: string }[] }
  | { type: "system_status"; level?: string; message?: string; status?: Record<string, unknown> };

export function isStructuredOutput(x: unknown): x is StructuredOutput {
  return typeof x === "object" && x !== null && "type" in x;
}
