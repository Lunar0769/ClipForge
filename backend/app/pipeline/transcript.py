from collections.abc import Sequence

from pydantic import BaseModel, Field

SENTENCE_END = (".", "?", "!", "…", "。", "？", "！", "।", "؟")
_TRAILING_CLOSERS = "\"'”’)]»"


class Word(BaseModel):
    text: str  # as emitted by Whisper; Latin scripts carry a leading space
    start: float
    end: float
    prob: float = 1.0


class Segment(BaseModel):
    id: int
    start: float
    end: float
    text: str
    words: list[Word] = Field(default_factory=list)


class Sentence(BaseModel):
    id: int
    start: float
    end: float
    text: str
    word_start: int  # index into Transcript.words
    word_end: int    # exclusive


class Transcript(BaseModel):
    language: str
    language_prob: float = 0.0
    duration_s: float
    segments: list[Segment] = Field(default_factory=list)
    words: list[Word] = Field(default_factory=list)
    sentences: list[Sentence] = Field(default_factory=list)


def join_words(words: Sequence[Word]) -> str:
    return "".join(w.text for w in words).strip()


def build_sentences(words: Sequence[Word], *, max_gap_s: float = 1.2, max_words: int = 60) -> list[Sentence]:
    sentences: list[Sentence] = []
    start = 0

    def close(end: int) -> None:
        nonlocal start
        chunk = words[start:end]
        if chunk:
            sentences.append(Sentence(
                id=len(sentences), start=chunk[0].start, end=chunk[-1].end,
                text=join_words(chunk), word_start=start, word_end=end,
            ))
        start = end

    for i, word in enumerate(words):
        if i > start and word.start - words[i - 1].end > max_gap_s:
            close(i)
        token = word.text.strip().rstrip(_TRAILING_CLOSERS)
        if token.endswith(SENTENCE_END) or (i + 1 - start) >= max_words:
            close(i + 1)
    close(len(words))
    return sentences
