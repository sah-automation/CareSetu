"""Phase 0 corpus fixture sanity tests.

Verifies the committed corpus + ground truth loads in one call and satisfies
the Issue #3 acceptance shape: clip count, balanced cohorts, per-clip files,
pre-summary schema, and the PHI guard.
"""

from phase0.loader import COHORTS, FieldSet, load_corpus, scan_phi


def test_loads_in_one_call() -> None:
    corpus = load_corpus()
    assert isinstance(corpus.field_set, FieldSet)
    assert len(corpus.clips) >= 40


def test_three_balanced_cohorts() -> None:
    corpus = load_corpus()
    counts = {
        cohort: sum(1 for clip in corpus.clips if clip.cohort == cohort) for cohort in COHORTS
    }
    assert set(counts) == COHORTS
    assert min(counts.values()) >= 10
    assert min(counts.values()) / max(counts.values()) >= 0.5


def test_every_clip_has_all_files() -> None:
    corpus = load_corpus()
    for clip in corpus.clips:
        assert clip.audio_path.is_file()
        assert clip.transcript_path.is_file()
        assert clip.pre_summary_path.is_file()
        assert clip.duration_s > 0
        assert clip.word_count >= 20


def test_pre_summaries_match_manifest_and_field_set() -> None:
    corpus = load_corpus()
    by_id = {clip.clip_id: clip for clip in corpus.clips}
    assert len(corpus.pre_summaries) == len(corpus.clips)
    for summary in corpus.pre_summaries:
        clip = by_id[summary.clip_id]
        assert summary.cohort == clip.cohort
        assert summary.cohort in COHORTS
        assert summary.field_set_version == corpus.field_set.version


def test_phi_scan_clean() -> None:
    corpus = load_corpus()
    assert scan_phi(corpus) == ()
