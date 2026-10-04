from pydantic import BaseModel

from app.workspace import atomic_write_json, read_json


class Thing(BaseModel):
    name: str
    score: float


def test_workspace_creates_dirs(workspace):
    assert workspace.projects_dir.is_dir()
    assert workspace.videos_dir.is_dir()
    assert workspace.project_dir("p1").is_dir()
    assert workspace.video("v1").dir.is_dir()


def test_video_paths(workspace):
    vp = workspace.video("v1")
    assert vp.audio.name == "audio.wav"
    assert vp.meta.name == "meta.json"
    assert vp.transcript.name == "transcript.json"


def test_find_source_ignores_partial_files(workspace):
    vp = workspace.video("v1")
    assert vp.find_source() is None
    (vp.dir / "source.mp4.tmp").write_bytes(b"x")
    (vp.dir / "source.mkv.part").write_bytes(b"x")
    assert vp.find_source() is None
    (vp.dir / "source.mkv").write_bytes(b"x")
    assert vp.find_source() == vp.dir / "source.mkv"


def test_atomic_write_json_model_and_dict(workspace):
    target = workspace.video("v1").meta
    atomic_write_json(target, Thing(name="vidéo ü", score=0.5))
    assert read_json(target) == {"name": "vidéo ü", "score": 0.5}
    atomic_write_json(target, {"a": [1, 2]})
    assert read_json(target) == {"a": [1, 2]}
    assert not list(target.parent.glob("*.tmp"))


def test_remove_project(workspace):
    d = workspace.project_dir("p1")
    (d / "upload.mp4").write_bytes(b"x")
    workspace.remove_project("p1")
    assert not d.exists()
