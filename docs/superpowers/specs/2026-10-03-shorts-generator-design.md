# ClipForge — Design Spec

**Date:** 2026-10-03
**Status:** Approved in brainstorming, pending written-spec review
**Reference products/code:** Opus Clip (product), mutonby/openshorts (MIT, primary code reference), Anil-matcha/AI-Youtube-Shorts-Generator (MIT, scoring prompt reference), supoclip & hotclip (AGPL — design ideas only, no code copied).

---

## 1. Goal

A personal, locally-run, Opus-Clip-class tool: paste a YouTube URL (or upload a video) → after a few minutes receive 5–15 ranked, ready-to-post 9:16 shorts that are well framed, have animated captions and a hook title, come with an SEO pack (post caption, hashtags, titles), and can be edited in a modern browser UI before export.

### Success criteria
- A 20-minute source video produces ranked clips end-to-end with no manual steps.
- Processing time (excluding LLM latency) ≤ ~3 min per 10 min of source on the target machine.
- Clip boundaries never cut mid-word; every clip starts on a hook and ends on a payoff/sentence end.
- Speaker stays in frame on talking-head and podcast content without visible jitter.
- Every clip has a virality score (0–100) with a reason, and a complete SEO pack.
- Editor changes (trim, caption text, style, layout) re-render a clip in seconds.

### Constraints
- **Target machine:** Windows 11, Python 3.13, Node 22, ffmpeg 8 (full build), NVIDIA RTX 3050 Laptop **4 GB VRAM**.
- **Single user, local.** No auth, billing, or multi-tenant concerns.
- **LLM via user-supplied cloud API keys** (pluggable), Ollama as local fallback.
- **Any input language** (Whisper auto-detect); outputs in source language with optional translation.
- **All content types:** talking-head/educational, podcasts/interviews, gaming/screen recordings, vlogs/mixed.

### Non-goals (v1)
- Direct publishing/scheduling to YouTube/TikTok/Instagram.
- Multi-user accounts, cloud hosting, payments.
- Remotion/HTML-based premium caption renderer (interface reserved, not built).
- Training or fine-tuning any model.

---

## 2. Architecture

```
┌──────────── Web UI (React 19 + Vite + TS) ─────────┐
│ Home/Upload → Processing → Clip Gallery →           │
│ Clip Editor → SEO Pack → Export · Settings          │
└──────────────┬──────────────────────▲───────────────┘
        REST + │ WebSocket (progress, logs, partial results)
┌──────────────▼──────────────────────┴───────────────┐
│ FastAPI server ── SQLite (jobs, clips, settings)    │
│      │                                              │
│ Job worker: in-process asyncio queue.               │
│   GPU stages serialized (one at a time),            │
│   CPU / LLM / network stages run concurrently.      │
│      │                                              │
│ Pipeline stages (checkpointed + cached per video):  │
│ ingest → transcribe → classify → diarize →          │
│ analyze → shots → reframe → captions → polish →     │
│ render → seo                                        │
└─────────────────────────────────────────────────────┘
workspace/<video_id>/
  source.mp4, audio.wav, meta.json
  transcript.json, diarization.json, analysis.json
  clips/<clip_id>/{clip.json, camera.json, captions.ass, seo.json, thumb.jpg}
  renders/<clip_id>.mp4
```

### Repository layout
```
backend/
  app/
    main.py              FastAPI app, routers, websocket
    config.py            settings (.env + DB-backed user settings)
    db.py, models.py     SQLModel tables: Project, Job, Clip, Setting
    jobs/queue.py        asyncio job queue, GPU semaphore, progress events
    pipeline/
      runner.py          stage orchestration, checkpoint/resume
      ingest.py          yt-dlp / upload, audio extraction, hashing
      transcribe.py      faster-whisper wrapper
      diarize.py         pyannote wrapper
      classify.py        content-type classification (LLM)
      analyze.py         moment detection, alignment, dedupe, rerank, scoring
      align.py           quote → word-timestamp mapping, edge snapping
      audio_signals.py   RMS energy, laughter/peak detection
      shots.py           PySceneDetect within clip ranges
      reframe/
        detect.py        face detection (mediapipe tasks / YOLO-face onnx)
        track.py         ByteTrack-style ID association
        speaker.py       active-speaker fusion
        camera.py        deadzone + spring smoothing, keyframes
        layouts.py       track / active-speaker / split / gaming / fit-blur
      captions/
        base.py          CaptionRenderer interface
        ass.py           ASS generation (word pop, karaoke, keywords, emoji)
        presets.py       style presets
        hook.py          hook title card
      polish/
        fillers.py       filler & silence removal
        broll.py         Pexels/Pixabay search + overlay plan
        music.py         music selection + sidechain ducking
        zoom.py          emphasis punch-ins
        thumbnail.py     best-frame selection + text overlay
        translate.py     caption translation
        dub.py           ElevenLabs / Edge-TTS dubbing
      render.py          ffmpeg filtergraph builder, NVENC encode
      seo.py             SEO pack generation
    llm/
      base.py            LLMProvider interface (structured JSON output)
      anthropic.py, gemini.py, openai.py, ollama.py
      prompts/           versioned prompt templates
    api/                 routers: projects, jobs, clips, settings, files
  tests/
  pyproject.toml
frontend/
  src/
    routes/              home, processing, gallery, editor, export, settings
    components/          ui primitives, motion components, caption preview
    features/editor/     timeline, transcript editor, panels, zustand store
    lib/api.ts, lib/ws.ts
  package.json
assets/fonts, assets/music, assets/emoji
scripts/setup.ps1        venv, CUDA DLL deps, model downloads, npm install
```

### Key technology choices
| Concern | Choice |
|---|---|
| Backend | Python 3.13, FastAPI, Pydantic v2, SQLModel + SQLite |
| Download | yt-dlp (library), Node as JS runtime, optional cookies file |
| ASR | faster-whisper `large-v3-turbo`, fp16 (int8_float16 fallback), word timestamps, VAD |
| Diarization | pyannote.audio 4.x `speaker-diarization-community-1` (HF token), fed in-memory waveforms |
| Scene detection | PySceneDetect `AdaptiveDetector`, downscaled, only inside clip ranges |
| Face detection | mediapipe Tasks `FaceDetector` (CPU) primary; YOLO-face on onnxruntime-gpu fallback |
| Render | ffmpeg 8, `h264_nvenc -preset p5 -cq 21`, AAC 192k, 1080×1920 30/60fps |
| Captions | ASS via libass inside the same encode |
| LLM | Pluggable: Claude, Gemini, OpenAI, Ollama |
| Frontend | React 19, Vite, TypeScript, Tailwind v4, Motion, GSAP, Lenis, React Three Fiber (background shader), TanStack Query, Zustand |
| Tests | pytest, Vitest, Playwright |

WhisperX is **not** used (pins old torch). Legacy `mediapipe.solutions` API is **not** used (removed).

---

## 3. Pipeline

### 3.1 Ingest
- Input: YouTube URL or uploaded file (mp4/mkv/mov/webm).
- yt-dlp format `bv*[height<=1080]+ba/b`, merged to mp4. Cookies file path configurable for age-gated/members content.
- Extract mono 16 kHz WAV for ASR/diarization.
- `video_id` = SHA-256 of source file (first 64 MB + size + duration) — identical inputs reuse all cached stages.
- Record metadata: duration, fps, resolution, title, channel, description (fed to the LLM as context).

### 3.2 Transcribe
- faster-whisper `large-v3-turbo`, `word_timestamps=True`, `vad_filter=True`, auto language.
- Output `transcript.json`: language, segments, words `{text, start, end, prob}`, sentence boundaries.
- Fallbacks: CUDA OOM → `int8_float16` → CPU `int8`.

### 3.3 Classify
- One cheap LLM call on title + description + transcript sample → `{content_type, speaker_count_estimate, topics, tone}`.
- `content_type ∈ {podcast, talking_head, gaming, screen_tutorial, vlog, other}`. Drives layout defaults, scoring weights, whether diarization runs.

### 3.4 Diarize
- Runs if `speaker_count_estimate ≥ 2` or content_type = podcast. Assigns speaker labels to words/sentences.

### 3.5 Analyze (moment detection)
1. Chunk transcript into ~12-minute windows with 1-minute overlap; sentences numbered and speaker-tagged.
2. Per chunk, LLM returns strict JSON candidates:
   ```
   { start_quote, end_quote, hook_type, payoff_summary, self_contained: bool,
     scores: {hook, emotion, novelty, value, shareability, loop} (0–10),
     title, hook_text, why_viral, keywords[], emoji_suggestions[] }
   ```
   `hook_type ∈ {question, bold_claim, number, conflict, story, contrarian, reveal, humor}`.
3. **Alignment (in code):** fuzzy-match `start_quote`/`end_quote` to word sequence (normalized text, rapidfuzz). LLM timestamps are never trusted. Unmatched candidates are discarded.
4. **Edge snapping:** start to sentence start, end to sentence end; extend into silence ≥150 ms; enforce min/max duration (default 30–60 s, configurable 15–90 s).
5. **Audio signals:** RMS energy peaks and laughter/cheer detection add a bonus (weighted higher for gaming/vlog).
6. **Dedupe:** temporal IoU > 0.5 → keep higher score.
7. **Rerank:** top 20 candidates sent together to LLM for comparative ranking.
8. **Virality score (0–100):** weighted sub-scores (weights per content_type) + audio bonus + rerank position, normalized. Stored with `why_viral`.
9. Output: top N (default 10, configurable 3–30) clips to DB.

### 3.6 Shots
- PySceneDetect within each clip range (with 2 s padding) → shot boundaries.

### 3.7 Reframe
- Per shot: face detection every 2nd frame on downscaled frames; ByteTrack-style association → face tracks.
- Layout auto-selection per shot:
  | Layout | Trigger | Behavior |
  |---|---|---|
  | `track` | 1 dominant face | crop follows face; deadzone 12% width; critically-damped spring smoothing |
  | `active_speaker` | ≥2 faces, diarization available | fuse diarization turn + mouth-motion + audio energy; cut to speaker; min hold 1.5 s |
  | `split` | 2 faces persistently visible & both speak | two face crops stacked; captions on seam |
  | `gaming` | small static face region + large dynamic region, or content_type gaming | facecam top 35%, gameplay bottom 65% |
  | `fit_blur` | no faces / wide shot | full frame scaled-to-fit over blurred scaled background |
- Hard camera cut at shot boundaries; never smooth across a cut.
- Output `camera.json`: per-shot layout + keyframes `{t, x, y, w, h}` — editable in the UI.

### 3.8 Captions
- `CaptionRenderer` interface: `render(clip, words, style) → overlay artifact`. v1 implementation: `AssCaptionRenderer`.
- Word grouping: 2–4 words per line (configurable), break on punctuation/pauses > 300 ms.
- Animations: active-word highlight color, scale pop (`\t`), karaoke fill (`\kf`), fade in/out.
- LLM-flagged keywords get emphasis color; emoji (≤1 per line) via Noto Color Emoji.
- Safe area: captions positioned above bottom 20% and below top 12% (platform UI zones).
- Presets: Hormozi, MrBeast, Karaoke Glow, Minimal Clean, Neon, Boxed Highlight, Typewriter, Subtle Podcast. Each = serializable `CaptionStyle` (font, size, colors, stroke, shadow, box, position, case, animation, words_per_line).
- Hook title card: first 3 s, animated in/out, from `hook_text`.
- Bundled fonts: Montserrat, Bebas Neue, Anton, Poppins, Inter, Noto Sans (+ script variants: Devanagari, Arabic, CJK, etc.).

### 3.9 Polish (each toggleable per clip; defaults in settings)
- **Filler/silence removal:** filler list per language (Whisper tokens + LLM-confirmed), silences > 400 ms trimmed to 150 ms; produces a cut list; 20 ms audio crossfades; captions re-timed.
- **Auto-zoom:** 1.0→1.08 punch-ins on LLM-emphasized moments, max one per 6 s.
- **B-roll:** LLM picks ≤3 moments + search keywords; Pexels/Pixabay API; full-frame cutaway or PiP, 1.5–3 s; captions stay on top.
- **Music:** bundled royalty-free library tagged by mood + user folder; LLM picks mood; sidechain ducking (`sidechaincompress`) under speech, −18 dB bed.
- **Thumbnail:** sample frames, score by face size/sharpness/expression (landmark-based), overlay hook text.
- **Translation:** LLM translates caption segments to target language preserving segment timing.
- **Dubbing:** ElevenLabs (if key) else Edge-TTS; per-segment TTS time-stretched (atempo, bounded 0.8–1.25) to fit original timing; original voice ducked or replaced.

### 3.10 Render
- One ffmpeg invocation per clip: input seek (`-ss` before `-i`), cut list (`select`/`aselect` or concat of segments), crop expression driven by `sendcmd` from camera keyframes (or split/gaming filtergraph), scale to 1080×1920, B-roll overlays, zoom, `subtitles=` (ASS), music mix, NVENC encode.
- Optional `-hwaccel cuda` decode.
- Up to 3 clips rendered concurrently (NVENC session limit headroom).
- Preview renders: 540×960 fast preset for the editor; final: 1080×1920.

### 3.11 SEO pack
Per clip, one LLM call (source language, or target language if translated):
```
{ titles: [3], youtube: {title, description, tags[]},
  tiktok: {caption}, instagram: {caption},
  hashtags: {broad[], niche[], trending_style[]}  (15–30 total, deduped, no spaces),
  keywords[], cta }
```
- Validation: hashtag format `^#[\p{L}\p{N}_]+$`, length limits per platform (YouTube title ≤100 chars, TikTok caption ≤2200, Instagram ≤2200 & ≤30 hashtags).
- UI: one-click copy per field and "copy all for platform"; export as `seo.txt` + `seo.json` beside each MP4.
- Note: "trending" hashtags are LLM-suggested, not fetched from live platform data (no official API); labeled accordingly.

---

## 4. LLM provider layer
- `LLMProvider.generate_json(prompt, schema: type[BaseModel], temperature) → BaseModel`.
- Implementations: Anthropic (Claude), Google Gemini, OpenAI, Ollama (OpenAI-compatible endpoint).
- Structured output via provider-native JSON/schema mode where available; Pydantic validation; up to 2 repair retries with the validation error fed back; then fallback to the next configured provider.
- Per-task model selection in settings (e.g. cheap model for classify, strong model for analyze/rerank).
- Responses cached by `(prompt_version, input_hash, model)`.
- Prompts are versioned files under `llm/prompts/`.

---

## 5. API
REST (JSON) + one WebSocket per job.
- `POST /api/projects` (url or multipart upload, options) → project + job
- `GET /api/projects`, `GET /api/projects/{id}`, `DELETE /api/projects/{id}`
- `GET /api/projects/{id}/clips`
- `GET/PATCH /api/clips/{id}` (trim, words edits, style, layout/camera, polish toggles)
- `POST /api/clips/{id}/render?quality=preview|final`
- `GET /api/clips/{id}/seo`, `POST /api/clips/{id}/seo/regenerate`
- `POST /api/projects/{id}/export` (selected clip ids) → zip
- `GET/PUT /api/settings`; `POST /api/settings/test-provider`
- `GET /api/jobs/{id}`, `POST /api/jobs/{id}/retry` (resume from last checkpoint), `POST /api/jobs/{id}/cancel`
- `WS /api/jobs/{id}/events` → `{stage, status, progress, eta, message, partial}` (partial transcript lines, clip cards as found)
- Static: `/files/<video_id>/...` for sources, previews, thumbnails.

---

## 6. Frontend

### Visual direction
- Dark-first: near-black canvas, electric violet→cyan accent gradient, subtle grain; light theme supported.
- Display font: Clash Display / General Sans; UI font: Inter.
- Animated WebGL shader background (React Three Fiber) on Home; disabled on low-power/reduced-motion.

### Screens
1. **Home / New project:** hero URL input + magnetic drop zone with glow; options drawer (clip count, length range, language/translate, style preset, polish toggles); recent project cards.
2. **Processing:** animated pipeline "constellation" — nodes per stage lighting up with progress %, ETA, log ticker; transcript streams in live; clip cards fade in with scores as found.
3. **Clip gallery:** masonry 9:16 cards, muted autoplay on hover, animated virality score ring, "why viral" tooltip, hook type tag; sort (score, time, length) and filter; multi-select batch actions.
4. **Editor:** video preview with live HTML caption overlay; timeline (waveform, shots, transcript words, B-roll/music lanes); trim handles snapping to words; transcript text editing (edit/delete words → cuts); panels: Captions, Hook, Layout/Camera, B-roll, Music, Polish, SEO; undo/redo; preview & final render.
5. **Export:** per-clip progress animations; download single MP4s or ZIP (MP4 + seo.txt + seo.json + thumb.jpg).
6. **Settings:** API keys (Anthropic, Gemini, OpenAI, Ollama URL, HF token, Pexels, Pixabay, ElevenLabs), per-task models, defaults, platform preferences, yt-dlp cookies path, GPU info.

### Motion system
- Shared-element (layoutId) transitions card → editor; staggered reveals; spring micro-interactions; skeleton shimmer loaders; Lenis smooth scroll; GSAP for hero sequences.
- `prefers-reduced-motion` respected globally.

---

## 7. Error handling
- Each stage writes its artifact atomically then marks checkpoint; `retry` resumes from the first incomplete stage.
- Stage failures surface to UI with human-readable cause + suggested fix (e.g. yt-dlp "Sign in to confirm" → cookies setting; "update yt-dlp").
- GPU OOM → automatic precision/CPU fallback, logged.
- LLM: schema-repair retries → provider fallback → if all fail, stage fails with clear message (keys/quota).
- Missing optional keys (Pexels, ElevenLabs, HF) disable the dependent feature with an inline notice rather than failing the job.
- Cancel stops subprocesses (ffmpeg) and leaves cached artifacts intact.

---

## 8. Testing
- **pytest unit:** quote alignment (incl. punctuation/case/number variants, multilingual), edge snapping, IoU dedupe, scoring, camera smoothing & deadzone, layout selection, ASS generation (golden files), filler cut list & caption re-timing, SEO validation, LLM provider JSON repair (mocked).
- **pytest integration:** golden ~2-minute sample video through full pipeline with a mocked LLM (fixture responses) → asserts clips exist, durations valid, video 1080×1920, captions burned (frame probe).
- **Vitest:** editor store (trim, word edits, undo/redo), caption preview style mapping.
- **Playwright smoke:** create project from local sample → processing → gallery → editor trim → export.

---

## 9. Delivery phases
Each phase ends in a working, demoable app.

1. **Foundation:** `setup.ps1` (venv, CUDA DLLs, models), FastAPI skeleton, DB, job queue + WebSocket, ingest + transcribe; frontend shell, design system, Home + Processing screens.
2. **Clip engine:** LLM provider layer, classify, diarize, analyze (align, dedupe, rerank, score), shots, reframe (all 5 layouts), ASS captions + presets + hook card, NVENC render, Gallery screen.
3. **SEO pack:** generation, validation, UI panel, export with SEO files.
4. **Editor:** timeline, trim, transcript editing, caption/layout/camera panels, preview/final re-render, undo/redo.
5. **Polish:** filler/silence removal, auto-zoom, B-roll, music ducking, thumbnails.
6. **Global & performance:** translation, dubbing, performance tuning, Playwright suite.

## 10. Future (out of scope for v1)
- `RemotionCaptionRenderer` premium animated caption templates.
- LR-ASD neural active-speaker model.
- Vision-LLM contact-sheet scoring signal.
- Direct upload/scheduling to platforms.
