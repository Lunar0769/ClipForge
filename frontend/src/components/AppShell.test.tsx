import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router";
import { expect, it } from "vitest";
import { AppShell } from "./AppShell";

it("renders the brand, children and toggles the theme", async () => {
  document.documentElement.dataset.theme = "dark";
  render(
    <MemoryRouter>
      <AppShell><p>child content</p></AppShell>
    </MemoryRouter>,
  );
  expect(screen.getByRole("link", { name: /clipforge home/i })).toBeInTheDocument();
  expect(screen.getByText("child content")).toBeInTheDocument();
  await userEvent.click(screen.getByRole("button", { name: /switch to light theme/i }));
  expect(document.documentElement.dataset.theme).toBe("light");
  await userEvent.click(screen.getByRole("button", { name: /switch to dark theme/i }));
  expect(document.documentElement.dataset.theme).toBe("dark");
});
