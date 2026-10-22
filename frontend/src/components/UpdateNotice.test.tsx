import { render, screen } from "@testing-library/react";
import { afterEach, expect, it, vi } from "vitest";
import { api } from "../lib/api";
import { UpdateNotice } from "./UpdateNotice";

afterEach(() => vi.restoreAllMocks());

it("shows the newer version with a link to releases", async () => {
  vi.spyOn(api, "updateStatus").mockResolvedValue({
    current: "1.0.0", latest: "1.1.0", update_available: true, url: "https://github.com/Lunar0769/ClipForge/releases",
  });
  render(<UpdateNotice />);
  const link = await screen.findByRole("link", { name: /v1.1.0 available/ });
  expect(link).toHaveAttribute("href", "https://github.com/Lunar0769/ClipForge/releases");
});

it("stays hidden when up to date or offline", async () => {
  vi.spyOn(api, "updateStatus").mockRejectedValue(new Error("offline"));
  const { container } = render(<UpdateNotice />);
  await new Promise((r) => setTimeout(r, 20));
  expect(container).toBeEmptyDOMElement();
});
