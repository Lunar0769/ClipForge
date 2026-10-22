import pytest

from app import repo
from app.llm import LLMError
from app.models import SourceType
from app.options import ProjectOptions
from app.pipeline import score
from app.pipeline.errors import StageError
from app.pipeline.score import Chunk, Moment, ScoreStage, chunk_sentences, dedupe, resolve_moment
from app.pipeline.transcript import Transcript, Word, build_sentences
from app.workspace import atomic_write_json


def make_transcript(n_sentences: int, sentence_s: float = 4.0) -> Transcript:
    words, t = [], 0.0
    for i in range(n_sentences):
        tokens = f"This is sentence number {i} about something.".split()
        step = sentence_s / len(tokens)
        for tok in tokens:
            words.append(Word(text=" " + tok, start=round(t, 3), end=round(t + step * 0.9, 3)))
            t += step
        t += 0.2
    return Transcript(language="en", duration_s=round(t, 2), words=words, sentences=build_sentences(words))


T = make_transcript(400)  # ~28 minutes
S = T.sentences
OPTS = ProjectOptions(clip_count=5, min_duration_s=30, max_duration_s=60)


def moment(first, last, score_value=70, title="Great moment"):
    return {"start_sentence": first, "end_sentence": last, "score": score_value,
            "sub_scores": {"hook": 80, "emotion": 140, "novelty": "x"}, "title": title,
            "hook_text": "one two three four five six seven eight nine ten eleven twelve",
            "hook_type": "weird", "why_viral": "w", "payoff_summary": "p",
            "keywords": ["a", "b", "c", "d", "e", "f", "g"], "emoji": ["🔥", "💡"]}


def first_sentence_in(prompt: str) -> int:
    return int(prompt.split("[S")[1].split("]")[0])


def test_chunks_cover_the_whole_transcript_with_overlap():
    chunks = chunk_sentences(S)
    assert len(chunks) == 3
    assert chunks[0].first == 0 and chunks[-1].last == len(S) - 1
    for a, b in zip(chunks, chunks[1:]):
        assert b.first <= a.last


def test_resolve_moment_fits_length_and_cleans_fields():
    m = resolve_moment(moment(10, 11), S, Chunk(0, 150), OPTS, T.duration_s)
    assert 30 <= m.end - m.start <= 60.5
    assert S[9].end < m.start <= S[10].start
    f = m.fields
    assert f["hook_type"] == "statement" and len(f["hook_text"].split()) == 10
    assert f["sub_scores"] == {"hook": 80, "emotion": 100, "novelty": 0, "value": 0, "shareability": 0, "loop_potential": 0}
    assert len(f["keywords"]) == 6


@pytest.mark.parametrize("raw", [
    moment(200, 205),               # outside the chunk
    moment(20, 10),                 # end before start
    moment(10, 12) | {"title": ""},
    "not a dict",
])
def test_resolve_moment_rejects_bad_proposals(raw):
    assert resolve_moment(raw, S, Chunk(0, 150), OPTS, T.duration_s) is None


def test_dedupe_keeps_best_of_overlapping():
    a, b, c = Moment(0, 40, 60, {}), Moment(5, 45, 90, {}), Moment(100, 140, 50, {})
    assert dedupe([a, b, c]) == [b, c]


@pytest.fixture
def scored_ctx(make_ctx, engine):
    ctx = make_ctx(source_type=SourceType.url, options=OPTS.model_dump())
    ctx.video_id = "vid1"
    repo.update_project(engine, ctx.project_id, video_id="vid1", title="Talk")
    atomic_write_json(ctx.video().transcript, T)
    return ctx


def test_stage_scores_every_chunk_and_keeps_best_distinct(scored_ctx, engine, monkeypatch):
    prompts = []

    def fake(system, prompt, **kwargs):
        prompts.append(prompt)
        first = first_sentence_in(prompt)
        return {"moments": [moment(first + 5, first + 6, 60 + len(prompts)), moment(first + 6, first + 7, 50),
                            moment(first + 40, first + 41, 80 + len(prompts))]}, "fake/model"

    monkeypatch.setattr(score, "generate_json", fake)
    ScoreStage().run(scored_ctx)
    clips = repo.list_clips(engine, scored_ctx.project_id)
    assert len(prompts) == 3
    assert "30-60 seconds" in prompts[0]
    assert len(clips) == 5 and [c.rank for c in clips] == [0, 1, 2, 3, 4]
    assert clips[0].score >= clips[-1].score
    spans = sorted((c.start_s, c.end_s) for c in clips)
    for (s1, e1), (s2, e2) in zip(spans, spans[1:]):
        overlap = max(0.0, min(e1, e2) - max(s1, s2)) / (max(e1, e2) - min(s1, s2))
        assert overlap <= 0.35
    assert max(c.start_s for c in clips) > 600  # later parts of the video were considered


def test_stage_fails_clearly_when_ai_fails_everywhere(scored_ctx, monkeypatch):
    def broken(*args, **kwargs):
        raise LLMError("The AI provider couldn't complete this step.", "Check your API key in Settings.")

    monkeypatch.setattr(score, "generate_json", broken)
    with pytest.raises(StageError) as err:
        ScoreStage().run(scored_ctx)
    assert "Settings" in err.value.hint


def test_partial_failure_keeps_good_parts(scored_ctx, engine, bus, monkeypatch):
    def flaky(system, prompt, **kwargs):
        first = first_sentence_in(prompt)
        if first == 0:
            raise LLMError("busy", "Check your API key in Settings.")
        return {"moments": [moment(first + 5, first + 6, 70)]}, "fake/model"

    monkeypatch.setattr(score, "generate_json", flaky)
    ScoreStage().run(scored_ctx)
    assert len(repo.list_clips(engine, scored_ctx.project_id)) == 2
    assert any("couldn't be scored" in (e.message or "") for e in bus.history(scored_ctx.job_id) if e.type == "log")


def test_no_speech_is_a_clear_error(scored_ctx):
    atomic_write_json(scored_ctx.video().transcript, Transcript(language="en", duration_s=5.0))
    with pytest.raises(StageError, match="enough speech"):
        ScoreStage().run(scored_ctx)
