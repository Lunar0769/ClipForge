import { fireEvent, render, screen } from "@testing-library/react";
import { expect, it, vi } from "vitest";
import { MagneticButton } from "./MagneticButton";

it("keeps caller handlers and style under reduced motion", () => {
  const onPointerMove = vi.fn();
  render(
    <MagneticButton onPointerMove={onPointerMove} style={{ color: "rgb(1, 2, 3)" }}>
      Go
    </MagneticButton>,
  );
  const button = screen.getByRole("button", { name: "Go" });
  fireEvent.pointerMove(button, { clientX: 50, clientY: 50 });
  expect(onPointerMove).toHaveBeenCalledTimes(1);
  expect(button).toHaveStyle({ color: "rgb(1, 2, 3)" });
});
