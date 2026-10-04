import { describe, expect, it } from "vitest";
import { makeProject } from "../test/fixtures";
import { fileExtension, formatDuration, formatRelative, formatTimestamp, projectTitle } from "./format";

describe("format", () => {
  it("formats durations", () => {
    expect(formatDuration(5)).toBe("0:05");
    expect(formatDuration(725)).toBe("12:05");
    expect(formatDuration(3723)).toBe("1:02:03");
  });

  it("formats transcript timestamps", () => {
    expect(formatTimestamp(0)).toBe("0:00");
    expect(formatTimestamp(61.9)).toBe("1:01");
  });

  it("formats relative times", () => {
    const now = Date.parse("2026-10-03T12:00:00Z");
    expect(formatRelative("2026-10-03T11:59:40+00:00", now)).toBe("just now");
    expect(formatRelative("2026-10-03T11:55:00+00:00", now)).toBe("5 min ago");
    expect(formatRelative("2026-10-03T09:00:00+00:00", now)).toBe("3 h ago");
    expect(formatRelative("2026-09-01T09:00:00+00:00", now)).toMatch(/2026|Sep/);
  });

  it("picks the best project title", () => {
    expect(projectTitle(makeProject({ title: "My Talk" }))).toBe("My Talk");
    expect(projectTitle(makeProject({ title: null, source_type: "upload", original_filename: "a b.mp4" }))).toBe("a b.mp4");
    expect(projectTitle(makeProject({ title: null, source_url: "https://youtu.be/abc" }))).toBe("youtu.be/abc");
  });

  it("extracts lowercase extensions", () => {
    expect(fileExtension("My Clip.MP4")).toBe(".mp4");
    expect(fileExtension("noext")).toBe("");
  });
});
