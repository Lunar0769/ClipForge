import { render } from "@testing-library/react";
import { expect, it, vi } from "vitest";
import { BackgroundBoundary } from "./BackgroundBoundary";

function Boom(): never {
  throw new Error("webgl failed");
}

it("falls back to the static gradient when the background throws", () => {
  vi.spyOn(console, "error").mockImplementation(() => {});
  const { container } = render(
    <BackgroundBoundary>
      <Boom />
    </BackgroundBoundary>,
  );
  expect(container.querySelector('div[aria-hidden="true"]')).toBeInTheDocument();
  vi.restoreAllMocks();
});

it("renders children when nothing fails", () => {
  const { getByText } = render(<BackgroundBoundary><p>ok</p></BackgroundBoundary>);
  expect(getByText("ok")).toBeInTheDocument();
});
