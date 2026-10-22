import { expect, it } from "vitest";
import { isNotice } from "./TranscriptStream";

it("treats warnings as notices and routine activity as log lines", () => {
  expect(isNotice("⚠️ 1 of 3 transcript parts couldn't be scored; showing the rest.")).toBe(true);
  expect(isNotice("No speech was detected in this video.")).toBe(true);
  expect(isNotice("Rendering clip #1 (42s) with hormozi subtitles: Title")).toBe(false);
  expect(isNotice("✅ SEO packs ready for 4 clips")).toBe(false);
});
