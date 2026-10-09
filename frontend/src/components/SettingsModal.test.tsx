import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { api } from "../lib/api";
import { SettingsModal } from "./SettingsModal";

vi.mock("../lib/api", () => ({
  api: {
    getSettings: vi.fn(),
    updateSettings: vi.fn(),
    testProvider: vi.fn(),
    system: vi.fn(),
  },
}));

describe("SettingsModal", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    vi.mocked(api.getSettings).mockResolvedValue({
      provider: "gemini",
      gemini_key_set: true,
      openai_key_set: false,
      anthropic_key_set: false,
      ollama_host: "http://localhost:11434",
      default_subtitle_style: "hormozi",
      default_auto_zoom: true,
      default_music_mood: null,
    });
    vi.mocked(api.system).mockResolvedValue({
      gpus: [{ name: "NVIDIA GeForce RTX 4070", memory_total_mb: 12288, driver: "551.86" }],
      ffmpeg: true,
      nvenc: true,
    });
  });

  it("does not render when isOpen is false", () => {
    const { container } = render(<SettingsModal isOpen={false} onClose={vi.fn()} />);
    expect(container).toBeEmptyDOMElement();
  });

  it("renders tabs and loads settings when isOpen is true", async () => {
    render(<SettingsModal isOpen={true} onClose={vi.fn()} />);

    expect(screen.getByRole("dialog", { name: /clipforge studio settings/i })).toBeInTheDocument();
    expect(screen.getByText(/studio settings & ai brain/i)).toBeInTheDocument();

    await waitFor(() => {
      expect(screen.getByText("Google Gemini API Key")).toBeInTheDocument();
    });
    expect(screen.getByText(/key saved/i)).toBeInTheDocument();
  });

  it("switches tabs to generation defaults and hardware", async () => {
    render(<SettingsModal isOpen={true} onClose={vi.fn()} />);

    await waitFor(() => {
      expect(screen.getByText(/generation defaults/i)).toBeInTheDocument();
    });

    await userEvent.click(screen.getByText(/generation defaults/i));
    expect(screen.getByText(/default kinetic subtitle style/i)).toBeInTheDocument();
    expect(screen.getByText(/retention auto-zoom punch-in/i)).toBeInTheDocument();

    await userEvent.click(screen.getByText(/hardware & acceleration/i));
    await waitFor(() => {
      expect(screen.getByText(/nvidia geforce rtx 4070/i)).toBeInTheDocument();
      expect(screen.getByText(/12 gb vram/i)).toBeInTheDocument();
    });
  });

  it("triggers provider test and displays status", async () => {
    vi.mocked(api.testProvider).mockResolvedValue({
      ok: true,
      message: "Connected successfully to Gemini!",
      model: "gemini-2.5-flash",
    });

    render(<SettingsModal isOpen={true} onClose={vi.fn()} />);

    await waitFor(() => {
      expect(screen.getAllByRole("button", { name: /test ping/i })[0]).toBeInTheDocument();
    });

    const testButtons = screen.getAllByRole("button", { name: /test ping/i });
    await userEvent.click(testButtons[0]);

    await waitFor(() => {
      expect(screen.getByText(/connected successfully to gemini!/i)).toBeInTheDocument();
    });
  });
});
