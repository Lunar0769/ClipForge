import { act, renderHook } from "@testing-library/react";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { useJobEvents } from "./useJobEvents";

class FakeSocket {
  static instances: FakeSocket[] = [];
  onopen: (() => void) | null = null;
  onmessage: ((m: { data: string }) => void) | null = null;
  onclose: (() => void) | null = null;
  constructor(public url: string) {
    FakeSocket.instances.push(this);
  }
  close() {}
  emit(event: object) {
    this.onmessage?.({ data: JSON.stringify(event) });
  }
}

const ev = (e: object) => ({ job_id: "j", stage: null, status: null, progress: null, message: null, data: null, ts: 0, ...e });
const last = () => FakeSocket.instances[FakeSocket.instances.length - 1];

beforeEach(() => {
  FakeSocket.instances = [];
  vi.stubGlobal("WebSocket", FakeSocket);
  vi.useFakeTimers();
});
afterEach(() => {
  vi.useRealTimers();
  vi.unstubAllGlobals();
});

it("dispatches events into state", () => {
  const { result } = renderHook(() => useJobEvents("j1"));
  act(() => last().onopen?.());
  act(() => last().emit(ev({ type: "job", status: "running" })));
  expect(result.current.jobStatus).toBe("running");
});

it("ignores malformed frames", () => {
  const { result } = renderHook(() => useJobEvents("j1"));
  act(() => last().onmessage?.({ data: "not json" }));
  expect(result.current.jobStatus).toBeNull();
});

it("resets state immediately when the job id changes", () => {
  const { result, rerender } = renderHook(({ id }) => useJobEvents(id), { initialProps: { id: "j1" } });
  act(() => last().emit(ev({ type: "job", status: "failed", message: "boom" })));
  expect(result.current.jobStatus).toBe("failed");
  rerender({ id: "j2" });
  expect(result.current.jobStatus).toBeNull();
  expect(result.current.error).toBeNull();
  expect(FakeSocket.instances).toHaveLength(2);
});

it("does not reconnect after a terminal event", () => {
  renderHook(() => useJobEvents("j1"));
  act(() => last().emit(ev({ type: "job", status: "succeeded" })));
  act(() => last().onclose?.());
  act(() => void vi.advanceTimersByTime(30_000));
  expect(FakeSocket.instances).toHaveLength(1);
});

it("reconnects after an unexpected close", () => {
  renderHook(() => useJobEvents("j1"));
  act(() => last().onclose?.());
  act(() => void vi.advanceTimersByTime(1000));
  expect(FakeSocket.instances).toHaveLength(2);
});
