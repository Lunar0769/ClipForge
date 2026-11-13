// frontend/src/features/gallery/AIChatPanel.tsx
import { useState, useRef, useEffect } from "react";
import { Bot, Send, Loader2, CheckCircle, XCircle } from "lucide-react";
import clsx from "clsx";
import { api } from "../../lib/api";

interface ChatMessage {
  id: string;
  role: "user" | "assistant";
  text: string;
  intent?: string;
  understood?: boolean;
  changes?: Record<string, unknown>;
  rerendering?: boolean;
  timestamp: Date;
}

const SUGGESTIONS = [
  "Make it faster — cut dead air",
  "Change captions to neon style",
  "Cut the first 5 seconds",
  "Add background music (energetic)",
  "Remove the hook title",
  "Switch to split screen layout",
  "Trim the last 3 seconds",
  "Remove B-roll overlays",
  "Change to clean minimal captions",
  "Turn off auto-zoom",
];

function formatChanges(changes: Record<string, unknown>): string {
  const labels: Record<string, (v: unknown) => string> = {
    start_s: (v) => `Start → ${(v as number).toFixed(1)}s`,
    end_s: (v) => `End → ${(v as number).toFixed(1)}s`,
    subtitle_style: (v) => `Captions → ${v}`,
    auto_zoom: (v) => `Auto-zoom ${v ? "on" : "off"}`,
    filler_trim: (v) => `Fast pacing ${v ? "on" : "off"}`,
    music_mood: (v) => (v ? `Music → ${v}` : "Music off"),
    broll_enabled: (v) => `B-roll ${v ? "on" : "off"}`,
    layout_mode: (v) => `Layout → ${v}`,
    hook_text: () => "Hook text updated",
    title: () => "Title updated",
    target_language: (v) => `Language → ${v}`,
  };
  return Object.entries(changes)
    .map(([k, v]) => labels[k]?.(v) ?? `${k}: ${v}`)
    .join(" · ");
}

interface Props {
  clipId: string;
  onEditApplied: () => void;
}

export function AIChatPanel({ clipId, onEditApplied }: Props) {
  const [messages, setMessages] = useState<ChatMessage[]>([
    {
      id: "welcome",
      role: "assistant",
      text: "Hey! I'm your AI editor. Tell me what to change — I can trim the clip, speed it up, change captions style, switch layouts, add music, and more.",
      timestamp: new Date(),
    },
  ]);
  const [input, setInput] = useState("");
  const [loading, setLoading] = useState(false);
  const bottomRef = useRef<HTMLDivElement>(null);
  const inputRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages]);

  const sendMessage = async (text: string) => {
    if (!text.trim() || loading) return;

    const userMsg: ChatMessage = {
      id: Date.now().toString(),
      role: "user",
      text: text.trim(),
      timestamp: new Date(),
    };
    setMessages((prev) => [...prev, userMsg]);
    setInput("");
    setLoading(true);

    // Optimistic "thinking" message
    const thinkingId = Date.now().toString() + "_t";
    setMessages((prev) => [
      ...prev,
      { id: thinkingId, role: "assistant", text: "thinking", timestamp: new Date() },
    ]);

    try {
      const result = await api.chatEditClip(clipId, text.trim());

      // Replace thinking with real response
      const assistantMsg: ChatMessage = {
        id: thinkingId,
        role: "assistant",
        text: result.summary,
        intent: result.intent,
        understood: result.understood,
        changes: result.changes,
        rerendering: result.rerender_triggered,
        timestamp: new Date(),
      };
      setMessages((prev) =>
        prev.map((m) => (m.id === thinkingId ? assistantMsg : m))
      );

      if (result.rerender_triggered) {
        // Notify parent to refresh video after re-render completes
        setTimeout(() => {
          onEditApplied();
        }, 4500);
      }
    } catch {
      setMessages((prev) =>
        prev.map((m) =>
          m.id === thinkingId
            ? {
                ...m,
                text: "Something went wrong. The server might be busy — try again.",
                understood: false,
              }
            : m
        )
      );
    } finally {
      setLoading(false);
      inputRef.current?.focus();
    }
  };

  return (
    <div className="flex flex-col h-full">
      {/* Header */}
      <div className="flex items-center gap-2 px-3 py-2.5 border-b border-border/60 bg-surface">
        <div className="flex size-7 items-center justify-center rounded-lg bg-violet-brand/15">
          <Bot className="size-4 text-violet-brand" />
        </div>
        <div>
          <p className="text-xs font-semibold text-fg">AI Editor</p>
          <p className="text-[10px] text-muted">Type an instruction to edit this clip</p>
        </div>
        <div className="ml-auto flex items-center gap-1 rounded-full bg-green-500/15 border border-green-500/30 px-2 py-0.5">
          <div className="size-1.5 rounded-full bg-green-400 animate-pulse" />
          <span className="text-[10px] font-medium text-green-400">Ready</span>
        </div>
      </div>

      {/* Messages */}
      <div className="flex-1 overflow-y-auto px-3 py-3 space-y-3 min-h-0">
        {messages.map((msg) => (
          <div
            key={msg.id}
            className={clsx(
              "flex gap-2",
              msg.role === "user" ? "justify-end" : "justify-start"
            )}
          >
            {msg.role === "assistant" && (
              <div className="flex size-6 shrink-0 items-center justify-center rounded-full bg-violet-brand/20 mt-0.5">
                <Bot className="size-3.5 text-violet-brand" />
              </div>
            )}

            <div
              className={clsx(
                "max-w-[85%] rounded-2xl px-3 py-2 text-xs leading-relaxed",
                msg.role === "user"
                  ? "bg-violet-brand text-white rounded-tr-sm"
                  : "bg-surface-2 text-fg rounded-tl-sm border border-border/60"
              )}
            >
              {msg.text === "thinking" ? (
                <span className="flex items-center gap-1.5 text-muted">
                  <Loader2 className="size-3 animate-spin" />
                  Thinking...
                </span>
              ) : (
                <>
                  <p>{msg.text}</p>
                  {msg.role === "assistant" &&
                    msg.changes &&
                    Object.keys(msg.changes).length > 0 && (
                      <p className="mt-1.5 text-[10px] text-muted/80 border-t border-border/40 pt-1.5">
                        {formatChanges(msg.changes)}
                      </p>
                    )}
                  {msg.role === "assistant" && msg.rerendering && (
                    <span className="mt-1.5 flex items-center gap-1 text-[10px] text-violet-400">
                      <Loader2 className="size-2.5 animate-spin" />
                      Re-rendering video…
                    </span>
                  )}
                  {msg.role === "assistant" && msg.understood === false && (
                    <span className="mt-1 flex items-center gap-1 text-[10px] text-amber-400">
                      <XCircle className="size-2.5" />
                      Couldn't understand that
                    </span>
                  )}
                  {msg.role === "assistant" &&
                    msg.understood === true &&
                    msg.changes &&
                    Object.keys(msg.changes).length > 0 && (
                      <span className="mt-1 flex items-center gap-1 text-[10px] text-green-400">
                        <CheckCircle className="size-2.5" />
                        Applied
                      </span>
                    )}
                </>
              )}
            </div>
          </div>
        ))}
        <div ref={bottomRef} />
      </div>

      {/* Quick suggestions (shown when only welcome message) */}
      {messages.length === 1 && (
        <div className="px-3 pb-2">
          <p className="text-[10px] text-muted mb-1.5 font-medium">Try saying:</p>
          <div className="flex flex-wrap gap-1">
            {SUGGESTIONS.slice(0, 6).map((s) => (
              <button
                key={s}
                type="button"
                onClick={() => sendMessage(s)}
                className="rounded-lg bg-surface-2 border border-border/60 px-2 py-1 text-[10px] text-muted hover:text-fg hover:border-violet-brand/40 transition"
              >
                {s}
              </button>
            ))}
          </div>
        </div>
      )}

      {/* Input */}
      <div className="border-t border-border/60 p-2.5 bg-surface">
        <form
          onSubmit={(e) => {
            e.preventDefault();
            void sendMessage(input);
          }}
          className="flex gap-2"
        >
          <input
            ref={inputRef}
            value={input}
            onChange={(e) => setInput(e.target.value)}
            placeholder="e.g. make it faster, neon captions..."
            disabled={loading}
            className="flex-1 rounded-xl bg-surface-2 border border-border/80 px-3 py-2 text-xs text-fg placeholder:text-muted focus:outline-none focus:border-violet-brand/60 disabled:opacity-50 transition"
          />
          <button
            type="submit"
            disabled={!input.trim() || loading}
            className="flex size-9 shrink-0 items-center justify-center rounded-xl bg-violet-brand text-white transition hover:bg-violet-600 disabled:opacity-40 disabled:cursor-not-allowed"
          >
            {loading ? (
              <Loader2 className="size-4 animate-spin" />
            ) : (
              <Send className="size-3.5" />
            )}
          </button>
        </form>
      </div>
    </div>
  );
}
