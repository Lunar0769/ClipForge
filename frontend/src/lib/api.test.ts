import { afterEach, describe, expect, it, vi } from "vitest";
import { ApiError, api, jobEventsUrl } from "./api";

function jsonResponse(body: unknown, status = 200) {
  return new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } });
}

describe("api", () => {
  afterEach(() => vi.unstubAllGlobals());

  it("parses JSON responses", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(jsonResponse([{ id: "p1" }])));
    await expect(api.listProjects()).resolves.toEqual([{ id: "p1" }]);
  });

  it("posts JSON for createFromUrl", async () => {
    const fetchMock = vi.fn().mockResolvedValue(jsonResponse({ id: "p1" }, 201));
    vi.stubGlobal("fetch", fetchMock);
    await api.createFromUrl("https://youtu.be/x");
    const [url, init] = fetchMock.mock.calls[0];
    expect(url).toBe("/api/projects");
    expect(init.method).toBe("POST");
    expect(JSON.parse(init.body)).toEqual({ url: "https://youtu.be/x" });
    expect(init.headers["Content-Type"]).toBe("application/json");
  });

  it("throws ApiError with the server's detail message", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(jsonResponse({ detail: "Enter a full http(s) link" }, 422)));
    await expect(api.createFromUrl("x")).rejects.toMatchObject({ status: 422, message: "Enter a full http(s) link" });
  });

  it("flattens FastAPI validation errors", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(jsonResponse({ detail: [{ msg: "Field required" }] }, 422)));
    const error = await api.createFromUrl("x").catch((e) => e);
    expect(error).toBeInstanceOf(ApiError);
    expect(error.message).toBe("Field required");
  });

  it("builds websocket URLs from the page origin", () => {
    expect(jobEventsUrl("j1")).toBe(`ws://${window.location.host}/api/jobs/j1/events`);
  });
});
