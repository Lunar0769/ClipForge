import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, expect, it, vi } from "vitest";
import { ApiError, api } from "../../lib/api";
import { makeJob, makeProject } from "../../test/fixtures";
import { renderWithProviders } from "../../test/utils";
import HomePage from "./HomePage";

vi.mock("../../lib/api", async (importOriginal) => {
  const actual = await importOriginal<typeof import("../../lib/api")>();
  return {
    ...actual,
    api: { ...actual.api, createFromUrl: vi.fn(), listProjects: vi.fn(), upload: vi.fn() },
  };
});
vi.mock("../../components/ShaderBackground", () => ({ default: () => null }));

beforeEach(() => {
  vi.mocked(api.listProjects).mockResolvedValue([]);
  vi.mocked(api.createFromUrl).mockReset();
  vi.mocked(api.upload).mockReset();
});

it("creates a project from a pasted link and opens it", async () => {
  vi.mocked(api.createFromUrl).mockResolvedValue(makeProject({ id: "p1" }));
  renderWithProviders(<HomePage />);
  await userEvent.type(screen.getByLabelText(/video link/i), "youtube.com/watch?v=abc");
  await userEvent.click(screen.getByRole("button", { name: /forge clips/i }));
  await waitFor(() => expect(api.createFromUrl).toHaveBeenCalledWith("https://youtube.com/watch?v=abc"));
  expect(await screen.findByTestId("location")).toHaveTextContent("/projects/p1");
});

it("explains invalid links without calling the API", async () => {
  renderWithProviders(<HomePage />);
  await userEvent.type(screen.getByLabelText(/video link/i), "hello");
  await userEvent.click(screen.getByRole("button", { name: /forge clips/i }));
  expect(await screen.findByRole("alert")).toHaveTextContent(/doesn't look like a video link/i);
  expect(api.createFromUrl).not.toHaveBeenCalled();
});

it("shows server errors", async () => {
  vi.mocked(api.createFromUrl).mockRejectedValue(new ApiError(422, "Enter a full http(s) link"));
  renderWithProviders(<HomePage />);
  await userEvent.type(screen.getByLabelText(/video link/i), "https://youtu.be/x");
  await userEvent.click(screen.getByRole("button", { name: /forge clips/i }));
  expect(await screen.findByRole("alert")).toHaveTextContent("Enter a full http(s) link");
});

it("rejects unsupported upload types", async () => {
  const user = userEvent.setup({ applyAccept: false });
  renderWithProviders(<HomePage />);
  await user.upload(screen.getByTestId("file-input"), new File(["x"], "notes.txt", { type: "text/plain" }));
  expect(await screen.findByRole("alert")).toHaveTextContent(/unsupported file type/i);
  expect(api.upload).not.toHaveBeenCalled();
});

it("uploads a video and opens the project", async () => {
  vi.mocked(api.upload).mockImplementation(async (_file, onProgress) => {
    onProgress(0.5);
    return makeProject({ id: "p2" });
  });
  const user = userEvent.setup({ applyAccept: false });
  renderWithProviders(<HomePage />);
  await user.upload(screen.getByTestId("file-input"), new File(["x"], "talk.MP4", { type: "video/mp4" }));
  expect(await screen.findByTestId("location")).toHaveTextContent("/projects/p2");
});

it("lists recent projects with their status", async () => {
  vi.mocked(api.listProjects).mockResolvedValue([
    makeProject({ id: "p3", title: "My Talk", latest_job: makeJob({ status: "succeeded" }) }),
  ]);
  renderWithProviders(<HomePage />);
  expect(await screen.findByText("My Talk")).toBeInTheDocument();
  expect(screen.getByText("Ready")).toBeInTheDocument();
});
