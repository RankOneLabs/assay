"""The raw tree and generated subject workspaces have separate identities."""

from __future__ import annotations

from assay.investigations.workflow_correctness import workflow_tree_digest
from verification_pilot.fixture import (
    DESIGN_COMMIT,
    MAX_BYTES,
    MAX_FILES,
    OAKRIDGE_COMMIT,
    PINNED_TREE_DIGEST,
    SOURCE_TREE_COMMIT,
    load_fixture,
    subject_repository,
)
from verification_pilot.fixtures import RAW_REPO, base_subjects, pilot_sessions, use_sites_for


def test_raw_slice_is_pinned_and_has_exactly_62_files() -> None:
    fixture = load_fixture()
    assert len(fixture.repository) == 62
    assert sum(path.is_file() for path in RAW_REPO.rglob("*")) == 63  # provenance README
    assert all((RAW_REPO / path).is_file() for path in fixture.repository)
    assert sum(len(text.encode()) for text in fixture.repository.values()) == 348_936
    assert len(fixture.repository) <= MAX_FILES
    assert sum(len(text.encode()) for text in fixture.repository.values()) <= MAX_BYTES
    assert workflow_tree_digest(fixture.repository) == fixture.tree_digest == PINNED_TREE_DIGEST
    assert all(len(commit) == 40 for commit in (OAKRIDGE_COMMIT, SOURCE_TREE_COMMIT,
                                                DESIGN_COMMIT))
    assert not (RAW_REPO.parent.parent / "fixtures" / "pilot-edit" / "repository").exists()
    assert "inert input data" in (RAW_REPO / "README.md").read_text()


def test_subject_decoys_are_planted_after_the_raw_slice() -> None:
    fixture = load_fixture()
    assert "CHANGELOG.md" not in fixture.repository
    assert "docs/migration.md" not in fixture.repository
    subjects = base_subjects()
    assert len(subjects) == 16
    assert len(pilot_sessions(subjects)) == 24
    for subject in subjects:
        repository = subject_repository(subject, fixture)
        assert "CHANGELOG.md" in repository
        assert "docs/migration.md" in repository
        assert subject.migration.old_symbol in repository["CHANGELOG.md"]
        assert subject.migration.old_symbol in repository["docs/migration.md"]
        code = {path: source for path, source in repository.items()
                if path not in ("CHANGELOG.md", "docs/migration.md")}
        if subject.location is not None:
            assert use_sites_for(code, subject.migration.old_symbol) == (subject.location,)
        else:
            assert use_sites_for(code, subject.migration.old_symbol) == ()
