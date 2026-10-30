"""The MCP server, driven through a real MCP client connected in memory."""

import io
import json
from datetime import date

import pdfplumber
import pytest
from mcp import Client

from billchecker.mcp_server import build_server
from conftest import FakeLLM
from synthetic import CASES, expected_bill, expected_eob

BY_NAME = {c.name: c for c in CASES}
NO_EXPLAIN = {"lines": [], "flags": []}


@pytest.fixture
def anyio_backend():
    return "asyncio"


@pytest.fixture
def files(fixture_files):
    return {f.path.name: str(f.path) for f in fixture_files}


def server_with(*responses, factory=None):
    llm = FakeLLM(*responses)
    return build_server(llm_factory=factory or (lambda: llm), today=lambda: date(2026, 4, 15)), llm


async def call(server, tool, **args):
    async with Client(server) as client:
        return await client.call_tool(tool, args)


def data(result):
    assert not result.is_error, result.content[0].text
    return result.structured_content or json.loads(result.content[0].text)


def error_text(result):
    assert result.is_error
    return result.content[0].text


# --- Discovery ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_lists_tools_resources_and_prompt():
    server, _ = server_with()
    async with Client(server) as client:
        tools = {t.name: t for t in (await client.list_tools()).tools}
        assert set(tools) == {"check_bill", "check_extracted_bill", "create_letter", "search_guides"}
        assert tools["check_extracted_bill"].annotations.read_only_hint is True
        assert tools["create_letter"].annotations.read_only_hint is False
        uris = {str(r.uri) for r in (await client.list_resources()).resources}
        assert uris == {"billchecker://schema/bill", "billchecker://schema/eob"}
        schema = json.loads((await client.read_resource("billchecker://schema/bill")).contents[0].text)
        assert "line_items" in schema["properties"]
        prompt = await client.get_prompt("review_bill", {"bill_file": "~/bill.pdf"})
        assert "check_bill" in prompt.messages[0].content.text
        assert "not confirmed errors" in client.instructions or "not confirmed errors" in (client.instructions or "")


# --- check_bill ------------------------------------------------------------------------------


@pytest.mark.anyio
async def test_check_bill_reads_files_and_flags(files):
    case = BY_NAME["denial"]
    server, llm = server_with(expected_bill(case.bill), expected_eob(case.eob), NO_EXPLAIN)
    out = data(await call(server, "check_bill", bill_files=[files["denial_bill.pdf"]], eob_files=[files["denial_eob.pdf"]]))
    assert out["status"] == "ok" and out["eob_status"] == "ok"
    assert sorted(f["rule"] for f in out["flags"]) == ["balance_mismatch", "billed_after_denial"]
    assert set(out["explanations"]["lines"]) == {"L1", "L2", "L3"}
    assert len(llm.calls) == 3  # bill, EOB, explanations


@pytest.mark.anyio
async def test_check_bill_photo_in_spanish_without_explanations(files):
    case = BY_NAME["clean"]
    server, llm = server_with(expected_bill(case.bill))
    out = data(await call(server, "check_bill", bill_files=[files["clean_bill_photo.jpg"]], language="es", explain_lines=False))
    assert out["flags"] == [] and out["explanations"] is None and len(llm.calls) == 1


@pytest.mark.anyio
async def test_check_bill_errors_are_clear(files, tmp_path):
    server, _ = server_with()
    assert "not found" in error_text(await call(server, "check_bill", bill_files=[str(tmp_path / "nope.pdf")]))
    bad = tmp_path / "notes.txt"
    bad.write_text("hello")
    assert "PDF, JPG, PNG" in error_text(await call(server, "check_bill", bill_files=[str(bad)]))

    def no_key():
        raise RuntimeError("missing key")

    server, _ = server_with(factory=no_key)
    msg = error_text(await call(server, "check_bill", bill_files=[files["clean_bill.pdf"]]))
    assert "check_extracted_bill" in msg

    server, _ = server_with("garbage", "garbage")
    assert "Could not read the bill" in error_text(await call(server, "check_bill", bill_files=[files["clean_bill.pdf"]]))


# --- check_extracted_bill ------------------------------------------------------------------------


@pytest.mark.anyio
async def test_check_extracted_bill_needs_no_llm():
    def no_llm():
        raise AssertionError("must not use the LLM")

    server, _ = server_with(factory=no_llm)
    case = BY_NAME["unpaid"]
    out = data(await call(server, "check_extracted_bill", bill=expected_bill(case.bill), eob=expected_eob(case.eob)))
    assert sorted(f["rule"] for f in out["flags"]) == ["balance_mismatch", "payment_not_applied"]


@pytest.mark.anyio
async def test_check_extracted_bill_reports_schema_errors():
    server, _ = server_with()
    bad = expected_bill(BY_NAME["clean"].bill)
    bad["line_items"][0]["charge"] = "150.005"
    del bad["itemized"]
    msg = error_text(await call(server, "check_extracted_bill", bill=bad))
    assert "line_items.0.charge" in msg and "itemized" in msg


# --- create_letter -------------------------------------------------------------------------


@pytest.mark.anyio
async def test_dispute_letter_with_selected_flags_and_pdf(tmp_path):
    case = BY_NAME["denial"]
    bill, eob = expected_bill(case.bill), expected_eob(case.eob)
    server, _ = server_with()
    flags = data(await call(server, "check_extracted_bill", bill=bill, eob=eob))["flags"]
    chosen = [f["flag_id"] for f in flags if f["rule"] == "billed_after_denial"]
    pdf = tmp_path / "letter.pdf"
    out = data(await call(server, "create_letter", kind="dispute", bill=bill, eob=eob, patient_name="Sam Example",
                          flag_ids=chosen, pdf_path=str(pdf)))
    assert "1. Charge for a service my insurer denied" in out["text"] and "Amount due does not match" not in out["text"]
    assert out["pdf_path"] == str(pdf)
    assert "Sam Example" in pdfplumber.open(io.BytesIO(pdf.read_bytes())).pages[0].extract_text()


@pytest.mark.anyio
async def test_dispute_cannot_include_flags_the_checks_did_not_raise():
    case = BY_NAME["clean"]
    server, _ = server_with()
    msg = error_text(await call(server, "create_letter", kind="dispute", bill=expected_bill(case.bill),
                                eob=expected_eob(case.eob), patient_name="Sam", flag_ids=["duplicate_line:bill.L1,bill.L2"]))
    assert "not raised" in msg
    msg = error_text(await call(server, "create_letter", kind="dispute", bill=expected_bill(case.bill),
                                eob=expected_eob(case.eob), patient_name="Sam"))
    assert "no flags" in msg


@pytest.mark.anyio
@pytest.mark.parametrize(
    "kind, extra, expect",
    [
        ("itemized_request", {}, "Request for an itemized bill"),
        ("financial_assistance", {}, "charity care policy"),
        ("payment_plan", {"monthly_amount": "$50"}, "I can pay $50.00 per month"),
        ("insurer_appeal", {"member_id": "M123"}, "Member ID: M123"),
    ],
)
async def test_other_letter_kinds(kind, extra, expect):
    case = BY_NAME["denial"]
    server, _ = server_with()
    out = data(await call(server, "create_letter", kind=kind, bill=expected_bill(case.bill), eob=expected_eob(case.eob),
                          patient_name="Sam Example", **extra))
    assert expect in out["text"]


@pytest.mark.anyio
async def test_pdf_path_safety(tmp_path):
    case = BY_NAME["summary"]
    server, _ = server_with()
    args = dict(kind="itemized_request", bill=expected_bill(case.bill), patient_name="Sam")
    assert "must end in .pdf" in error_text(await call(server, "create_letter", pdf_path=str(tmp_path / "x.txt"), **args))
    assert "does not exist" in error_text(await call(server, "create_letter", pdf_path=str(tmp_path / "no" / "x.pdf"), **args))
    existing = tmp_path / "keep.pdf"
    existing.write_bytes(b"mine")
    assert "already exists" in error_text(await call(server, "create_letter", pdf_path=str(existing), **args))
    assert existing.read_bytes() == b"mine"


# --- search_guides (RAG) ----------------------------------------------------------------------


@pytest.mark.anyio
async def test_search_guides_returns_sourced_passages():
    from billchecker.rag import KnowledgeBase

    server = build_server(llm_factory=lambda: None, knowledge=KnowledgeBase())
    out = data(await call(server, "search_guides", query="How long do I have to file an appeal?", limit=3))
    assert out["search_mode"] == "keyword" and len(out["passages"]) == 3
    top = out["passages"][0]
    assert "appeal" in top["title"].lower() and top["source_url"].startswith("https://")
    assert "search query" in error_text(await call(server, "search_guides", query="  "))
