import json
import os
import shutil
from pathlib import Path
from typing import Any

from pydantic import BaseModel

_PARTIAL_SUFFIXES = {".tmp", ".part", ".ytdl"}


class VideoPaths:
    """Content-addressed cache for one source video, shared by all projects using it."""

    def __init__(self, directory: Path) -> None:
        self.dir = directory

    @property
    def audio(self) -> Path:
        return self.dir / "audio.wav"

    @property
    def meta(self) -> Path:
        return self.dir / "meta.json"

    @property
    def transcript(self) -> Path:
        return self.dir / "transcript.json"

    def find_source(self) -> Path | None:
        for path in sorted(self.dir.glob("source.*")):
            if path.suffix.lower() not in _PARTIAL_SUFFIXES:
                return path
        return None


class Workspace:
    def __init__(self, root: Path) -> None:
        self.root = Path(root)
        self.projects_dir = self.root / "projects"
        self.videos_dir = self.root / "videos"
        self.projects_dir.mkdir(parents=True, exist_ok=True)
        self.videos_dir.mkdir(parents=True, exist_ok=True)

    def project_dir(self, project_id: str) -> Path:
        path = self.projects_dir / project_id
        path.mkdir(parents=True, exist_ok=True)
        return path

    def video(self, video_id: str) -> VideoPaths:
        path = self.videos_dir / video_id
        path.mkdir(parents=True, exist_ok=True)
        return VideoPaths(path)

    def remove_project(self, project_id: str) -> None:
        shutil.rmtree(self.projects_dir / project_id, ignore_errors=True)


def atomic_write_json(path: Path, data: BaseModel | dict | list) -> None:
    if isinstance(data, BaseModel):
        text = data.model_dump_json(indent=2)
    else:
        text = json.dumps(data, ensure_ascii=False, indent=2)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(text, encoding="utf-8")
    os.replace(tmp, path)


def read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))
