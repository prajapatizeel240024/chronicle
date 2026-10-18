from datetime import date
from types import SimpleNamespace

from chronicle.extract import (AnthropicExtractor, RawExtraction, find_quote, validate_extraction)
from chronicle.schema import Message, PatientContext

CTX = PatientContext("px", ["pots", "migraine"], [])
MSG = Message("px-d01a", "px", date(2026, 7, 9), "text", "Dizziness since Tuesday, a 6. Took my Inderal. No nausea today.")


def run(events):
    return validate_extraction(RawExtraction(events), MSG, CTX)


def test_invented_symptom_is_rejected_by_the_quote_check():
    ev, rej = run([{"kind": "symptom", "name": "dizziness", "severity": 4, "quote": "my legs gave out completely"}])
    assert not ev and rej[0].reason == "quote_not_verbatim"


def test_quote_check_ignores_case_and_whitespace_only():
    assert find_quote("a  b\nc", "A b C") is not None
    assert find_quote("a b c", "a b d") is None


def test_dates_resolved_in_code_and_brand_normalised_in_code():
    ev, rej = run([
        {"kind": "symptom", "name": "dizziness", "severity": 6, "date_phrase": "since Tuesday", "quote": "Dizziness since Tuesday, a 6"},
        {"kind": "med", "name": "Inderal", "med_action": "take", "date_phrase": "today", "quote": "Took my Inderal"}])
    assert not rej
    assert ev[0].event_date == date(2026, 7, 7)
    assert ev[1].name == "propranolol" and ev[1].med_as_said == "Inderal"


def test_negated_event_has_no_severity_and_unknown_condition_is_unattributed():
    ev, _ = run([{"kind": "symptom", "name": "nausea", "severity": 5, "negated": True, "condition": "lupus",
                  "quote": "No nausea today"}])
    assert ev[0].severity is None and ev[0].condition == "unattributed"


def test_schema_violations_and_unknown_names_and_bad_dates_are_rejected():
    _, rej = run([
        {"kind": "symptom", "name": "dizziness", "severity": 11, "quote": "Dizziness since Tuesday"},       # out of range
        {"kind": "symptom", "name": "dizziness", "extra": 1, "quote": "Dizziness since Tuesday"},          # extra field
        {"kind": "symptom", "name": "spontaneous combustion", "quote": "Dizziness since Tuesday"},
        {"kind": "med", "name": "unobtainium", "quote": "Took my Inderal"},
        {"kind": "symptom", "name": "dizziness", "date_phrase": "when the moon is full", "quote": "Dizziness since Tuesday"}])
    assert [r.reason for r in rej] == ["schema", "schema", "unknown_symptom", "unknown_med", "unresolvable_date"]


def test_anthropic_extractor_parses_tool_use_with_a_fake_client():
    block = SimpleNamespace(type="tool_use", input={"events": [{"kind": "symptom", "name": "dizziness", "quote": "Dizziness"}]})
    seen = {}

    class FakeMessages:
        def create(self, **kw):
            seen.update(kw)
            return SimpleNamespace(content=[block], usage=SimpleNamespace(input_tokens=120, output_tokens=30))

    ex = AnthropicExtractor("claude-haiku-5-5", client=SimpleNamespace(messages=FakeMessages()))
    raw = ex.extract(MSG, CTX)
    assert raw.events and raw.input_tokens == 120 and raw.output_tokens == 30
    assert seen["tool_choice"] == {"type": "tool", "name": "record_events"}
    assert "<message>" in seen["messages"][0]["content"]  # the message is wrapped as data


def test_api_errors_are_recorded_not_raised():
    class Boom:
        def create(self, **kw):
            raise RuntimeError("down")

    raw = AnthropicExtractor("m", client=SimpleNamespace(messages=Boom())).extract(MSG, CTX)
    assert raw.events == [] and "down" in raw.error
