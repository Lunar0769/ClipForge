from app.pipeline.transcript import Word, build_sentences


def w(text, start, end):
    return Word(text=text, start=start, end=end)


def test_splits_on_sentence_punctuation():
    words = [w(" Hello", 0, 0.4), w(" world.", 0.4, 0.8), w(" How", 1.0, 1.2), w(" are", 1.2, 1.3), w(" you?", 1.3, 1.6)]
    sentences = build_sentences(words)
    assert [s.text for s in sentences] == ["Hello world.", "How are you?"]
    assert [(s.word_start, s.word_end) for s in sentences] == [(0, 2), (2, 5)]
    assert (sentences[1].start, sentences[1].end) == (1.0, 1.6)


def test_splits_on_long_pause_without_punctuation():
    words = [w(" so", 0, 0.3), w(" yeah", 0.3, 0.6), w(" anyway", 2.5, 2.9)]
    assert [s.text for s in build_sentences(words)] == ["so yeah", "anyway"]


def test_caps_sentence_length():
    words = [w(f" w{i}", i * 0.1, i * 0.1 + 0.05) for i in range(130)]
    sentences = build_sentences(words, max_words=60)
    assert [s.word_end - s.word_start for s in sentences] == [60, 60, 10]


def test_closing_quote_after_period_ends_sentence():
    words = [w(' "Stop."', 0, 0.5), w(" Then", 0.6, 0.8)]
    assert [s.text for s in build_sentences(words)] == ['"Stop."', "Then"]


def test_non_latin_scripts():
    hindi = [w(" नमस्ते।", 0, 0.5), w(" दुनिया", 0.6, 1.0)]
    assert [s.text for s in build_sentences(hindi)] == ["नमस्ते।", "दुनिया"]
    chinese = [w("你好", 0, 0.3), w("。", 0.3, 0.35), w("世界", 0.5, 0.8)]
    assert [s.text for s in build_sentences(chinese)] == ["你好。", "世界"]


def test_empty_words():
    assert build_sentences([]) == []
