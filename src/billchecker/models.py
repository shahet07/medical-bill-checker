"""Structured schemas for bills, EOBs, and flags.

These models are the contract between LLM extraction and the rules engine.
Extraction output must validate against Bill / Eob before any rule runs.
Money is always Decimal; dates are ISO dates validated on parse.
"""

from datetime import date
from decimal import Decimal
from typing import Annotated, List, Literal, Optional

from pydantic import BaseModel, ConfigDict, Field, model_validator

Money = Annotated[Decimal, Field(max_digits=12, decimal_places=2)]
Page = Annotated[int, Field(ge=1)]


class _Model(BaseModel):
    # extra="forbid" makes LLM output with invented fields fail validation.
    model_config = ConfigDict(extra="forbid", frozen=True)


class SourceRef(_Model):
    """Where a value was found in the uploaded document."""

    page: Page
    text: str = Field(min_length=1)


class DateRange(_Model):
    start: Optional[date]
    end: Optional[date]

    @model_validator(mode="after")
    def _ordered(self) -> "DateRange":
        if self.start and self.end and self.start > self.end:
            raise ValueError("dates_of_service.start is after end")
        return self


# --- Bill -------------------------------------------------------------------

CodeType = Literal["CPT", "HCPCS", "REV", "OTHER"]


class LineItem(_Model):
    line_id: str = Field(pattern=r"^L\d+$")
    service_date: Optional[date]
    description: str
    code: Optional[str]
    code_type: Optional[CodeType]
    units: Optional[Decimal]
    charge: Money
    source_page: Page
    source_text: str = Field(min_length=1)


class BillTotals(_Model):
    billed: Optional[Money]
    adjustments: Optional[Money]
    patient_balance: Optional[Money]
    source: Optional[SourceRef]


class Bill(_Model):
    schema_version: Literal["1.0"]
    provider_name: Optional[str]
    account_number_redacted: Optional[str]
    statement_date: Optional[date]
    dates_of_service: DateRange
    line_items: List[LineItem]
    totals: BillTotals
    itemized: bool
    # Explicit text on the bill saying the service was out of network, if any.
    out_of_network_marker: Optional[SourceRef]
    extraction_confidence: Literal["high", "medium", "low"]

    @model_validator(mode="after")
    def _unique_line_ids(self) -> "Bill":
        ids = [li.line_id for li in self.line_items]
        if len(ids) != len(set(ids)):
            raise ValueError("duplicate line_id in line_items")
        return self


# --- EOB --------------------------------------------------------------------

EobStatus = Literal["processed", "denied", "not_processed", "unknown"]
NetworkStatus = Literal["in_network", "out_of_network", "unknown"]


class EobLine(_Model):
    line_id: str = Field(pattern=r"^E\d+$")
    service_date: Optional[date]
    code: Optional[str]
    billed: Optional[Money]
    allowed: Optional[Money]
    insurer_paid: Optional[Money]
    patient_responsibility: Optional[Money]
    status: EobStatus
    denial_reason: Optional[str]
    network_status: NetworkStatus
    source_page: Page
    source_text: str = Field(min_length=1)


class EobTotals(_Model):
    patient_responsibility: Optional[Money]
    source: Optional[SourceRef]


class Eob(_Model):
    schema_version: Literal["1.0"]
    insurer: Optional[str]
    claim_id: Optional[str]
    service_lines: List[EobLine]
    totals: EobTotals

    @model_validator(mode="after")
    def _unique_line_ids(self) -> "Eob":
        ids = [sl.line_id for sl in self.service_lines]
        if len(ids) != len(set(ids)):
            raise ValueError("duplicate line_id in service_lines")
        return self


# --- Flags ------------------------------------------------------------------

RuleName = Literal[
    "duplicate_line",
    "balance_mismatch",
    "billed_after_denial",
    "network_mismatch",
    "no_itemization",
    "not_on_eob",
    "charge_mismatch",
    "payment_not_applied",
    "unbundled_pair",
    "credit_balance",
]


class Evidence(_Model):
    source: Literal["bill", "eob"]
    ref: str  # line_id, or "totals" / "network_marker"
    page: Optional[int]
    text: str


class Flag(_Model):
    # Deterministic: rule name plus the refs it points at, so reruns are stable.
    flag_id: str
    rule: RuleName
    # review: money may be owed back or not owed; worth contacting the provider.
    # check: something to read and verify before acting.
    severity: Literal["review", "check"]
    confidence: Literal["high", "medium", "low"]
    summary: str  # templated, never LLM-written
    evidence: List[Evidence] = Field(min_length=1)
