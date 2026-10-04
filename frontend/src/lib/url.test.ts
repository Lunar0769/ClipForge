import { describe, expect, it } from "vitest";
import { normalizeSourceUrl } from "./url";

describe("normalizeSourceUrl", () => {
  it.each([
    ["https://www.youtube.com/watch?v=abc", "https://www.youtube.com/watch?v=abc"],
    ["youtube.com/watch?v=abc", "https://youtube.com/watch?v=abc"],
    ["  youtu.be/abc?t=30  ", "https://youtu.be/abc?t=30"],
    ["https://www.youtube.com/shorts/xyz", "https://www.youtube.com/shorts/xyz"],
    ["http://vimeo.com/123", "http://vimeo.com/123"],
  ])("accepts %s", (input, expected) => {
    expect(normalizeSourceUrl(input)).toBe(expected);
  });

  it.each(["", "   ", "hello", "javascript:alert(1)", "ftp://example.com/a.mp4", "https://"])(
    "rejects %s",
    (input) => {
      expect(normalizeSourceUrl(input)).toBeNull();
    },
  );
});
