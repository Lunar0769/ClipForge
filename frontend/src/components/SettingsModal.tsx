import {
  AlertCircle,
  BrainCircuit,
  Check,
  CheckCircle2,
  Cpu,
  Eye,
  EyeOff,
  Flame,
  Layers,
  Loader2,
  Radio,
  Server,
  SlidersHorizontal,
  Sparkles,
  X,
  Zap,
} from "lucide-react";
import { useEffect, useState } from "react";
import { api } from "../lib/api";
import type { AppSettings, SystemInfo } from "../lib/types";

interface SettingsModalProps {
  isOpen: boolean;
  onClose: () => void;
}

type TabKey = "brain" | "defaults" | "hardware";

export function SettingsModal({ isOpen, onClose }: SettingsModalProps) {
  const [activeTab, setActiveTab] = useState<TabKey>("brain");
  const [loading, setLoading] = useState(false);
  const [saving, setSaving] = useState(false);
  const [saveSuccess, setSaveSuccess] = useState(false);
  const [errorMsg, setErrorMsg] = useState<string | null>(null);

  // Settings values
  const [settings, setSettings] = useState<AppSettings | null>(null);
  const [provider, setProvider] = useState<string>("gemini");
  const [geminiKey, setGeminiKey] = useState("");
  const [openaiKey, setOpenaiKey] = useState("");
  const [anthropicKey, setAnthropicKey] = useState("");
  const [ollamaHost, setOllamaHost] = useState("http://localhost:11434");
  const [subtitleStyle, setSubtitleStyle] = useState("hormozi");
  const [autoZoom, setAutoZoom] = useState(true);
  const [musicMood, setMusicMood] = useState<string | null>(null);

  // Password visibility toggles
  const [showGemini, setShowGemini] = useState(false);
  const [showOpenai, setShowOpenai] = useState(false);
  const [showAnthropic, setShowAnthropic] = useState(false);

  // Provider test state
  const [testingProvider, setTestingProvider] = useState<string | null>(null);
  const [testResult, setTestResult] = useState<{
    provider: string;
    ok: boolean;
    message: string;
    model?: string | null;
  } | null>(null);

  // System Hardware Info
  const [systemInfo, setSystemInfo] = useState<SystemInfo | null>(null);
  const [loadingSystem, setLoadingSystem] = useState(false);

  // Fetch settings on open
  useEffect(() => {
    if (!isOpen) return;
    setLoading(true);
    setErrorMsg(null);
    setSaveSuccess(false);

    api
      .getSettings()
      .then((data) => {
        setSettings(data);
        setProvider(data.provider || "gemini");
        setOllamaHost(data.ollama_host || "http://localhost:11434");
        setSubtitleStyle(data.default_subtitle_style || "hormozi");
        setAutoZoom(data.default_auto_zoom !== false);
        setMusicMood(data.default_music_mood || null);
      })
      .catch((err) => {
        setErrorMsg(err?.message || "Failed to load current settings");
      })
      .finally(() => {
        setLoading(false);
      });

    setLoadingSystem(true);
    api
      .system()
      .then((info) => setSystemInfo(info))
      .catch(() => {})
      .finally(() => setLoadingSystem(false));
  }, [isOpen]);

  // Handle escape key
  useEffect(() => {
    const handleKeyDown = (e: KeyboardEvent) => {
      if (e.key === "Escape" && isOpen && !saving) {
        onClose();
      }
    };
    window.addEventListener("keydown", handleKeyDown);
    return () => window.removeEventListener("keydown", handleKeyDown);
  }, [isOpen, saving, onClose]);

  if (!isOpen) return null;

  const handleSave = async () => {
    setSaving(true);
    setErrorMsg(null);
    setSaveSuccess(false);

    try {
      const updated = await api.updateSettings({
        provider,
        gemini_api_key: geminiKey.trim() || undefined,
        openai_api_key: openaiKey.trim() || undefined,
        anthropic_api_key: anthropicKey.trim() || undefined,
        ollama_host: ollamaHost.trim() || undefined,
        default_subtitle_style: subtitleStyle,
        default_auto_zoom: autoZoom,
        default_music_mood: musicMood,
      });

      setSettings(updated);
      setGeminiKey("");
      setOpenaiKey("");
      setAnthropicKey("");
      setSaveSuccess(true);
      setTimeout(() => setSaveSuccess(false), 3000);
    } catch (err: unknown) {
      const e = err as { message?: string };
      setErrorMsg(e?.message || "Failed to save settings");
    } finally {
      setSaving(false);
    }
  };

  const handleTestProvider = async (targetProvider: string) => {
    setTestingProvider(targetProvider);
    setTestResult(null);

    let keyToSend: string | undefined = undefined;
    if (targetProvider === "gemini") keyToSend = geminiKey.trim() || undefined;
    if (targetProvider === "openai") keyToSend = openaiKey.trim() || undefined;
    if (targetProvider === "anthropic") keyToSend = anthropicKey.trim() || undefined;

    try {
      const res = await api.testProvider({
        provider: targetProvider,
        api_key: keyToSend,
        ollama_host: targetProvider === "ollama" ? ollamaHost.trim() : undefined,
      });
      setTestResult({
        provider: targetProvider,
        ok: res.ok,
        message: res.message,
        model: res.model,
      });
    } catch (err: unknown) {
      const e = err as { message?: string };
      setTestResult({
        provider: targetProvider,
        ok: false,
        message: e?.message || "Failed to communicate with provider",
      });
    } finally {
      setTestingProvider(null);
    }
  };

  return (
    <div
      role="dialog"
      aria-modal="true"
      aria-label="ClipForge Studio Settings"
      className="fixed inset-0 z-50 flex items-center justify-center p-3 sm:p-6 bg-black/80 backdrop-blur-md animate-in fade-in duration-200"
    >
      <div
        className="relative flex flex-col w-full max-w-2xl max-h-[90vh] rounded-3xl bg-surface-1 border border-border/80 shadow-2xl shadow-violet-brand/10 overflow-hidden"
        onClick={(e) => e.stopPropagation()}
      >
        {/* Header */}
        <div className="flex items-center justify-between border-b border-border/70 px-6 py-4 bg-surface-2/40">
          <div className="flex items-center gap-3">
            <div className="grid size-9 place-items-center rounded-xl bg-violet-brand/20 text-violet-300">
              <SlidersHorizontal className="size-5" />
            </div>
            <div>
              <h2 className="font-display text-base font-semibold text-fg">
                Studio Settings & AI Brain
              </h2>
              <p className="text-xs text-muted">
                Configure LLM moment detectors, default subtitles, and render hardware
              </p>
            </div>
          </div>
          <button
            type="button"
            disabled={saving}
            onClick={onClose}
            className="rounded-full p-1.5 text-muted hover:text-fg hover:bg-surface-3 transition"
            aria-label="Close settings"
          >
            <X className="size-4" />
          </button>
        </div>

        {/* Navigation Tabs */}
        <div className="flex border-b border-border/60 bg-surface-2/20 px-6 pt-2 gap-2">
          <button
            type="button"
            onClick={() => setActiveTab("brain")}
            className={`flex items-center gap-2 border-b-2 px-3 py-2.5 text-xs font-semibold transition ${
              activeTab === "brain"
                ? "border-violet-brand text-fg"
                : "border-transparent text-muted hover:text-fg"
            }`}
          >
            <BrainCircuit className="size-3.5" />
            AI Brain & Providers
          </button>
          <button
            type="button"
            onClick={() => setActiveTab("defaults")}
            className={`flex items-center gap-2 border-b-2 px-3 py-2.5 text-xs font-semibold transition ${
              activeTab === "defaults"
                ? "border-violet-brand text-fg"
                : "border-transparent text-muted hover:text-fg"
            }`}
          >
            <Layers className="size-3.5" />
            Generation Defaults
          </button>
          <button
            type="button"
            onClick={() => setActiveTab("hardware")}
            className={`flex items-center gap-2 border-b-2 px-3 py-2.5 text-xs font-semibold transition ${
              activeTab === "hardware"
                ? "border-violet-brand text-fg"
                : "border-transparent text-muted hover:text-fg"
            }`}
          >
            <Cpu className="size-3.5" />
            Hardware & Acceleration
          </button>
        </div>

        {/* Content Body */}
        <div className="flex-1 overflow-y-auto p-6 space-y-6">
          {loading ? (
            <div className="flex flex-col items-center justify-center py-16 gap-3 text-muted">
              <Loader2 className="size-6 animate-spin text-violet-brand" />
              <p className="text-xs">Loading studio configuration...</p>
            </div>
          ) : (
            <>
              {errorMsg && (
                <div className="flex items-center gap-2.5 rounded-xl border border-red-500/30 bg-red-500/10 p-3.5 text-xs text-red-300">
                  <AlertCircle className="size-4 shrink-0" />
                  <span>{errorMsg}</span>
                </div>
              )}

              {saveSuccess && (
                <div className="flex items-center gap-2.5 rounded-xl border border-emerald-500/30 bg-emerald-500/10 p-3.5 text-xs text-emerald-300">
                  <CheckCircle2 className="size-4 shrink-0" />
                  <span>Settings successfully saved and reloaded!</span>
                </div>
              )}

              {/* TAB 1: AI Brain */}
              {activeTab === "brain" && (
                <div className="space-y-6">
                  {/* Provider selection cards */}
                  <div>
                    <label className="block text-xs font-semibold text-muted uppercase tracking-wider mb-2.5">
                      Active AI Detection Brain
                    </label>
                    <div className="grid grid-cols-2 sm:grid-cols-4 gap-2.5">
                      {[
                        { id: "gemini", name: "Google Gemini", sub: "Gemini 2.5/Flash" },
                        { id: "openai", name: "OpenAI", sub: "GPT-4o Mini" },
                        { id: "anthropic", name: "Anthropic", sub: "Claude 3.5 Haiku" },
                        { id: "ollama", name: "Ollama (Local)", sub: "Self-hosted LLM" },
                      ].map((item) => {
                        const active = provider === item.id;
                        return (
                          <button
                            key={item.id}
                            type="button"
                            onClick={() => setProvider(item.id)}
                            className={`flex flex-col items-start p-3 rounded-2xl border text-left transition ${
                              active
                                ? "border-violet-brand bg-violet-brand/10 shadow-sm shadow-violet-brand/20 ring-1 ring-violet-brand"
                                : "border-border/70 bg-surface-2/40 hover:bg-surface-2 hover:border-border"
                            }`}
                          >
                            <span
                              className={`text-xs font-semibold ${
                                active ? "text-violet-200" : "text-fg"
                              }`}
                            >
                              {item.name}
                            </span>
                            <span className="text-[10px] text-muted">{item.sub}</span>
                          </button>
                        );
                      })}
                    </div>
                  </div>

                  {/* Provider Keys */}
                  <div className="space-y-4 pt-2">
                    {/* Google Gemini */}
                    <div className="p-4 rounded-2xl border border-border/70 bg-surface-2/30 space-y-2.5">
                      <div className="flex items-center justify-between">
                        <div className="flex items-center gap-2">
                          <span className="text-xs font-semibold text-fg">Google Gemini API Key</span>
                          {settings?.gemini_key_set ? (
                            <span className="flex items-center gap-1 rounded-full bg-emerald-500/20 px-2 py-0.5 text-[10px] font-medium text-emerald-300">
                              <Check className="size-2.5" /> Key Saved
                            </span>
                          ) : (
                            <span className="rounded-full bg-surface-3 px-2 py-0.5 text-[10px] text-muted">
                              Not Set
                            </span>
                          )}
                        </div>
                        <button
                          type="button"
                          disabled={testingProvider === "gemini"}
                          onClick={() => handleTestProvider("gemini")}
                          className="flex items-center gap-1.5 rounded-lg border border-border/80 bg-surface-3 px-2.5 py-1 text-[11px] font-medium text-fg hover:bg-surface-2 transition disabled:opacity-50"
                        >
                          {testingProvider === "gemini" ? (
                            <Loader2 className="size-3 animate-spin text-violet-brand" />
                          ) : (
                            <Radio className="size-3 text-cyan-400" />
                          )}
                          Test Ping
                        </button>
                      </div>
                      <div className="relative">
                        <input
                          type={showGemini ? "text" : "password"}
                          placeholder={settings?.gemini_key_set ? "••••••••••••••••••••••••" : "AIzaSy..."}
                          value={geminiKey}
                          onChange={(e) => setGeminiKey(e.target.value)}
                          className="w-full rounded-xl border border-border/80 bg-surface-1 px-3 py-2 pr-9 text-xs font-mono text-fg placeholder:text-muted/50 focus:border-violet-brand focus:outline-none"
                        />
                        <button
                          type="button"
                          onClick={() => setShowGemini(!showGemini)}
                          className="absolute right-2.5 top-1/2 -translate-y-1/2 text-muted hover:text-fg"
                        >
                          {showGemini ? <EyeOff className="size-3.5" /> : <Eye className="size-3.5" />}
                        </button>
                      </div>
                      <p className="text-[10px] text-muted">
                        Get your free API key at <a href="https://aistudio.google.com" target="_blank" rel="noreferrer" className="text-violet-400 underline">aistudio.google.com</a>
                      </p>
                    </div>

                    {/* OpenAI */}
                    <div className="p-4 rounded-2xl border border-border/70 bg-surface-2/30 space-y-2.5">
                      <div className="flex items-center justify-between">
                        <div className="flex items-center gap-2">
                          <span className="text-xs font-semibold text-fg">OpenAI API Key</span>
                          {settings?.openai_key_set ? (
                            <span className="flex items-center gap-1 rounded-full bg-emerald-500/20 px-2 py-0.5 text-[10px] font-medium text-emerald-300">
                              <Check className="size-2.5" /> Key Saved
                            </span>
                          ) : (
                            <span className="rounded-full bg-surface-3 px-2 py-0.5 text-[10px] text-muted">
                              Not Set
                            </span>
                          )}
                        </div>
                        <button
                          type="button"
                          disabled={testingProvider === "openai"}
                          onClick={() => handleTestProvider("openai")}
                          className="flex items-center gap-1.5 rounded-lg border border-border/80 bg-surface-3 px-2.5 py-1 text-[11px] font-medium text-fg hover:bg-surface-2 transition disabled:opacity-50"
                        >
                          {testingProvider === "openai" ? (
                            <Loader2 className="size-3 animate-spin text-violet-brand" />
                          ) : (
                            <Radio className="size-3 text-cyan-400" />
                          )}
                          Test Ping
                        </button>
                      </div>
                      <div className="relative">
                        <input
                          type={showOpenai ? "text" : "password"}
                          placeholder={settings?.openai_key_set ? "••••••••••••••••••••••••" : "sk-proj-..."}
                          value={openaiKey}
                          onChange={(e) => setOpenaiKey(e.target.value)}
                          className="w-full rounded-xl border border-border/80 bg-surface-1 px-3 py-2 pr-9 text-xs font-mono text-fg placeholder:text-muted/50 focus:border-violet-brand focus:outline-none"
                        />
                        <button
                          type="button"
                          onClick={() => setShowOpenai(!showOpenai)}
                          className="absolute right-2.5 top-1/2 -translate-y-1/2 text-muted hover:text-fg"
                        >
                          {showOpenai ? <EyeOff className="size-3.5" /> : <Eye className="size-3.5" />}
                        </button>
                      </div>
                    </div>

                    {/* Anthropic */}
                    <div className="p-4 rounded-2xl border border-border/70 bg-surface-2/30 space-y-2.5">
                      <div className="flex items-center justify-between">
                        <div className="flex items-center gap-2">
                          <span className="text-xs font-semibold text-fg">Anthropic Claude API Key</span>
                          {settings?.anthropic_key_set ? (
                            <span className="flex items-center gap-1 rounded-full bg-emerald-500/20 px-2 py-0.5 text-[10px] font-medium text-emerald-300">
                              <Check className="size-2.5" /> Key Saved
                            </span>
                          ) : (
                            <span className="rounded-full bg-surface-3 px-2 py-0.5 text-[10px] text-muted">
                              Not Set
                            </span>
                          )}
                        </div>
                        <button
                          type="button"
                          disabled={testingProvider === "anthropic"}
                          onClick={() => handleTestProvider("anthropic")}
                          className="flex items-center gap-1.5 rounded-lg border border-border/80 bg-surface-3 px-2.5 py-1 text-[11px] font-medium text-fg hover:bg-surface-2 transition disabled:opacity-50"
                        >
                          {testingProvider === "anthropic" ? (
                            <Loader2 className="size-3 animate-spin text-violet-brand" />
                          ) : (
                            <Radio className="size-3 text-cyan-400" />
                          )}
                          Test Ping
                        </button>
                      </div>
                      <div className="relative">
                        <input
                          type={showAnthropic ? "text" : "password"}
                          placeholder={settings?.anthropic_key_set ? "••••••••••••••••••••••••" : "sk-ant-..."}
                          value={anthropicKey}
                          onChange={(e) => setAnthropicKey(e.target.value)}
                          className="w-full rounded-xl border border-border/80 bg-surface-1 px-3 py-2 pr-9 text-xs font-mono text-fg placeholder:text-muted/50 focus:border-violet-brand focus:outline-none"
                        />
                        <button
                          type="button"
                          onClick={() => setShowAnthropic(!showAnthropic)}
                          className="absolute right-2.5 top-1/2 -translate-y-1/2 text-muted hover:text-fg"
                        >
                          {showAnthropic ? <EyeOff className="size-3.5" /> : <Eye className="size-3.5" />}
                        </button>
                      </div>
                    </div>

                    {/* Ollama Local */}
                    <div className="p-4 rounded-2xl border border-border/70 bg-surface-2/30 space-y-2.5">
                      <div className="flex items-center justify-between">
                        <div className="flex items-center gap-2">
                          <Server className="size-3.5 text-violet-400" />
                          <span className="text-xs font-semibold text-fg">Ollama Host URL</span>
                        </div>
                        <button
                          type="button"
                          disabled={testingProvider === "ollama"}
                          onClick={() => handleTestProvider("ollama")}
                          className="flex items-center gap-1.5 rounded-lg border border-border/80 bg-surface-3 px-2.5 py-1 text-[11px] font-medium text-fg hover:bg-surface-2 transition disabled:opacity-50"
                        >
                          {testingProvider === "ollama" ? (
                            <Loader2 className="size-3 animate-spin text-violet-brand" />
                          ) : (
                            <Radio className="size-3 text-cyan-400" />
                          )}
                          Test Ping
                        </button>
                      </div>
                      <input
                        type="text"
                        placeholder="http://localhost:11434"
                        value={ollamaHost}
                        onChange={(e) => setOllamaHost(e.target.value)}
                        className="w-full rounded-xl border border-border/80 bg-surface-1 px-3 py-2 text-xs font-mono text-fg placeholder:text-muted/50 focus:border-violet-brand focus:outline-none"
                      />
                      <p className="text-[10px] text-muted">
                        Requires Ollama running locally (<code className="font-mono text-violet-300">ollama serve</code>). Recommended models: <code className="font-mono text-violet-300">llama3.2</code>, <code className="font-mono text-violet-300">deepseek-r1</code>.
                      </p>
                    </div>

                    {/* Provider Test Result Toast */}
                    {testResult && (
                      <div
                        className={`flex items-start gap-2.5 rounded-xl border p-3.5 text-xs animate-in fade-in ${
                          testResult.ok
                            ? "border-emerald-500/30 bg-emerald-500/10 text-emerald-300"
                            : "border-red-500/30 bg-red-500/10 text-red-300"
                        }`}
                      >
                        {testResult.ok ? (
                          <CheckCircle2 className="size-4 shrink-0 mt-0.5 text-emerald-400" />
                        ) : (
                          <AlertCircle className="size-4 shrink-0 mt-0.5 text-red-400" />
                        )}
                        <div>
                          <p className="font-semibold capitalize">{testResult.provider} Test Result</p>
                          <p className="text-[11px] opacity-90">{testResult.message}</p>
                          {testResult.model && (
                            <p className="text-[10px] font-mono mt-1 text-emerald-400">
                              Active model: {testResult.model}
                            </p>
                          )}
                        </div>
                      </div>
                    )}
                  </div>
                </div>
              )}

              {/* TAB 2: Generation Defaults */}
              {activeTab === "defaults" && (
                <div className="space-y-6">
                  {/* Default Subtitle Preset */}
                  <div>
                    <label className="block text-xs font-semibold text-muted uppercase tracking-wider mb-2.5">
                      Default Kinetic Subtitle Style
                    </label>
                    <div className="grid grid-cols-2 gap-2.5">
                      {[
                        {
                          id: "hormozi",
                          title: "Hormozi Kinetic",
                          badge: "Yellow / Green Bold",
                          desc: "High-contrast dynamic words with viral retention cadence",
                        },
                        {
                          id: "mrbeast",
                          title: "MrBeast Punch",
                          badge: "Uppercase Impact",
                          desc: "Ultra-heavy typography with energetic rotation punch",
                        },
                        {
                          id: "cyber",
                          title: "Cyber Neon",
                          badge: "Neon Cyan Glow",
                          desc: "Futuristic sleek glow for tech, coding, and crypto clips",
                        },
                        {
                          id: "clean",
                          title: "Clean Minimal",
                          badge: "White Serif / Sans",
                          desc: "Subtle podcast elegance with smooth pill backdrop",
                        },
                      ].map((item) => {
                        const isSelected = subtitleStyle === item.id;
                        return (
                          <button
                            key={item.id}
                            type="button"
                            onClick={() => setSubtitleStyle(item.id)}
                            className={`flex flex-col items-start p-3.5 rounded-2xl border text-left transition ${
                              isSelected
                                ? "border-violet-brand bg-violet-brand/10 shadow-sm ring-1 ring-violet-brand"
                                : "border-border/70 bg-surface-2/40 hover:bg-surface-2 hover:border-border"
                            }`}
                          >
                            <div className="flex items-center justify-between w-full mb-1">
                              <span
                                className={`text-xs font-semibold ${
                                  isSelected ? "text-violet-200" : "text-fg"
                                }`}
                              >
                                {item.title}
                              </span>
                              <span className="text-[9px] font-mono px-1.5 py-0.5 rounded bg-surface-3 text-muted">
                                {item.badge}
                              </span>
                            </div>
                            <p className="text-[11px] text-muted line-clamp-2">{item.desc}</p>
                          </button>
                        );
                      })}
                    </div>
                  </div>

                  {/* Auto-Zoom Punch In */}
                  <div className="p-4 rounded-2xl border border-border/70 bg-surface-2/30 flex items-center justify-between gap-4">
                    <div className="space-y-0.5">
                      <div className="flex items-center gap-2">
                        <Flame className="size-4 text-amber-400" />
                        <span className="text-xs font-semibold text-fg">
                          Retention Auto-Zoom Punch-In
                        </span>
                      </div>
                      <p className="text-[11px] text-muted">
                        Automatically applies 1.08x zoom punch-ins at key hook sentences to eliminate retention drop-off
                      </p>
                    </div>
                    <label className="relative inline-flex items-center cursor-pointer shrink-0">
                      <input
                        type="checkbox"
                        checked={autoZoom}
                        onChange={(e) => setAutoZoom(e.target.checked)}
                        className="sr-only peer"
                      />
                      <div className="w-11 h-6 bg-surface-3 peer-focus:outline-none rounded-full peer peer-checked:after:translate-x-full peer-checked:after:border-white after:content-[''] after:absolute after:top-[2px] after:left-[2px] after:bg-white after:border-gray-300 after:border after:rounded-full after:h-5 after:w-5 after:transition-all peer-checked:bg-violet-brand"></div>
                    </label>
                  </div>

                  {/* Background Music Mood */}
                  <div>
                    <label className="block text-xs font-semibold text-muted uppercase tracking-wider mb-2.5">
                      Default Audio Bed / Music Mood
                    </label>
                    <div className="grid grid-cols-2 sm:grid-cols-4 gap-2">
                      {[
                        { id: null, label: "None (Raw Voice)" },
                        { id: "chill", label: "Chill Ambient" },
                        { id: "energetic", label: "Energetic Beat" },
                        { id: "suspense", label: "Suspense Pulse" },
                      ].map((item) => {
                        const active = musicMood === item.id;
                        return (
                          <button
                            key={String(item.id)}
                            type="button"
                            onClick={() => setMusicMood(item.id)}
                            className={`px-3 py-2.5 rounded-xl border text-xs font-medium text-center transition ${
                              active
                                ? "border-violet-brand bg-violet-brand/20 text-violet-200 ring-1 ring-violet-brand"
                                : "border-border/70 bg-surface-2/40 text-muted hover:text-fg hover:bg-surface-2"
                            }`}
                          >
                            {item.label}
                          </button>
                        );
                      })}
                    </div>
                  </div>
                </div>
              )}

              {/* TAB 3: Hardware & Acceleration */}
              {activeTab === "hardware" && (
                <div className="space-y-4">
                  {loadingSystem ? (
                    <div className="flex items-center justify-center py-12 gap-2 text-muted">
                      <Loader2 className="size-4 animate-spin text-violet-brand" />
                      <span className="text-xs">Querying GPU hardware...</span>
                    </div>
                  ) : (
                    <>
                      {/* GPU Status Card */}
                      <div className="p-4 rounded-2xl border border-border/70 bg-surface-2/30 space-y-3">
                        <div className="flex items-center gap-2">
                          <Cpu className="size-4 text-violet-400" />
                          <h3 className="text-xs font-semibold text-fg">Detected GPUs & VRAM</h3>
                        </div>

                        {systemInfo?.gpus && systemInfo.gpus.length > 0 ? (
                          <div className="space-y-2">
                            {systemInfo.gpus.map((gpu, i) => (
                              <div
                                key={i}
                                className="flex items-center justify-between rounded-xl bg-surface-1 p-3 border border-border/60"
                              >
                                <div>
                                  <p className="text-xs font-semibold text-fg">{gpu.name}</p>
                                  <p className="text-[10px] text-muted">Driver: {gpu.driver || "N/A"}</p>
                                </div>
                                <span className="font-mono text-xs px-2.5 py-1 rounded-lg bg-violet-brand/20 text-violet-300 font-semibold">
                                  {Math.round(gpu.memory_total_mb / 1024)} GB VRAM
                                </span>
                              </div>
                            ))}
                          </div>
                        ) : (
                          <div className="rounded-xl bg-surface-1 p-3 text-xs text-muted">
                            No dedicated CUDA GPU detected. System is running in CPU mode.
                          </div>
                        )}
                      </div>

                      {/* Video Encoder Card */}
                      <div className="p-4 rounded-2xl border border-border/70 bg-surface-2/30 space-y-3">
                        <div className="flex items-center gap-2">
                          <Zap className="size-4 text-amber-400" />
                          <h3 className="text-xs font-semibold text-fg">Render Engine & Codecs</h3>
                        </div>
                        <div className="grid grid-cols-2 gap-3">
                          <div className="rounded-xl bg-surface-1 p-3 border border-border/60 flex items-center justify-between">
                            <span className="text-xs text-fg">FFmpeg Engine</span>
                            {systemInfo?.ffmpeg ? (
                              <span className="flex items-center gap-1 text-[11px] font-semibold text-emerald-400">
                                <Check className="size-3" /> Ready
                              </span>
                            ) : (
                              <span className="text-[11px] font-semibold text-red-400">Missing</span>
                            )}
                          </div>
                          <div className="rounded-xl bg-surface-1 p-3 border border-border/60 flex items-center justify-between">
                            <span className="text-xs text-fg">NVENC Hardware Acceleration</span>
                            {systemInfo?.nvenc ? (
                              <span className="flex items-center gap-1 text-[11px] font-semibold text-emerald-400">
                                <Sparkles className="size-3" /> Enabled (Fast)
                              </span>
                            ) : (
                              <span className="text-[11px] font-semibold text-muted">Software (CPU)</span>
                            )}
                          </div>
                        </div>
                      </div>
                    </>
                  )}
                </div>
              )}
            </>
          )}
        </div>

        {/* Footer */}
        <div className="flex items-center justify-between border-t border-border/70 px-6 py-4 bg-surface-2/40">
          <button
            type="button"
            disabled={saving}
            onClick={onClose}
            className="rounded-full px-4 py-2 text-xs font-medium text-muted hover:text-fg hover:bg-surface-3 transition"
          >
            Cancel
          </button>
          <button
            type="button"
            disabled={saving || loading}
            onClick={handleSave}
            className="flex items-center gap-2 rounded-full bg-violet-brand px-6 py-2 text-xs font-semibold text-white shadow-lg shadow-violet-brand/25 transition hover:brightness-110 disabled:opacity-50"
          >
            {saving ? (
              <>
                <Loader2 className="size-3.5 animate-spin" />
                Saving...
              </>
            ) : saveSuccess ? (
              <>
                <Check className="size-3.5" />
                Saved!
              </>
            ) : (
              "Save Settings"
            )}
          </button>
        </div>
      </div>
    </div>
  );
}
