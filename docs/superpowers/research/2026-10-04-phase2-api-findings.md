# Phase 2 API check (scratch uv project, py3.13, Windows 11, ffmpeg 8.0.1 gyan full)

## Resolution (no conflicts)
google-genai 2.28.0, openai 3.24.0, rapidfuzz 3.14.6, scenedetect 0.7.1, mediapipe 1.0.1, numpy 2.5.3,
pyannote.audio 4.0.7, faster-whisper 1.2.1, ctranslate2 4.8.2, av 16.1.0 (av>=14,<17 OK), torch 2.14.1, torchaudio 2.11.0,
torchcodec 0.17.0, opencv-python 5.0.0.93 (from scenedetect) AND opencv-contrib-python 5.0.0.93 (from mediapipe), scikit-learn 1.9.1, onnxruntime 1.30.0.
- ctranslate2 does not depend on torch; no clash with pyannote's torch. numpy 2.5.3 satisfied everything.
- scenedetect 0.7.1 has NO `opencv-headless` extra (uv warns). It hard-depends on `opencv-python`. mediapipe hard-depends on
  `opencv-contrib-python` (GUI build). Both get installed (same cv2 namespace; works, duplicates).
- torch on PyPI for Windows = CPU only (2.14.1+cpu, cuda None). CUDA needs an explicit index. cu128 index only has torch<=2.11 / torchaudio 2.9; cu126 and cu130 have torch 2.14.1.
- GOTCHA: a venv at a >260-char path broke an sklearn .pyd with a misleading ModuleNotFoundError. Avoid very deep venv paths.
- pyannote community-1 is gated="auto" on HF (accept terms + HF token). No token here: pipeline NOT run end-to-end. Verified offline: signatures, Audio() accepts waveform dict, TORCHCODEC_AVAILABLE=True, Annotation iteration.
- Speed (pyannote-audio README, 2025-09): community-1 = 31 s (AMI ~1h files) to 37 s (DIHARD) per hour of audio on an H100. No CPU benchmark published (CPU much slower, unverified). Use cuda (small models, 4 GB fine), fall back to CPU.

## CUDA torch in pyproject (VERIFIED: torch 2.14.1+cu126, torchaudio 2.11.0+cu126, torchcodec 0.17.0+cu126, torch.cuda.is_available() True on RTX 3050)
torch/torchaudio/torchcodec MUST be listed as direct dependencies (tool.uv.sources only applies to direct deps).
It pulls nvidia-cublas-cu12 12.6.4.1 / nvidia-cudnn-cu12 9.10.2.21, which satisfy the repo pins (>=12.4 / >=9,<10).
```toml
[project]
dependencies = [
    # ... existing ...
    "torch", "torchaudio", "torchcodec",
]

[tool.uv.sources]
torch = { index = "pytorch-cu126" }
torchaudio = { index = "pytorch-cu126" }
torchcodec = { index = "pytorch-cu126" }

[[tool.uv.index]]
name = "pytorch-cu126"
url = "https://download.pytorch.org/whl/cu126"
explicit = true
```

## 1. google-genai
```python
from pydantic import BaseModel
from google import genai
from google.genai import types, errors
class Clip(BaseModel):
    title: str; start_quote: str
client = genai.Client(api_key=KEY)
resp = client.models.generate_content(
    model="gemini-2.5-flash", contents=prompt,
    config=types.GenerateContentConfig(
        temperature=0.3, system_instruction=sys,
        response_mime_type="application/json", response_schema=list[Clip],
        thinking_config=types.ThinkingConfig(thinking_budget=0),
        http_options=types.HttpOptions(timeout=120_000)))     # ms
text = resp.text            # JSON string
clips = resp.parsed         # list[Clip] when schema is pydantic
```
Errors: `errors.APIError` (.code int, .status str, .message) -> `errors.ClientError` (4xx) / `errors.ServerError` (5xx).
429 = ClientError code==429 status "RESOURCE_EXHAUSTED". Bad API key = ClientError code **400** "API key not valid" (INVALID_ARGUMENT, verified live).
No RateLimitError class: branch on `e.code`.

## 2. openai 3.24
`client.chat.completions.parse` exists (also `client.beta.chat.completions.parse`, `client.responses.parse`).
```python
from openai import OpenAI
c = OpenAI(api_key=KEY)       # Ollama: OpenAI(base_url="http://localhost:11434/v1", api_key="ollama")
r = c.chat.completions.parse(model="gpt-4o-mini", messages=[...], response_format=Clip, temperature=0.2)
msg = r.choices[0].message; clip = msg.parsed; refusal = msg.refusal
```
Ollama JSON mode (request shape verified against a local mock server; real Ollama not tested):
```python
c = OpenAI(base_url="http://localhost:11434/v1", api_key="ollama")
r = c.chat.completions.create(model=..., messages=..., response_format={"type": "json_object"}, temperature=0)
clip = Clip.model_validate_json(r.choices[0].message.content)
```
`parse(response_format=Clip)` sends response_format type json_schema (strict), which Ollama supports.
Exceptions: openai.RateLimitError, AuthenticationError, APIConnectionError, APITimeoutError, BadRequestError, APIStatusError (.status_code),
LengthFinishReasonError, ContentFilterFinishReasonError (raised by parse()).

## 3. rapidfuzz: quote -> word indices (verified)
Normalize (lowercase, strip non-alnum), join tokens with " ", record the char offset of each token, then:
```python
import bisect
from rapidfuzz import fuzz
norm = lambda w: "".join(ch for ch in w.lower() if ch.isalnum())
toks = [norm(w) for w in words]; q = [norm(w) for w in quote.split()]
text = " ".join(toks); offs = []; p = 0
for t in toks: offs.append(p); p += len(t) + 1
a = fuzz.partial_ratio_alignment(" ".join(q), text)   # ScoreAlignment(score, src_start, src_end, dest_start, dest_end)
s = bisect.bisect_right(offs, a.dest_start) - 1
e = bisect.bisect_left(offs, a.dest_end) - 1          # inclusive word range words[s:e+1]
```
Test: "Align a quote, to a long transcript!" -> words[12:19], score 100. Precise alternative:
slide a window of len(q) tokens with `rapidfuzz.distance.Indel.normalized_similarity(q, toks[i:i+n])` (accepts lists of str), argmax.
Reject score < ~80; restrict the search to a window near the LLM-claimed time.

## 4. scenedetect 0.7.1 (verified, 3-scene clip)
```python
from scenedetect import open_video, SceneManager, AdaptiveDetector
def scenes(path, start_s, end_s, width=320):
    v = open_video(path)
    sm = SceneManager(); sm.add_detector(AdaptiveDetector(adaptive_threshold=3.0, min_scene_len=10))
    sm.auto_downscale = False; sm.downscale = max(1, v.frame_size[0] // width)
    v.seek(float(start_s))                       # FLOAT = seconds; INT = FRAMES
    sm.detect_scenes(v, end_time=float(end_s), show_progress=False)
    return [(s.seconds, e.seconds) for s, e in sm.get_scene_list(start_in_scene=True)]
```
Gotchas: ints are frame numbers (end_time=14 gave 0.56 s). `get_seconds()` deprecated -> `.seconds`. auto_downscale=True (default) ignores `downscale`.
One-liner: `detect(path, AdaptiveDetector(), start_time=3.0, end_time=11.0)`. Range 3..11 gave [(3,6),(6,10),(10,11)] (absolute times).

## 5. mediapipe 1.0.1 FaceDetector (ran on Windows CPU, py3.13: OK)
Short range: https://storage.googleapis.com/mediapipe-models/face_detector/blaze_face_short_range/float16/latest/blaze_face_short_range.tflite (230 KB, official)
Full range:  https://storage.googleapis.com/mediapipe-models/face_detector/blaze_face_full_range/float16/latest/blaze_face_full_range.tflite (1.08 MB, works; not in the official table). full_range_sparse = 404.
`mp.solutions` is gone in 1.0.1; Tasks only.
```python
import cv2, numpy as np, mediapipe as mp
from mediapipe.tasks import python as mpt
from mediapipe.tasks.python import vision
opts = vision.FaceDetectorOptions(base_options=mpt.BaseOptions(model_asset_path=path, delegate=mpt.BaseOptions.Delegate.CPU),
        running_mode=vision.RunningMode.VIDEO, min_detection_confidence=0.5)
with vision.FaceDetector.create_from_options(opts) as det:
    img = mp.Image(image_format=mp.ImageFormat.SRGB, data=np.ascontiguousarray(cv2.cvtColor(bgr, cv2.COLOR_BGR2RGB)))
    res = det.detect_for_video(img, int(i * 1000 / fps))     # ms, strictly increasing per detector
    for d in res.detections:
        b = d.bounding_box          # PIXELS origin_x, origin_y, width, height
        score = d.categories[0].score
        kps = d.keypoints           # NORMALIZED x,y; multiply by w,h
```
Keypoint order (verified on a real portrait): 0 right eye, 1 left eye, 2 nose tip, **3 mouth center**, 4 right ear, 5 left ear. label is None.
Portrait: bbox 283,115,234x234 score .92 (short), .85 (full). Synthetic testsrc frames -> 0 detections (expected). Create a new detector after seeks (timestamp monotonicity).

## 6. pyannote.audio 4.0.7
```python
import torch
from pyannote.audio import Pipeline
pipe = Pipeline.from_pretrained("pyannote/speaker-diarization-community-1", token=HF_TOKEN)   # `token`, not use_auth_token
pipe.to(torch.device("cuda"))
wav = torch.from_numpy(samples_f32_mono_16k)[None, :]          # (channel, time)
out = pipe({"waveform": wav, "sample_rate": 16000}, min_speakers=1, max_speakers=4)   # in-memory, no decoding
for turn, speaker in out.speaker_diarization:                  # (Segment, label)
    print(turn.start, turn.end, speaker)
# also .itertracks(yield_label=True) -> (turn, track, label)
# out.exclusive_speaker_diarization (no overlap, best for transcript alignment); out.speaker_embeddings
```
4.x returns a DiarizeOutput dataclass, not an Annotation. Not executed end-to-end (no HF token).

## 7. FFmpeg 8.0.1
Filters: subtitles, ass, sendcmd, crop, overlay present. Encoders: h264_nvenc, hevc_nvenc, av1_nvenc. libass 0.17.4, harfbuzz, fribidi, freetype, directwrite provider.

Working command (bash; absolute path with spaces; drive colon escaped; forward slashes; single quotes around value):
```
ffmpeg -y -f lavfi -i testsrc2=s=640x360:r=25:d=3 -vf "sendcmd=f=cmds.txt,crop=w=202:h=360:x=0:y=0,subtitles=filename='C\:/Users/Kavya/.../apicheck/sp ace/t.ass'" -c:v h264_nvenc -pix_fmt yuv420p B.mp4
```
cmds.txt (verified: frames differ over time, subtitle drawn):
```
0.0 crop x 0;
1.0 crop x 100;
2.0 crop x 200;
```
Verified Python (list args, no shell; rc 0, output decodes, 360x640 h264):
```python
import pathlib, subprocess
def esc(p):
    return pathlib.Path(p).resolve().as_posix().replace("\\", "\\\\").replace(":", "\\:")
vf = f"sendcmd=f='{esc(cmds)}',crop=w=202:h=360:x=0:y=0,scale=360:640,subtitles=filename='{esc(ass)}'"
subprocess.run(["ffmpeg", "-y", "-i", src, "-vf", vf, "-c:v", "h264_nvenc", "-pix_fmt", "yuv420p", out])
```
RULE: forward slashes; `\:` for the drive colon; whole value in single quotes; spaces are fine inside the quotes (do not backslash them).
APOSTROPHE in path: no escaping variant worked ('\'' with 1 or 3 backslashes, unquoted). Workaround verified: copy the .ass/fonts to a safe temp dir,
or run with cwd=<ass dir> and `subtitles=t.ass` (worked in a folder named "it's").
Note: sendcmd `crop x` updates x per frame; keep w/h fixed.

## 8. libass color emoji
NOT supported. Noto Color Emoji (google/fonts NotoColorEmoji-Regular.ttf, 25 MB) via `ass=emoji.ass:fontsdir=efonts`: a style using it rendered nothing;
the default-style fallback used Segoe UI Emoji and drew MONOCHROME glyphs (text colour + outline). Option: overlay PNG emoji with
overlay enable='between(t,a,b)', or accept monochrome. (github noto-emoji/main/fonts/NotoColorEmoji.ttf is 404; the google/fonts path works.)
