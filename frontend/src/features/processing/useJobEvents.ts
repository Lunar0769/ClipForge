import { useEffect, useReducer } from "react";
import { jobEventsUrl } from "../../lib/api";
import { isTerminal, type JobEvent, type JobStatus } from "../../lib/types";
import { initialJobViewState, jobEventsReducer, type JobViewState } from "./jobEvents";

/** Live job state from the WebSocket. The server replays history on connect, so we reset first. */
export function useJobEvents(jobId: string | undefined): JobViewState {
  const [state, dispatch] = useReducer(jobEventsReducer, initialJobViewState);

  useEffect(() => {
    dispatch({ type: "reset" });
    if (!jobId) return;
    let socket: WebSocket | null = null;
    let closed = false;
    let finished = false;
    let attempt = 0;
    let timer: number | undefined;

    const connect = () => {
      socket = new WebSocket(jobEventsUrl(jobId));
      socket.onopen = () => {
        attempt = 0;
        dispatch({ type: "reset" });
      };
      socket.onmessage = (message) => {
        if (closed) return;
        let event: JobEvent;
        try {
          event = JSON.parse(message.data) as JobEvent;
        } catch {
          return;
        }
        // The server keeps the socket open after the terminal event; don't reconnect (and replay) once finished.
        if (event.type === "job" && isTerminal(event.status as JobStatus)) finished = true;
        dispatch(event);
      };
      socket.onclose = () => {
        if (closed || finished) return;
        timer = window.setTimeout(connect, Math.min(1000 * 2 ** attempt++, 10_000));
      };
    };

    connect();
    return () => {
      closed = true;
      window.clearTimeout(timer);
      socket?.close();
    };
  }, [jobId]);

  return state;
}
