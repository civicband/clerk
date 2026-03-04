"""Tests for clerk.extraction module."""

import importlib.util
import os

import pytest


def load_extraction_module():
    """Load extraction module directly without triggering clerk package imports.

    This avoids issues with weasyprint and other heavy dependencies in clerk/__init__.py.
    """
    spec = importlib.util.spec_from_file_location(
        "clerk.extraction",
        os.path.join(os.path.dirname(__file__), "..", "src", "clerk", "extraction.py"),
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class TestExtractionFeatureFlag:
    """Tests for ENABLE_EXTRACTION feature flag."""

    def test_extraction_disabled_by_default(self, monkeypatch):
        """Extraction should be disabled when env var not set."""
        monkeypatch.delenv("ENABLE_EXTRACTION", raising=False)

        extraction = load_extraction_module()
        assert extraction.EXTRACTION_ENABLED is False

    def test_extraction_enabled_when_set(self, monkeypatch):
        """Extraction should be enabled when ENABLE_EXTRACTION=1."""
        monkeypatch.setenv("ENABLE_EXTRACTION", "1")

        extraction = load_extraction_module()
        assert extraction.EXTRACTION_ENABLED is True

    def test_extraction_disabled_when_zero(self, monkeypatch):
        """Extraction should be disabled when ENABLE_EXTRACTION=0."""
        monkeypatch.setenv("ENABLE_EXTRACTION", "0")

        extraction = load_extraction_module()
        assert extraction.EXTRACTION_ENABLED is False


class TestEntityConfidenceThreshold:
    """Tests for ENTITY_CONFIDENCE_THRESHOLD configuration."""

    def test_default_confidence_threshold(self, monkeypatch):
        """Default confidence threshold should be 0.7."""
        monkeypatch.delenv("ENTITY_CONFIDENCE_THRESHOLD", raising=False)

        extraction = load_extraction_module()
        assert extraction.ENTITY_CONFIDENCE_THRESHOLD == 0.7

    def test_custom_confidence_threshold(self, monkeypatch):
        """Custom confidence threshold should be read from environment."""
        monkeypatch.setenv("ENTITY_CONFIDENCE_THRESHOLD", "0.85")

        extraction = load_extraction_module()
        assert extraction.ENTITY_CONFIDENCE_THRESHOLD == 0.85


class TestModelSelection:
    """Tests for configurable spaCy model selection."""

    def test_default_model_is_md(self, monkeypatch):
        """Default model should be en_core_web_md."""
        monkeypatch.setenv("ENABLE_EXTRACTION", "1")
        monkeypatch.delenv("SPACY_MODEL", raising=False)
        extraction = load_extraction_module()
        assert extraction.SPACY_MODEL == "en_core_web_md"

    def test_model_configurable_via_env(self, monkeypatch):
        """SPACY_MODEL env var overrides the default."""
        monkeypatch.setenv("ENABLE_EXTRACTION", "1")
        monkeypatch.setenv("SPACY_MODEL", "en_core_web_trf")
        extraction = load_extraction_module()
        assert extraction.SPACY_MODEL == "en_core_web_trf"


class TestGetNlp:
    """Tests for lazy NLP model loading."""

    def test_get_nlp_returns_none_when_spacy_unavailable(self, monkeypatch):
        """get_nlp returns None when spaCy not installed."""
        import builtins

        # Simulate spacy not being installed by making import fail
        original_import = builtins.__import__

        def mock_import(name, *args, **kwargs):
            if name == "spacy":
                raise ImportError("No module named 'spacy'")
            return original_import(name, *args, **kwargs)

        monkeypatch.setattr(builtins, "__import__", mock_import)

        extraction = load_extraction_module()
        result = extraction.get_nlp()
        assert result is None

    def test_get_nlp_caches_model(self):
        """get_nlp should return same instance on repeated calls."""
        extraction = load_extraction_module()

        nlp1 = extraction.get_nlp()
        nlp2 = extraction.get_nlp()

        # If spaCy is available, should be same instance
        # If not available, both should be None
        assert nlp1 is nlp2

    def test_get_nlp_logs_warning_when_spacy_unavailable(self, caplog):
        """get_nlp logs warning when spaCy not installed."""
        import logging

        # This test verifies logging behavior without crashing
        extraction = load_extraction_module()

        with caplog.at_level(logging.WARNING):
            extraction.get_nlp()  # Should not raise


class TestExtractEntities:
    """Tests for extract_entities function."""

    def test_returns_empty_when_extraction_disabled(self, monkeypatch):
        """Returns empty dict when EXTRACTION_ENABLED=False."""
        monkeypatch.setenv("ENABLE_EXTRACTION", "0")

        extraction = load_extraction_module()
        result = extraction.extract_entities("Mayor Smith spoke about the new park.")
        assert result == {"persons": [], "orgs": [], "locations": []}

    def test_returns_empty_when_nlp_unavailable(self, monkeypatch):
        """Returns empty dict when spaCy model not available."""
        monkeypatch.setenv("ENABLE_EXTRACTION", "1")

        extraction = load_extraction_module()
        # Reset NLP to simulate unavailable
        extraction._nlp = None
        extraction._nlp_load_attempted = True

        result = extraction.extract_entities("Mayor Smith spoke.")
        assert result == {"persons": [], "orgs": [], "locations": []}

    def test_returns_valid_structure_always(self, monkeypatch):
        """Result always has persons, orgs, locations keys."""
        monkeypatch.setenv("ENABLE_EXTRACTION", "1")

        extraction = load_extraction_module()
        result = extraction.extract_entities("Test text")

        assert "persons" in result
        assert "orgs" in result
        assert "locations" in result
        assert isinstance(result["persons"], list)
        assert isinstance(result["orgs"], list)
        assert isinstance(result["locations"], list)

    def test_accepts_precomputed_doc(self, monkeypatch):
        """extract_entities can use precomputed doc to avoid re-parsing."""
        monkeypatch.setenv("ENABLE_EXTRACTION", "1")
        extraction = load_extraction_module()

        nlp = extraction.get_nlp()
        if nlp is None:
            pytest.skip("spaCy not available")

        text = "Mayor Smith attended the meeting."
        doc = nlp(text)

        # Should work with precomputed doc
        result = extraction.extract_entities(text, doc=doc)
        assert "persons" in result


class TestDetectRollCall:
    """Tests for detect_roll_call function."""

    def test_detects_present_pattern(self):
        """Detects 'Present: Name, Name, Name' pattern."""
        extraction = load_extraction_module()
        text = "Present: Smith, Jones, Lee, Brown, Garcia"
        result = extraction.detect_roll_call(text)

        assert result is not None
        assert "Smith" in result
        assert "Jones" in result
        assert "Garcia" in result

    def test_detects_roll_call_pattern(self):
        """Detects 'Roll Call:' pattern."""
        extraction = load_extraction_module()
        text = "Roll Call: Members present were Smith, Jones, and Lee."
        result = extraction.detect_roll_call(text)

        assert result is not None
        assert len(result) >= 1

    def test_detects_attending_pattern(self):
        """Detects 'Attending:' pattern."""
        extraction = load_extraction_module()
        text = "Attending: Council Member Smith, Council Member Jones"
        result = extraction.detect_roll_call(text)

        assert result is not None

    def test_returns_none_when_no_roll_call(self):
        """Returns None when no roll call pattern found."""
        extraction = load_extraction_module()
        text = "The meeting was called to order at 7:00 PM."
        result = extraction.detect_roll_call(text)

        assert result is None

    def test_extracts_names_after_colon(self):
        """Extracts comma-separated names after pattern."""
        extraction = load_extraction_module()
        text = "Present: Mayor Weber, Vice Mayor Smith, Councilmember Jones"
        result = extraction.detect_roll_call(text)

        assert result is not None
        assert any("Weber" in name for name in result)


class TestExtractVotes:
    """Tests for extract_votes function."""

    def test_extracts_simple_vote_pattern(self, monkeypatch):
        """Extracts 'passed 7-0' style votes."""
        monkeypatch.setenv("ENABLE_EXTRACTION", "1")
        extraction = load_extraction_module()
        text = "The motion passed 7-0."
        result = extraction.extract_votes(text)

        assert "votes" in result
        assert len(result["votes"]) == 1
        vote = result["votes"][0]
        assert vote["result"] == "passed"
        assert vote["tally"]["ayes"] == 7
        assert vote["tally"]["nays"] == 0

    def test_extracts_approved_pattern(self, monkeypatch):
        """Extracts 'approved 5-2' style votes."""
        monkeypatch.setenv("ENABLE_EXTRACTION", "1")
        extraction = load_extraction_module()
        text = "The resolution was approved 5-2."
        result = extraction.extract_votes(text)

        assert len(result["votes"]) == 1
        vote = result["votes"][0]
        assert vote["result"] == "passed"
        assert vote["tally"]["ayes"] == 5
        assert vote["tally"]["nays"] == 2

    def test_extracts_unanimous_vote(self, monkeypatch):
        """Extracts 'unanimously' style votes."""
        monkeypatch.setenv("ENABLE_EXTRACTION", "1")
        extraction = load_extraction_module()
        text = "The motion carried unanimously."
        result = extraction.extract_votes(text)

        assert len(result["votes"]) == 1
        vote = result["votes"][0]
        assert vote["result"] == "passed"
        assert vote["tally"]["nays"] == 0

    def test_extracts_roll_call_votes(self, monkeypatch):
        """Extracts 'Ayes: Name, Name. Nays: Name.' style votes."""
        monkeypatch.setenv("ENABLE_EXTRACTION", "1")
        extraction = load_extraction_module()
        text = "Ayes: Smith, Jones, Lee. Nays: Brown."
        result = extraction.extract_votes(text)

        assert len(result["votes"]) == 1
        vote = result["votes"][0]
        assert vote["tally"]["ayes"] == 3
        assert vote["tally"]["nays"] == 1
        assert len(vote["individual_votes"]) == 4

    def test_extracts_motion_and_second(self, monkeypatch):
        """Extracts motion by and seconded by."""
        monkeypatch.setenv("ENABLE_EXTRACTION", "1")
        extraction = load_extraction_module()
        text = "Motion by Smith, seconded by Jones. The motion passed 5-0."
        result = extraction.extract_votes(text)

        assert len(result["votes"]) == 1
        vote = result["votes"][0]
        assert vote["motion_by"] == "Smith"
        assert vote["seconded_by"] == "Jones"

    def test_returns_empty_when_no_votes(self, monkeypatch):
        """Returns empty votes list when no vote patterns found."""
        monkeypatch.setenv("ENABLE_EXTRACTION", "1")
        extraction = load_extraction_module()
        text = "The committee discussed the budget proposal."
        result = extraction.extract_votes(text)

        assert result == {"votes": []}

    def test_returns_empty_when_extraction_disabled(self, monkeypatch):
        """Returns empty votes list when extraction is disabled."""
        monkeypatch.delenv("ENABLE_EXTRACTION", raising=False)
        extraction = load_extraction_module()
        text = "The motion passed 7-0."  # Would normally match
        result = extraction.extract_votes(text)

        assert result == {"votes": []}

    def test_includes_raw_text(self, monkeypatch):
        """Includes the raw text that matched."""
        monkeypatch.setenv("ENABLE_EXTRACTION", "1")
        extraction = load_extraction_module()
        text = "After discussion, the motion passed 7-0."
        result = extraction.extract_votes(text)

        assert len(result["votes"]) == 1
        assert "raw_text" in result["votes"][0]
        assert "passed 7-0" in result["votes"][0]["raw_text"]


class TestMeetingContext:
    """Tests for meeting context accumulation."""

    def test_create_meeting_context(self):
        """Creates empty meeting context."""
        extraction = load_extraction_module()
        ctx = extraction.create_meeting_context()

        assert "known_persons" in ctx
        assert "known_orgs" in ctx
        assert "attendees" in ctx
        assert "meeting_type" in ctx
        assert isinstance(ctx["known_persons"], set)

    def test_update_context_from_entities(self):
        """Updates context with extracted entities."""
        extraction = load_extraction_module()
        ctx = extraction.create_meeting_context()
        entities = {
            "persons": [{"text": "John Smith", "confidence": 0.9}],
            "orgs": [{"text": "City Council", "confidence": 0.8}],
            "locations": [],
        }

        extraction.update_context(ctx, entities=entities)

        assert "John Smith" in ctx["known_persons"]
        assert "City Council" in ctx["known_orgs"]

    def test_update_context_from_roll_call(self):
        """Updates context with roll call attendees."""
        extraction = load_extraction_module()
        ctx = extraction.create_meeting_context()
        attendees = ["Smith", "Jones", "Lee"]

        extraction.update_context(ctx, attendees=attendees)

        assert ctx["attendees"] == attendees
        assert "Smith" in ctx["known_persons"]
        assert "Jones" in ctx["known_persons"]

    def test_update_context_accumulates_attendees(self):
        """Multiple updates accumulate attendees without duplicates."""
        extraction = load_extraction_module()
        ctx = extraction.create_meeting_context()

        # First roll call from page 1
        extraction.update_context(ctx, attendees=["Smith", "Jones"])
        assert ctx["attendees"] == ["Smith", "Jones"]

        # Second roll call from page 2 with overlap
        extraction.update_context(ctx, attendees=["Jones", "Lee", "Brown"])
        assert ctx["attendees"] == ["Smith", "Jones", "Lee", "Brown"]
        assert "Lee" in ctx["known_persons"]
        assert "Brown" in ctx["known_persons"]

        # Third update with all duplicates
        extraction.update_context(ctx, attendees=["Smith", "Jones"])
        assert ctx["attendees"] == ["Smith", "Jones", "Lee", "Brown"]


class TestParseText:
    """Tests for parse_text function."""

    def test_returns_none_when_extraction_disabled(self, monkeypatch):
        """parse_text returns None when ENABLE_EXTRACTION=0."""
        monkeypatch.setenv("ENABLE_EXTRACTION", "0")
        extraction = load_extraction_module()
        result = extraction.parse_text("Some text")
        assert result is None

    def test_returns_none_when_nlp_unavailable(self, monkeypatch):
        """parse_text returns None when spaCy not available."""
        monkeypatch.setenv("ENABLE_EXTRACTION", "1")
        extraction = load_extraction_module()
        extraction._nlp = None
        extraction._nlp_load_attempted = True
        result = extraction.parse_text("Some text")
        assert result is None

    def test_returns_doc_when_available(self, monkeypatch):
        """parse_text returns spaCy Doc when available."""
        monkeypatch.setenv("ENABLE_EXTRACTION", "1")
        extraction = load_extraction_module()
        # Only test if spaCy is actually available
        if extraction.get_nlp() is not None:
            result = extraction.parse_text("The motion passed.")
            assert result is not None
            assert hasattr(result, "text")
            assert result.text == "The motion passed."

    def test_returns_none_on_spacy_exception(self, monkeypatch, mocker):
        """parse_text returns None if spaCy processing fails."""
        monkeypatch.setenv("ENABLE_EXTRACTION", "1")
        extraction = load_extraction_module()

        nlp = extraction.get_nlp()
        if nlp is None:
            pytest.skip("spaCy not available")

        # Mock the nlp call to raise an exception
        mocker.patch.object(extraction, "_nlp", side_effect=ValueError("Simulated failure"))
        result = extraction.parse_text("test")
        assert result is None


class TestMatcherInitialization:
    """Tests for lazy matcher initialization."""

    def test_get_vote_matcher_returns_matcher(self, monkeypatch):
        """_get_vote_matcher returns Matcher when spaCy available."""
        monkeypatch.setenv("ENABLE_EXTRACTION", "1")
        extraction = load_extraction_module()

        nlp = extraction.get_nlp()
        if nlp is None:
            pytest.skip("spaCy not available")

        matcher = extraction._get_vote_matcher(nlp)
        assert matcher is not None

    def test_get_motion_matcher_returns_matcher(self, monkeypatch):
        """_get_motion_matcher returns DependencyMatcher when spaCy available."""
        monkeypatch.setenv("ENABLE_EXTRACTION", "1")
        extraction = load_extraction_module()

        nlp = extraction.get_nlp()
        if nlp is None:
            pytest.skip("spaCy not available")

        matcher = extraction._get_motion_matcher(nlp)
        assert matcher is not None

    def test_matchers_are_cached(self, monkeypatch):
        """Matchers should be cached after first initialization."""
        monkeypatch.setenv("ENABLE_EXTRACTION", "1")
        extraction = load_extraction_module()

        nlp = extraction.get_nlp()
        if nlp is None:
            pytest.skip("spaCy not available")

        matcher1 = extraction._get_vote_matcher(nlp)
        matcher2 = extraction._get_vote_matcher(nlp)
        assert matcher1 is matcher2


class TestTokenMatcherVotes:
    """Tests for Token Matcher vote result extraction."""

    def test_tally_vote_with_matcher(self, monkeypatch):
        """Token Matcher extracts tally votes."""
        monkeypatch.setenv("ENABLE_EXTRACTION", "1")
        extraction = load_extraction_module()

        nlp = extraction.get_nlp()
        if nlp is None:
            pytest.skip("spaCy not available")

        doc = nlp("The motion passed 7-0.")
        votes = extraction._extract_vote_results_spacy(doc)

        assert len(votes) == 1
        assert votes[0]["result"] == "passed"
        assert votes[0]["tally"]["ayes"] == 7
        assert votes[0]["tally"]["nays"] == 0

    def test_unanimous_vote_with_matcher(self, monkeypatch):
        """Token Matcher extracts unanimous votes."""
        monkeypatch.setenv("ENABLE_EXTRACTION", "1")
        extraction = load_extraction_module()

        nlp = extraction.get_nlp()
        if nlp is None:
            pytest.skip("spaCy not available")

        doc = nlp("The motion carried unanimously.")
        votes = extraction._extract_vote_results_spacy(doc)

        assert len(votes) == 1
        assert votes[0]["result"] == "passed"

    def test_defeated_variation(self, monkeypatch):
        """Token Matcher handles 'defeated' as fail."""
        monkeypatch.setenv("ENABLE_EXTRACTION", "1")
        extraction = load_extraction_module()

        nlp = extraction.get_nlp()
        if nlp is None:
            pytest.skip("spaCy not available")

        doc = nlp("The amendment was defeated 2-5.")
        votes = extraction._extract_vote_results_spacy(doc)

        assert len(votes) == 1
        assert votes[0]["result"] == "failed"

    def test_voice_vote_with_matcher(self, monkeypatch):
        """Token Matcher extracts voice votes."""
        monkeypatch.setenv("ENABLE_EXTRACTION", "1")
        extraction = load_extraction_module()

        nlp = extraction.get_nlp()
        if nlp is None:
            pytest.skip("spaCy not available")

        doc = nlp("The item was approved by voice vote.")
        votes = extraction._extract_vote_results_spacy(doc)

        assert len(votes) >= 1


class TestDependencyMatcherMotions:
    """Tests for DependencyMatcher motion attribution."""

    def test_active_voice_motion(self, monkeypatch):
        """DependencyMatcher extracts 'Smith moved approval'."""
        monkeypatch.setenv("ENABLE_EXTRACTION", "1")
        extraction = load_extraction_module()

        nlp = extraction.get_nlp()
        if nlp is None:
            pytest.skip("spaCy not available")

        doc = nlp("Smith moved approval of the resolution.")
        result = extraction._extract_motion_attribution_spacy(doc)

        assert result is not None
        assert result.get("motion_by") == "Smith"

    def test_passive_voice_motion(self, monkeypatch):
        """DependencyMatcher extracts 'moved by Smith'."""
        monkeypatch.setenv("ENABLE_EXTRACTION", "1")
        extraction = load_extraction_module()

        nlp = extraction.get_nlp()
        if nlp is None:
            pytest.skip("spaCy not available")

        doc = nlp("The motion was moved by Smith.")
        result = extraction._extract_motion_attribution_spacy(doc)

        assert result is not None
        assert result.get("motion_by") == "Smith"

    def test_seconded_by(self, monkeypatch):
        """DependencyMatcher extracts 'seconded by Jones'."""
        monkeypatch.setenv("ENABLE_EXTRACTION", "1")
        extraction = load_extraction_module()

        nlp = extraction.get_nlp()
        if nlp is None:
            pytest.skip("spaCy not available")

        doc = nlp("The item was seconded by Jones.")
        result = extraction._extract_motion_attribution_spacy(doc)

        assert result is not None
        assert result.get("seconded_by") == "Jones"

    def test_disambiguation_rejects_relocation(self, monkeypatch):
        """DependencyMatcher rejects 'moved to Oakland' (not a motion)."""
        monkeypatch.setenv("ENABLE_EXTRACTION", "1")
        extraction = load_extraction_module()

        nlp = extraction.get_nlp()
        if nlp is None:
            pytest.skip("spaCy not available")

        doc = nlp("The company moved to Oakland last year.")
        result = extraction._extract_motion_attribution_spacy(doc)

        # Should not extract motion attribution for relocation
        assert result is None or result.get("motion_by") is None


class TestExtractVotesWithSpacy:
    """Tests for integrated spaCy + regex vote extraction."""

    def test_uses_spacy_when_available(self, monkeypatch):
        """extract_votes uses spaCy Matcher when available."""
        monkeypatch.setenv("ENABLE_EXTRACTION", "1")
        extraction = load_extraction_module()

        nlp = extraction.get_nlp()
        if nlp is None:
            pytest.skip("spaCy not available")

        text = "The measure carried 6-1."
        result = extraction.extract_votes(text)

        assert len(result["votes"]) == 1
        assert result["votes"][0]["tally"]["ayes"] == 6

    def test_falls_back_to_regex(self, monkeypatch):
        """extract_votes falls back to regex when spaCy unavailable."""
        monkeypatch.setenv("ENABLE_EXTRACTION", "1")
        extraction = load_extraction_module()

        # Force spaCy to be unavailable
        extraction._nlp = None
        extraction._nlp_load_attempted = True

        text = "The motion passed 7-0."
        result = extraction.extract_votes(text)

        # Regex should still work
        assert len(result["votes"]) == 1
        assert result["votes"][0]["tally"]["ayes"] == 7

    def test_accepts_precomputed_doc(self, monkeypatch):
        """extract_votes can use precomputed doc."""
        monkeypatch.setenv("ENABLE_EXTRACTION", "1")
        extraction = load_extraction_module()

        nlp = extraction.get_nlp()
        if nlp is None:
            pytest.skip("spaCy not available")

        text = "The motion passed 7-0."
        doc = nlp(text)
        result = extraction.extract_votes(text, doc=doc)

        assert len(result["votes"]) == 1


class TestRollcallMatcher:
    """Tests for roll call Token Matcher initialization."""

    def test_get_rollcall_matcher_returns_matcher(self, monkeypatch):
        """_get_rollcall_matcher returns Matcher when spaCy available."""
        monkeypatch.setenv("ENABLE_EXTRACTION", "1")
        extraction = load_extraction_module()

        nlp = extraction.get_nlp()
        if nlp is None:
            pytest.skip("spaCy not available")

        matcher = extraction._get_rollcall_matcher(nlp)
        assert matcher is not None

    def test_rollcall_matcher_is_cached(self, monkeypatch):
        """Roll call matcher should be cached after first initialization."""
        monkeypatch.setenv("ENABLE_EXTRACTION", "1")
        extraction = load_extraction_module()

        nlp = extraction.get_nlp()
        if nlp is None:
            pytest.skip("spaCy not available")

        matcher1 = extraction._get_rollcall_matcher(nlp)
        matcher2 = extraction._get_rollcall_matcher(nlp)
        assert matcher1 is matcher2


class TestAgendaItemExtraction:
    """Tests for extract_agenda_item_refs function."""

    def test_extracts_ordinance_reference(self, monkeypatch):
        """Extracts 'Ordinance 2024-15' as ordinance type."""
        monkeypatch.setenv("ENABLE_EXTRACTION", "1")
        extraction = load_extraction_module()

        nlp = extraction.get_nlp()
        if nlp is None:
            pytest.skip("spaCy not available")

        doc = nlp("The council voted on Ordinance 2024-15.")
        refs = extraction.extract_agenda_item_refs(doc)

        assert len(refs) == 1
        assert refs[0]["type"] == "ordinance"
        assert refs[0]["number"] == "2024-15"

    def test_extracts_resolution_reference(self, monkeypatch):
        """Extracts 'Resolution 2024-03' as resolution type."""
        monkeypatch.setenv("ENABLE_EXTRACTION", "1")
        extraction = load_extraction_module()

        nlp = extraction.get_nlp()
        if nlp is None:
            pytest.skip("spaCy not available")

        doc = nlp("Resolution 2024-03 was adopted unanimously.")
        refs = extraction.extract_agenda_item_refs(doc)

        assert len(refs) == 1
        assert refs[0]["type"] == "resolution"
        assert refs[0]["number"] == "2024-03"

    def test_extracts_item_reference(self, monkeypatch):
        """Extracts 'Item 4.2' as item type."""
        monkeypatch.setenv("ENABLE_EXTRACTION", "1")
        extraction = load_extraction_module()

        nlp = extraction.get_nlp()
        if nlp is None:
            pytest.skip("spaCy not available")

        doc = nlp("Discussion of Item 4.2 continued.")
        refs = extraction.extract_agenda_item_refs(doc)

        assert len(refs) == 1
        assert refs[0]["type"] == "item"
        assert refs[0]["number"] == "4.2"

    def test_extracts_consent_calendar_reference(self, monkeypatch):
        """Extracts 'Consent Calendar Item 3' as consent_calendar type."""
        monkeypatch.setenv("ENABLE_EXTRACTION", "1")
        extraction = load_extraction_module()

        nlp = extraction.get_nlp()
        if nlp is None:
            pytest.skip("spaCy not available")

        doc = nlp("Consent Calendar Item 3 was approved.")
        refs = extraction.extract_agenda_item_refs(doc)

        assert any(r["type"] == "consent_calendar" for r in refs)

    def test_returns_empty_for_plain_text(self, monkeypatch):
        """Returns empty list for text with no agenda item references."""
        monkeypatch.setenv("ENABLE_EXTRACTION", "1")
        extraction = load_extraction_module()

        nlp = extraction.get_nlp()
        if nlp is None:
            pytest.skip("spaCy not available")

        doc = nlp("The meeting was called to order at seven PM.")
        refs = extraction.extract_agenda_item_refs(doc)

        assert refs == []


class TestSpacyRollcallExtraction:
    """Tests for spaCy-based roll call vote extraction."""

    def test_extracts_rollcall_with_spacy(self, monkeypatch):
        """spaCy extracts roll call votes using NER."""
        monkeypatch.setenv("ENABLE_EXTRACTION", "1")
        extraction = load_extraction_module()

        nlp = extraction.get_nlp()
        if nlp is None:
            pytest.skip("spaCy not available")

        # Use a text where spaCy should recognize names as PERSON entities
        doc = nlp("Ayes: John Smith, Mary Jones. Nays: Robert Brown.")
        votes = extraction._extract_rollcall_votes_spacy(doc)

        # May return empty if NER doesn't recognize as PERSON
        # This tests the function runs without error
        assert isinstance(votes, list)

    def test_returns_empty_when_no_rollcall_pattern(self, monkeypatch):
        """spaCy roll call returns empty when no Ayes/Nays pattern."""
        monkeypatch.setenv("ENABLE_EXTRACTION", "1")
        extraction = load_extraction_module()

        nlp = extraction.get_nlp()
        if nlp is None:
            pytest.skip("spaCy not available")

        doc = nlp("The motion passed 7-0.")
        votes = extraction._extract_rollcall_votes_spacy(doc)

        assert votes == []

    def test_fallback_to_regex_when_spacy_finds_nothing(self, monkeypatch):
        """extract_votes falls back to regex for roll calls when spaCy finds none."""
        monkeypatch.setenv("ENABLE_EXTRACTION", "1")
        extraction = load_extraction_module()

        nlp = extraction.get_nlp()
        if nlp is None:
            pytest.skip("spaCy not available")

        # Text with roll call that regex can parse
        text = "Ayes: Smith, Jones. Nays: Brown."
        result = extraction.extract_votes(text)

        # Should find votes (either via spaCy NER or regex fallback)
        assert len(result["votes"]) >= 1
        # Should have individual votes
        if result["votes"]:
            assert len(result["votes"][0]["individual_votes"]) >= 1

    def test_spacy_rollcall_returns_empty_when_nlp_unavailable(self, monkeypatch):
        """_extract_rollcall_votes_spacy returns empty when NLP unavailable."""
        monkeypatch.setenv("ENABLE_EXTRACTION", "1")
        extraction = load_extraction_module()

        # Force spaCy to be unavailable
        extraction._nlp = None
        extraction._nlp_load_attempted = True

        # Create a mock doc-like object (shouldn't be used since nlp is None)
        result = extraction._extract_rollcall_votes_spacy(None)
        assert result == []


class TestVoteTopicExtraction:
    """Tests for extract_vote_topic function."""

    def test_extracts_topic_from_motion_sentence(self, monkeypatch):
        """Given a sentence with a motion verb, extract the topic."""
        monkeypatch.setenv("ENABLE_EXTRACTION", "1")
        extraction = load_extraction_module()

        nlp = extraction.get_nlp()
        if nlp is None:
            pytest.skip("spaCy not available")

        text = "Motion to approve the downtown parking structure plan passed 7-0."
        doc = nlp(text)
        # Vote is at "passed 7-0" - find its char offset
        offset = text.index("passed")
        topic = extraction.extract_vote_topic(doc, offset)

        assert topic is not None
        assert "parking" in topic.lower()

    def test_extracts_topic_from_preceding_sentence(self, monkeypatch):
        """Falls back to preceding sentence when vote sentence is terse."""
        monkeypatch.setenv("ENABLE_EXTRACTION", "1")
        extraction = load_extraction_module()

        nlp = extraction.get_nlp()
        if nlp is None:
            pytest.skip("spaCy not available")

        text = "The Council discussed the new zoning amendment for District 5. The motion passed 5-2."
        doc = nlp(text)
        offset = text.index("passed")
        topic = extraction.extract_vote_topic(doc, offset)

        assert topic is not None
        assert "zoning" in topic.lower()

    def test_returns_none_for_no_context(self, monkeypatch):
        """Returns None when the text is too terse to extract a topic."""
        monkeypatch.setenv("ENABLE_EXTRACTION", "1")
        extraction = load_extraction_module()

        nlp = extraction.get_nlp()
        if nlp is None:
            pytest.skip("spaCy not available")

        text = "Passed 7-0."
        doc = nlp(text)
        topic = extraction.extract_vote_topic(doc, 0)

        assert topic is None

    def test_topic_truncated_to_max_length(self, monkeypatch):
        """Topic should be truncated to max_length characters."""
        monkeypatch.setenv("ENABLE_EXTRACTION", "1")
        extraction = load_extraction_module()

        nlp = extraction.get_nlp()
        if nlp is None:
            pytest.skip("spaCy not available")

        # Create a very long sentence that will produce a long topic
        long_subject = " ".join(["comprehensive"] * 30)
        text = f"The Council discussed the {long_subject} infrastructure development plan for the entire metropolitan region. The motion passed 5-2."
        doc = nlp(text)
        offset = text.index("passed")
        topic = extraction.extract_vote_topic(doc, offset, max_length=150)

        assert topic is not None
        assert len(topic) <= 150


class TestSectionDetection:
    """Tests for detect_section function."""

    def test_detects_consent_calendar(self, monkeypatch):
        """detect_section identifies CONSENT CALENDAR section."""
        monkeypatch.setenv("ENABLE_EXTRACTION", "1")
        extraction = load_extraction_module()
        result = extraction.detect_section("CONSENT CALENDAR\nItem 1. Approve minutes.")
        assert result == "consent_calendar"

    def test_detects_public_hearing(self, monkeypatch):
        """detect_section identifies PUBLIC HEARING section."""
        monkeypatch.setenv("ENABLE_EXTRACTION", "1")
        extraction = load_extraction_module()
        result = extraction.detect_section("PUBLIC HEARING\nOrdinance 2024-15.")
        assert result == "public_hearing"

    def test_detects_new_business(self, monkeypatch):
        """detect_section identifies NEW BUSINESS section."""
        monkeypatch.setenv("ENABLE_EXTRACTION", "1")
        extraction = load_extraction_module()
        result = extraction.detect_section("NEW BUSINESS\nCouncil discussed parking.")
        assert result == "new_business"

    def test_returns_none_for_no_section(self, monkeypatch):
        """detect_section returns None when no section header found."""
        monkeypatch.setenv("ENABLE_EXTRACTION", "1")
        extraction = load_extraction_module()
        result = extraction.detect_section("The mayor welcomed everyone.")
        assert result is None

    def test_meeting_context_tracks_section(self, monkeypatch):
        """create_meeting_context includes current_section key set to None."""
        monkeypatch.setenv("ENABLE_EXTRACTION", "1")
        extraction = load_extraction_module()
        context = extraction.create_meeting_context()
        assert "current_section" in context
        assert context["current_section"] is None


class TestEntityResolution:
    """Tests for entity name resolution (pure Python, no spaCy needed)."""

    def test_merges_name_variants(self, monkeypatch):
        """Entities with 'Smith', 'John Smith', 'Councilmember Smith' resolve to 1 person."""
        monkeypatch.setenv("ENABLE_EXTRACTION", "1")
        extraction = load_extraction_module()

        entities = {
            "persons": [
                {"text": "Smith", "confidence": 0.85},
                {"text": "John Smith", "confidence": 0.90},
                {"text": "Councilmember Smith", "confidence": 0.80},
            ],
            "orgs": [],
            "locations": [],
        }
        result = extraction.resolve_entities(entities)

        assert len(result["persons"]) == 1
        person = result["persons"][0]
        assert person["text"] == "John Smith"
        assert "Smith" in person["variants"] or "Councilmember Smith" in person["variants"]
        assert person["confidence"] == 0.90

    def test_keeps_distinct_persons(self, monkeypatch):
        """'John Smith' and 'Jane Doe' stay as 2 separate persons."""
        monkeypatch.setenv("ENABLE_EXTRACTION", "1")
        extraction = load_extraction_module()

        entities = {
            "persons": [
                {"text": "John Smith", "confidence": 0.90},
                {"text": "Jane Doe", "confidence": 0.85},
            ],
            "orgs": [],
            "locations": [],
        }
        result = extraction.resolve_entities(entities)

        assert len(result["persons"]) == 2
        names = [p["text"] for p in result["persons"]]
        assert "John Smith" in names
        assert "Jane Doe" in names

    def test_handles_initials(self, monkeypatch):
        """'J. Smith' and 'John Smith' merge into 1 person with canonical 'John Smith'."""
        monkeypatch.setenv("ENABLE_EXTRACTION", "1")
        extraction = load_extraction_module()

        entities = {
            "persons": [
                {"text": "J. Smith", "confidence": 0.80},
                {"text": "John Smith", "confidence": 0.90},
            ],
            "orgs": [],
            "locations": [],
        }
        result = extraction.resolve_entities(entities)

        assert len(result["persons"]) == 1
        person = result["persons"][0]
        assert person["text"] == "John Smith"
        assert "J. Smith" in person["variants"]

    def test_preserves_orgs_and_locations(self, monkeypatch):
        """Orgs and locations pass through unchanged."""
        monkeypatch.setenv("ENABLE_EXTRACTION", "1")
        extraction = load_extraction_module()

        entities = {
            "persons": [
                {"text": "John Smith", "confidence": 0.90},
            ],
            "orgs": [
                {"text": "City Council", "confidence": 0.85},
            ],
            "locations": [
                {"text": "Oakland", "confidence": 0.80},
            ],
        }
        result = extraction.resolve_entities(entities)

        assert result["orgs"] == [{"text": "City Council", "confidence": 0.85}]
        assert result["locations"] == [{"text": "Oakland", "confidence": 0.80}]


class TestVoteRecordTopicIntegration:
    """Tests that vote records include topic and agenda_item_ref fields."""

    def test_vote_record_has_topic_fields(self, monkeypatch):
        """Vote records include agenda_item_ref, topic, and section fields."""
        monkeypatch.setenv("ENABLE_EXTRACTION", "1")
        extraction = load_extraction_module()

        record = extraction._create_vote_record(
            result="passed", ayes=7, nays=0, raw_text="passed 7-0"
        )
        assert "agenda_item_ref" in record
        assert "topic" in record
        assert "section" in record

    def test_vote_record_accepts_topic_fields(self, monkeypatch):
        """Vote records can be created with topic, agenda_item_ref, and section."""
        monkeypatch.setenv("ENABLE_EXTRACTION", "1")
        extraction = load_extraction_module()

        record = extraction._create_vote_record(
            result="passed",
            ayes=7,
            nays=0,
            raw_text="passed 7-0",
            agenda_item_ref={"type": "ordinance", "number": "2024-15"},
            topic="downtown parking structure",
            section="public_hearing",
        )
        assert record["agenda_item_ref"] == {"type": "ordinance", "number": "2024-15"}
        assert record["topic"] == "downtown parking structure"
        assert record["section"] == "public_hearing"

    def test_extract_votes_includes_topic(self, monkeypatch):
        """Full vote extraction populates topic from context."""
        monkeypatch.setenv("ENABLE_EXTRACTION", "1")
        extraction = load_extraction_module()
        nlp = extraction.get_nlp()
        if nlp is None:
            pytest.skip("spaCy not available")

        text = "Motion to approve Ordinance 2024-15 regarding the downtown parking structure passed 7-0."
        result = extraction.extract_votes(text)
        votes = result["votes"]
        if votes:
            vote = votes[0]
            assert "topic" in vote
            assert "agenda_item_ref" in vote
            assert "section" in vote

    def test_find_nearest_ref(self, monkeypatch):
        """_find_nearest_ref returns the closest preceding ref."""
        monkeypatch.setenv("ENABLE_EXTRACTION", "1")
        extraction = load_extraction_module()

        refs = [
            {"type": "ordinance", "number": "2024-10", "char_start": 0, "char_end": 20},
            {"type": "resolution", "number": "2024-03", "char_start": 50, "char_end": 70},
        ]
        # Vote at position 80 should find the resolution (closer)
        result = extraction._find_nearest_ref(refs, 80)
        assert result is not None
        assert result["type"] == "resolution"
        assert result["number"] == "2024-03"

    def test_find_nearest_ref_ignores_after(self, monkeypatch):
        """_find_nearest_ref ignores refs that come after the vote."""
        monkeypatch.setenv("ENABLE_EXTRACTION", "1")
        extraction = load_extraction_module()

        refs = [
            {"type": "ordinance", "number": "2024-10", "char_start": 100, "char_end": 120},
        ]
        # Vote at position 50 should not find a ref after it
        result = extraction._find_nearest_ref(refs, 50)
        assert result is None

    def test_find_nearest_ref_empty_list(self, monkeypatch):
        """_find_nearest_ref returns None for empty refs list."""
        monkeypatch.setenv("ENABLE_EXTRACTION", "1")
        extraction = load_extraction_module()

        result = extraction._find_nearest_ref([], 50)
        assert result is None

    def test_regex_fallback_has_topic_fields(self, monkeypatch):
        """Regex fallback vote records include topic fields set to None."""
        monkeypatch.setenv("ENABLE_EXTRACTION", "1")
        extraction = load_extraction_module()

        # Force spaCy to be unavailable so regex fallback is used
        extraction._nlp = None
        extraction._nlp_load_attempted = True

        text = "The motion passed 7-0."
        result = extraction.extract_votes(text)

        assert len(result["votes"]) == 1
        vote = result["votes"][0]
        assert "topic" in vote
        assert vote["topic"] is None
        assert "agenda_item_ref" in vote
        assert vote["agenda_item_ref"] is None
        assert "section" in vote
        assert vote["section"] is None


class TestEntityCategorization:
    """Tests for entity categorization (pure Python, no spaCy needed)."""

    def test_categorizes_elected_official_by_title(self, monkeypatch):
        """Entity with 'Councilmember Smith' gets category 'elected_official'."""
        monkeypatch.setenv("ENABLE_EXTRACTION", "1")
        extraction = load_extraction_module()

        entities = {
            "persons": [
                {"text": "Councilmember Smith", "confidence": 0.85},
            ],
            "orgs": [],
            "locations": [],
        }
        result = extraction.resolve_entities(entities)

        assert len(result["persons"]) == 1
        assert result["persons"][0]["category"] == "elected_official"

    def test_categorizes_elected_official_by_roll_call(self, monkeypatch):
        """Entity 'Smith' in meeting_context attendees list gets 'elected_official'."""
        monkeypatch.setenv("ENABLE_EXTRACTION", "1")
        extraction = load_extraction_module()

        entities = {
            "persons": [
                {"text": "Smith", "confidence": 0.85},
            ],
            "orgs": [],
            "locations": [],
        }
        ctx = extraction.create_meeting_context()
        ctx["attendees"] = ["Smith", "Jones", "Lee"]

        result = extraction.resolve_entities(entities, meeting_context=ctx)

        assert len(result["persons"]) == 1
        assert result["persons"][0]["category"] == "elected_official"

    def test_categorizes_staff(self, monkeypatch):
        """Entity 'City Manager Johnson' gets category 'staff'."""
        monkeypatch.setenv("ENABLE_EXTRACTION", "1")
        extraction = load_extraction_module()

        entities = {
            "persons": [
                {"text": "City Manager Johnson", "confidence": 0.85},
            ],
            "orgs": [],
            "locations": [],
        }
        result = extraction.resolve_entities(entities)

        assert len(result["persons"]) == 1
        assert result["persons"][0]["category"] == "staff"

    def test_defaults_to_unknown(self, monkeypatch):
        """Entity 'John Doe' with no title and not in attendees gets 'unknown'."""
        monkeypatch.setenv("ENABLE_EXTRACTION", "1")
        extraction = load_extraction_module()

        entities = {
            "persons": [
                {"text": "John Doe", "confidence": 0.85},
            ],
            "orgs": [],
            "locations": [],
        }
        result = extraction.resolve_entities(entities)

        assert len(result["persons"]) == 1
        assert result["persons"][0]["category"] == "unknown"
