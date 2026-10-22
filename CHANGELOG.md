# Changelog

All notable changes to ClipForge. Versions follow [Semantic Versioning](https://semver.org/).
To update, run `./scripts/update.ps1` (see the README).

## [1.0.1] - 2026-10-23

### Added
- **Pixabay stock B-roll.** Pexels has paused new API keys, so B-roll can now use a free Pixabay key instead (Settings → AI Brain). When both keys are set, Pexels is tried first and Pixabay covers any miss. The Pixabay key is never written to logs.

## [1.0.0] - 2026-10-23

The first complete release. The whole pipeline (link → transcript → ranked clips → 9:16 renders → SEO → export) has been verified end-to-end on real videos.

### Added
- **Clip engine:** AI moment detection across the *whole* video (chunked, parallel, with overlap and de-duplication), 0-100 virality score with hook / emotion / novelty / value / shareability / loop sub-scores.
- **9:16 render engine:** NVENC encoding with automatic CPU fallback, thumbnails, Fit+Blur, Split Screen and Gaming Cam layouts.
- **Speaker Track face tracking** (new default layout): MediaPipe face detection, shot-cut detection, a camera path that sticks to the speaker with deadzone and easing, and a per-frame crop. Falls back to Fit+Blur when no face is found.
- **Animated captions:** word-by-word karaoke in 4 presets, plus hook title badges.
- **SEO pack:** titles, descriptions and hashtags for YouTube Shorts, TikTok and Reels.
- **Studio:** trim editor, hook text, 1.08x auto-zoom punch-ins, music beds, AI B-roll, filler-word and silence jump-cuts, multilingual dubbing (Edge-TTS).
- **Export:** one-click ZIP with MP4s, subtitles, thumbnails and `seo.txt`.
- **Settings hub:** Gemini, Claude, OpenAI or Ollama keys stored locally, with live connection tests.
- **Storage cleanup:** per-project disk usage, delete a clip, delete a project. The confirmation shows how much space will really be freed, and a shared source download is kept until no project needs it.
- **Updates:** an in-app "new version available" notice (checks GitHub tags, cached, silent when offline) and `scripts/update.ps1`.

### Fixed
- Default renders crashed on the audio mapping.
- API keys could appear in logs through request URLs. Keys are now sent in headers, and HTTP client logging is quieted.
- Scoring only looked at the first minutes of long videos, and sometimes made up heuristic scores when the AI failed. It now reports the failure honestly.
- Jump-cut clips with music had the wrong length.
- Auto-zoom had no visible effect.
- Changing the caption style reset the layout, dubbing and filler options.
- Dubbing failures produced a buzzing tone instead of an error.
- Exported `seo.txt` had an empty description and bare hashtags.

## [0.1.0] - 2026-10-04

### Added
- Phase 1 foundation: setup script, FastAPI + job queue, YouTube download and uploads, GPU transcription with faster-whisper, live processing UI.

[1.0.1]: https://github.com/Lunar0769/ClipForge/compare/v1.0.0...v1.0.1
[1.0.0]: https://github.com/Lunar0769/ClipForge/compare/v0.1.0...v1.0.0
[0.1.0]: https://github.com/Lunar0769/ClipForge/releases/tag/v0.1.0
