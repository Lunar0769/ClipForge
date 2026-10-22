import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, expect, it, vi } from "vitest";
import { api } from "../../lib/api";
import { formatBytes } from "../../lib/format";
import { makeJob, makeProject } from "../../test/fixtures";
import { renderWithProviders } from "../../test/utils";
import { RecentProjects } from "./RecentProjects";

vi.mock("../../lib/api", async (importOriginal) => {
  const actual = await importOriginal<typeof import("../../lib/api")>();
  return { ...actual, api: { ...actual.api, listProjects: vi.fn(), deleteProject: vi.fn() } };
});

const projects = [
  makeProject({ id: "p1", title: "Big talk", video_id: "v1", storage_bytes: 524_288_000, project_bytes: 104_857_600,
    cache_bytes: 419_430_400, freeable_bytes: 524_288_000, latest_job: makeJob({ status: "succeeded" }) }),
  makeProject({ id: "p2", title: "Small talk", video_id: "v2", storage_bytes: 10_485_760, project_bytes: 10_485_760,
    cache_bytes: 0, freeable_bytes: 10_485_760 }),
  makeProject({ id: "p3", title: "Big talk again", video_id: "v1", storage_bytes: 429_916_160, project_bytes: 10_485_760,
    cache_bytes: 419_430_400, freeable_bytes: 10_485_760 }),
];

beforeEach(() => {
  vi.mocked(api.listProjects).mockReset().mockResolvedValue(projects);
  vi.mocked(api.deleteProject).mockReset().mockResolvedValue(undefined);
});

it("shows per-project and total disk use", async () => {
  renderWithProviders(<RecentProjects />);
  expect(await screen.findByText("500 MB")).toBeInTheDocument();
  // shared 400 MB download counted once: 100 + 10 + 10 + 400
  expect(screen.getByText(/3 projects · 520 MB on disk/)).toBeInTheDocument();
});

it("deletes a project only after confirming", async () => {
  const user = userEvent.setup();
  renderWithProviders(<RecentProjects />);
  await user.click(await screen.findByRole("button", { name: "Delete project Big talk" }));
  const dialog = screen.getByRole("alertdialog", { name: "Delete this project?" });
  expect(dialog).toHaveTextContent("freeing about 500 MB");

  await user.click(screen.getByRole("button", { name: "Cancel" }));
  expect(api.deleteProject).not.toHaveBeenCalled();

  await user.click(screen.getByRole("button", { name: "Delete project Big talk" }));
  await user.click(screen.getByRole("button", { name: "Delete project" }));
  await waitFor(() => expect(api.deleteProject).toHaveBeenCalledWith("p1"));
  await waitFor(() => expect(screen.queryByRole("alertdialog")).not.toBeInTheDocument());
});

it("only promises the space that deleting really frees", async () => {
  const user = userEvent.setup();
  renderWithProviders(<RecentProjects />);
  await user.click(await screen.findByRole("button", { name: "Delete project Big talk again" }));
  expect(screen.getByRole("alertdialog")).toHaveTextContent("freeing about 10.0 MB");
});

it("Escape cancels the confirmation", async () => {
  const user = userEvent.setup();
  renderWithProviders(<RecentProjects />);
  await user.click(await screen.findByRole("button", { name: "Delete project Small talk" }));
  await user.keyboard("{Escape}");
  await waitFor(() => expect(screen.queryByRole("alertdialog")).not.toBeInTheDocument());
  expect(api.deleteProject).not.toHaveBeenCalled();
});

it("formats byte sizes", () => {
  expect(formatBytes(0)).toBe("0 MB");
  expect(formatBytes(1536)).toBe("1.5 KB");
  expect(formatBytes(524_288_000)).toBe("500 MB");
  expect(formatBytes(3 * 1024 ** 3)).toBe("3.0 GB");
});
