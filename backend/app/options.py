import hashlib

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.models import Project


class ProjectOptions(BaseModel):
    """Per-project clipping options (spec §3.5: default 30–60 s, configurable 15–90 s)."""

    model_config = ConfigDict(extra="ignore")

    clip_count: int = Field(10, ge=3, le=30)
    min_duration_s: int = Field(30, ge=15, le=85)
    max_duration_s: int = Field(60, ge=20, le=90)

    @model_validator(mode="after")
    def _range(self) -> "ProjectOptions":
        if self.max_duration_s < self.min_duration_s + 5:
            raise ValueError("The longest clip length must be at least 5 seconds more than the shortest.")
        return self

    def fingerprint(self) -> str:
        return hashlib.sha256(self.model_dump_json().encode()).hexdigest()[:12]


def project_options(project: Project) -> ProjectOptions:
    return ProjectOptions.model_validate(project.options or {})
