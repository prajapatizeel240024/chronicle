"""Strict Pydantic schema for what the extraction model must return."""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class ExtractedEvent(BaseModel):
    model_config = ConfigDict(extra="forbid")

    kind: Literal["symptom", "med"]
    name: str = Field(description="Symptom: one of the allowed symptom names. Med: the drug name exactly as the patient said it (brand or generic).")
    body_site: str | None = Field(None, description="Body site if the patient named one, else null.")
    severity: int | None = Field(None, ge=0, le=10, description="0-10 using the written anchors. Null if the patient gave no level, if negated, or for meds.")
    date_phrase: str = Field("today", description="The patient's own words for WHEN (e.g. 'today', 'since Tuesday', 'last night'). Never a calendar date you computed.")
    negated: bool = Field(False, description="True when the patient says they do NOT have it.")
    subject: Literal["self", "other"] = Field("self", description="'other' if the symptom belongs to someone else (mum, partner, friend).")
    reality: Literal["real", "hypothetical"] = Field("real", description="'hypothetical' for if/might/what-if statements.")
    condition: str = Field("unattributed", description="A condition id from the patient's list ONLY if the patient themselves links the symptom to it; otherwise 'unattributed'.")
    med_action: Literal["start", "stop", "take", "change"] | None = Field(None, description="For meds only.")
    dose: str | None = None
    triggers: list[str] = Field(default_factory=list, description="Triggers the patient names, in their words.")
    quote: str = Field(description="The EXACT words from the message that support this event, copied verbatim.")


class ExtractionResult(BaseModel):
    model_config = ConfigDict(extra="forbid")
    events: list[ExtractedEvent] = Field(default_factory=list)


@dataclass
class Message:
    msg_id: str
    patient_id: str
    sent_date: date
    channel: Literal["text", "voice"]
    text: str


@dataclass
class PatientContext:
    patient_id: str
    conditions: list[str]  # condition ids
    meds: list[str] = field(default_factory=list)  # generic names, for safety context


@dataclass
class Event:
    """A validated event: everything the code has checked and normalised."""
    msg_id: str
    kind: str
    name: str                      # canonical symptom or generic med name
    body_site: str | None
    severity: int | None
    event_date: date
    negated: bool
    subject: str
    reality: str
    condition: str
    med_action: str | None
    dose: str | None
    triggers: list[str]            # normalised tags
    quote: str
    quote_start: int
    quote_end: int
    med_as_said: str | None = None


@dataclass
class Reject:
    msg_id: str
    reason: str                    # schema | quote_not_verbatim | unknown_symptom | unknown_med | unresolvable_date
    raw: dict
