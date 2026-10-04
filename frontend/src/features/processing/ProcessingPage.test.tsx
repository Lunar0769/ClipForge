import { screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, expect, it, vi } from "vitest";
import { api } from "../../lib/api";
import { makeJob, makeProject } from "../../test/fixtures";
import { renderWithProviders } from "../../test/utils";
import { initialJobViewState } from "./jobEvents";
import ProcessingPage from "./ProcessingPage";
import { useJobEvents } from "./useJobEvents";

vi.mock("../../lib/api", async (importOriginal) => {
  const actual = await importOriginal<typeof import("../../lib/api")>();
  return {
    ...actual,
    api: { ...actual.api, getProject: vi.fn(), stages: vi.fn(), transcript: vi.fn(), retry: vi.fn(), cancelJob: vi.fn() },
  };
});
vi.mock("./useJobEvents", () => ({ useJobEvents: vi.fn() }));

const route = { route: "/projects/p1", path: "/projects/:projectId" };

beforeEach(() => {
  vi.mocked(api.stages).mockResolvedValue([
    { name: "ingest", label: "Importing video", weight: 1 },
    { name: "transcribe", label: "Transcribing speech", weight: 3 },
  ]);
});

it("shows live stages, overall progress and the streamed transcript", async () => {
  vi.mocked(api.getProject).mockResolvedValue(
    makeProject({ title: "My Talk", latest_job: makeJob({ status: "running" }) }),
  );
  vi.mocked(useJobEvents).mockReturnValue({
    ...initialJobViewState,
    jobStatus: "running",
    language: "en",
    stages: {
      ingest: { status: "done", progress: 1, message: null },
      transcribe: { status: "running", progress: 0.5, message: null },
    },
    transcript: [{ start: 0, end: 1, text: "Hello world." }],
  });
  renderWithProviders(<ProcessingPage />, route);

  expect(await screen.findByText("My Talk")).toBeInTheDocument();
  expect(await screen.findByText("Hello world.")).toBeInTheDocument();
  expect(screen.getByText("Importing video").closest("li")).toHaveAttribute("data-status", "done");
  expect(screen.getByText("Transcribing speech").closest("li")).toHaveAttribute("data-status", "running");
  expect(screen.getByRole("progressbar")).toHaveAttribute("aria-valuenow", "63");
  expect(screen.getByRole("button", { name: /cancel/i })).toBeInTheDocument();
});

it("explains failures and retries", async () => {
  vi.mocked(api.getProject).mockResolvedValue(makeProject({ latest_job: makeJob({ status: "failed" }) }));
  vi.mocked(api.retry).mockResolvedValue(makeProject({ latest_job: makeJob({ id: "j2", status: "queued" }) }));
  vi.mocked(useJobEvents).mockReturnValue({
    ...initialJobViewState,
    jobStatus: "failed",
    error: "YouTube blocked the download.",
    hint: "Update yt-dlp, then press Retry.",
    stages: { ingest: { status: "failed", progress: 0.2, message: "YouTube blocked the download." } },
  });
  renderWithProviders(<ProcessingPage />, route);

  expect(await screen.findByText("Update yt-dlp, then press Retry.")).toBeInTheDocument();
  await userEvent.click(screen.getByRole("button", { name: /retry/i }));
  expect(api.retry).toHaveBeenCalledWith("p1");
});

it("shows a friendly message for unknown projects", async () => {
  vi.mocked(api.getProject).mockRejectedValue(new Error("Project not found"));
  vi.mocked(useJobEvents).mockReturnValue(initialJobViewState);
  renderWithProviders(<ProcessingPage />, route);
  expect(await screen.findByText(/couldn't find this project/i)).toBeInTheDocument();
});

it("rebuilds the view from the REST job when there are no live events (API restarted)", async () => {
  vi.mocked(api.getProject).mockResolvedValue(
    makeProject({ title: "Silent", latest_job: makeJob({ status: "succeeded", stage: "transcribe", progress: 1 }) }),
  );
  vi.mocked(api.transcript).mockResolvedValue({ language: "en", duration_s: 3, segments: [] });
  vi.mocked(useJobEvents).mockReturnValue(initialJobViewState);
  renderWithProviders(<ProcessingPage />, route);

  expect(await screen.findByText("No speech was detected in this video.")).toBeInTheDocument();
  expect(screen.getByRole("progressbar")).toHaveAttribute("aria-valuenow", "100");
  expect(screen.getByText("Importing video").closest("li")).toHaveAttribute("data-status", "done");
  expect(screen.getByText("Transcribing speech").closest("li")).toHaveAttribute("data-status", "done");
});

it("shows the failed stage from the REST job when there are no live events", async () => {
  vi.mocked(api.getProject).mockResolvedValue(
    makeProject({ latest_job: makeJob({ status: "failed", stage: "transcribe", progress: 0.4, error: "GPU fell over" }) }),
  );
  vi.mocked(useJobEvents).mockReturnValue(initialJobViewState);
  renderWithProviders(<ProcessingPage />, route);

  expect(await screen.findByText("GPU fell over")).toBeInTheDocument();
  expect(await screen.findByText("Importing video")).toBeInTheDocument();
  expect(screen.getByText("Importing video").closest("li")).toHaveAttribute("data-status", "done");
  expect(screen.getByText("Transcribing speech").closest("li")).toHaveAttribute("data-status", "failed");
  expect(screen.getByRole("progressbar")).toHaveAttribute("aria-valuenow", "40");
});

it("prefers the saved transcript over streamed partials once the job succeeded", async () => {
  vi.mocked(api.getProject).mockResolvedValue(
    makeProject({ latest_job: makeJob({ status: "succeeded", stage: "transcribe", progress: 1 }) }),
  );
  vi.mocked(api.transcript).mockResolvedValue({
    language: "en", duration_s: 3,
    segments: [{ id: 0, start: 0, end: 1, text: "First full line." }, { id: 1, start: 1, end: 2, text: "Second full line." }],
  });
  vi.mocked(useJobEvents).mockReturnValue({
    ...initialJobViewState,
    jobStatus: "succeeded",
    transcript: [{ start: 1, end: 2, text: "Second full line." }], // replayed history kept only the tail
  });
  renderWithProviders(<ProcessingPage />, route);

  expect(await screen.findByText("First full line.")).toBeInTheDocument();
  expect(screen.getAllByText("Second full line.")).toHaveLength(1);
});
