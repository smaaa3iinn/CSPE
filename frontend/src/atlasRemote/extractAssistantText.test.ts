import { describe, expect, it } from "vitest";
import { extractAssistantText } from "./extractAssistantText";

describe("extractAssistantText", () => {
  it("joins assistant text blocks", () => {
    const text = extractAssistantText([
      { type: "text", role: "user", content: "ignored" },
      { type: "text", role: "assistant", content: "Done. Metro layer active." },
      { type: "system_status", level: "info", message: "ok" },
    ]);
    expect(text).toBe("Done. Metro layer active.");
  });

  it("includes blocks without role as assistant", () => {
    const text = extractAssistantText([{ type: "text", content: "Complete." }]);
    expect(text).toBe("Complete.");
  });
});
