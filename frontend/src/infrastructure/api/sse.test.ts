import { describe, expect, it } from "vitest";
import { parseSseBlock } from "./sse";

describe("SSE parser", () => {
  it("parses id, event name, and multiline data", () => {
    expect(parseSseBlock("id: 42\nevent: progress\ndata: {\ndata: \"ok\":true}"))
      .toEqual({ id: "42", event: "progress", data: "{\n\"ok\":true}" });
  });

  it("ignores heartbeat comments", () => {
    expect(parseSseBlock(": keep-alive")).toBeNull();
  });
});
