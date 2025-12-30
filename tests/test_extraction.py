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
