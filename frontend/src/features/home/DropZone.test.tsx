import { render } from "@testing-library/react";
import { expect, it } from "vitest";
import { DropZone } from "./DropZone";

function windowDragEvent(type: "dragover" | "drop", types: string[]): Event {
  const event = new Event(type, { bubbles: true, cancelable: true });
  Object.defineProperty(event, "dataTransfer", { value: { types, files: [] } });
  window.dispatchEvent(event);
  return event;
}

it("stops a file dropped outside the drop zone from navigating the browser away", () => {
  const { unmount } = render(<DropZone onUploaded={() => {}} />);
  expect(windowDragEvent("dragover", ["Files"]).defaultPrevented).toBe(true);
  expect(windowDragEvent("drop", ["Files"]).defaultPrevented).toBe(true);
  // Dragging text (e.g. into the link input) keeps working.
  expect(windowDragEvent("drop", ["text/plain"]).defaultPrevented).toBe(false);
  unmount();
  expect(windowDragEvent("drop", ["Files"]).defaultPrevented).toBe(false);
});
