"""The self-trust concept fixture: shares, remnants, compatibility read, pinned check."""

from __future__ import annotations

import json
from collections import Counter

import pytest

from assay.investigations.workflow_correctness import workflow_tree_digest
from verification_pilot.fixtures import GROUPS, read_raw_repository, whole_word_pattern
from verification_pilot.self_trust.check import RESULT, cases
from verification_pilot.self_trust.concepts import (
    CONCEPTS,
    HISTORICAL,
    LEGACY_READER,
    LEGACY_TEST,
    Concept,
    blind_replace,
    legacy_note_path,
    ownership,
    spelling_pattern,
    subject_repository,
)

REPOSITORY = read_raw_repository()


@pytest.mark.parametrize("concept", CONCEPTS, ids=lambda c: c.name)
def test_each_share_holds_one_remnant_and_one_retained_spelling(concept: Concept) -> None:
    owners = ownership(REPOSITORY, concept)
    assert [owners[remnant.path] for remnant in concept.remnants] == list(GROUPS)
    carriers = [LEGACY_READER, LEGACY_TEST, legacy_note_path(REPOSITORY, concept)]
    assert [owners[path] for path in carriers] == list(GROUPS)
    counts = Counter(owners.values())
    assert max(counts.values()) - min(counts.values()) <= 1


@pytest.mark.parametrize("concept", CONCEPTS, ids=lambda c: c.name)
def test_clean_rename_keeps_only_the_compatibility_spellings(concept: Concept) -> None:
    clean = subject_repository(REPOSITORY, concept, None)
    old = spelling_pattern(tuple(item for item, _ in concept.spellings))
    remaining = {path for path, source in clean.items()
                 if path not in HISTORICAL and old.search(source)}
    assert remaining == {LEGACY_READER, LEGACY_TEST, legacy_note_path(REPOSITORY, concept)}


@pytest.mark.parametrize("concept", CONCEPTS, ids=lambda c: c.name)
@pytest.mark.parametrize("group", GROUPS)
def test_a_planted_subject_reverts_one_line_the_type_search_misses(
    concept: Concept, group: str,
) -> None:
    clean = subject_repository(REPOSITORY, concept, None)
    planted = subject_repository(REPOSITORY, concept, group)  # type: ignore[arg-type]
    remnant = concept.remnants[GROUPS.index(group)]
    changed = [path for path in planted if planted[path] != clean[path]]
    assert changed == [remnant.path]
    before, after = clean[remnant.path].split("\n"), planted[remnant.path].split("\n")
    assert [i + 1 for i, (a, b) in enumerate(zip(before, after, strict=True)) if a != b] == [
        remnant.line]
    assert whole_word_pattern(remnant.old).search(after[remnant.line - 1])
    type_search = whole_word_pattern(concept.old_type)
    assert not any(type_search.search(source) for path, source in planted.items()
                   if path not in HISTORICAL)


@pytest.mark.parametrize("concept", CONCEPTS, ids=lambda c: c.name)
def test_blind_replace_rewrites_the_remnant_and_every_retained_spelling(
    concept: Concept,
) -> None:
    planted = subject_repository(REPOSITORY, concept, "group_a")
    blind = blind_replace(planted, concept)
    changed = {path for path in blind if blind[path] != planted[path]}
    assert changed == {concept.remnants[0].path, LEGACY_READER, LEGACY_TEST,
                       legacy_note_path(REPOSITORY, concept)}


def test_committed_image_check_holds_for_the_current_generator() -> None:
    # Any change to the generator changes a tree digest; re-run check.py then.
    result = json.loads(RESULT.read_text(encoding="utf-8"))
    assert result["holds"] is True
    expected = {name: workflow_tree_digest(tree)
                for concept in CONCEPTS for name, tree in cases(REPOSITORY, concept).items()}
    assert {name: entry["tree_digest"] for name, entry in result["cases"].items()} == expected
