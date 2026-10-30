import json

import pytest

from billchecker.explanation import MAX_LINE_CHARS, SCHEMA, check, explain
from billchecker.llm import LLMResponse, LLMUnavailable
from billchecker.models import Bill, Eob
from billchecker.rules import run_rules
from conftest import FakeLLM
from synthetic import CASES, expected_bill, expected_eob

BY_NAME = {c.name: c for c in CASES}

GOOD_LINES = {
    "L1": "A visit with a doctor you have seen before.",
    "L2": "A common blood test that counts your blood cells.",
    "L3": "Drawing blood from a vein for lab tests.",
}


def load(name):
    case = BY_NAME[name]
    bill = Bill.model_validate(expected_bill(case.bill))
    eob = Eob.model_validate(expected_eob(case.eob)) if case.eob else None
    return bill, run_rules(bill, eob)


def output(lines=None, flags=None):
    return {
        "lines": [{"line_id": k, "explanation": v} for k, v in (lines or {}).items()],
        "flags": [{"flag_id": k, "explanation": v} for k, v in (flags or {}).items()],
    }


class RaisingLLM:
    def generate(self, system, content, schema):
        raise LLMUnavailable("down")


# --- Happy path ---------------------------------------------------------------------


def test_good_explanations_are_used():
    bill, flags = load("denial")
    flag_text = {f.flag_id: "Your bill and your insurer's statement disagree here, so it is worth a look." for f in flags}
    llm = FakeLLM(output(GOOD_LINES, flag_text))
    result = explain(bill, flags, llm)
    assert result.problems == []
    assert {k: v.text for k, v in result.lines.items()} == GOOD_LINES
    assert all(v.source == "llm" for v in list(result.lines.values()) + list(result.flags.values()))
    assert set(result.flags) == {f.flag_id for f in flags}


def test_request_sends_only_lines_and_flags():
    bill, flags = load("denial")
    llm = FakeLLM(output(GOOD_LINES))
    explain(bill, flags, llm)
    [call] = llm.calls
    assert call["schema"] is SCHEMA
    text = call["content"][0]["text"]
    data = json.loads(text[text.index("<data>") + 6 : text.index("</data>")])
    assert [li["line_id"] for li in data["lines"]] == ["L1", "L2", "L3"]
    assert {f["flag_id"] for f in data["flags"]} == {f.flag_id for f in flags}
    assert "5432" not in text and "Riverside" not in text  # no account number or provider


def test_empty_bill_makes_no_call():
    bill, _ = load("summary")
    llm = FakeLLM()
    result = explain(bill, [], llm)
    assert result.lines == {} and result.flags == {} and llm.calls == []


# --- Per-item guardrails ------------------------------------------------------------


def test_invented_amount_falls_back_for_that_line_only():
    bill, _ = load("clean")
    lines = dict(GOOD_LINES, L2="A blood test that usually costs about $25.")
    result = explain(bill, [], FakeLLM(output(lines)))
    assert result.lines["L2"].source == "template"
    assert result.lines["L2"].text == 'Listed on your bill as "Complete blood count".'
    assert result.lines["L1"].source == "llm" and result.lines["L3"].source == "llm"
    assert result.problems == ["L2: unsupported_number"]


def test_numbers_from_the_items_own_data_are_allowed():
    bill, _ = load("clean")
    lines = dict(GOOD_LINES, L1="An office visit, billed at $150.00 for 1 unit.")
    assert explain(bill, [], FakeLLM(output(lines))).lines["L1"].source == "llm"


def test_number_from_another_line_is_not_allowed():
    bill, _ = load("clean")
    lines = dict(GOOD_LINES, L1="An office visit. The blood test after it was $40.00.")
    assert explain(bill, [], FakeLLM(output(lines))).lines["L1"].source == "template"


@pytest.mark.parametrize(
    "text",
    [
        "You don't owe this charge.",
        "You don’t owe this charge.",
        "This test was not medically necessary.",
        "This charge is an error by the clinic.",
        "This looks like fraud.",
        "You may want to talk to a lawyer.",
    ],
)
def test_advice_or_accusation_falls_back(text):
    bill, _ = load("clean")
    result = explain(bill, [], FakeLLM(output(dict(GOOD_LINES, L1=text))))
    assert result.lines["L1"].source == "template"
    assert result.problems == ["L1: blocked_phrase"]


def test_harmless_words_containing_blocked_ones_pass():
    assert check("This issue is worth a closer look.", set(), 500) is None


def test_too_long_and_empty_fall_back():
    bill, _ = load("clean")
    lines = dict(GOOD_LINES, L1="word " * (MAX_LINE_CHARS // 4), L2="   ")
    result = explain(bill, [], FakeLLM(output(lines)))
    assert sorted(result.problems) == ["L1: too_long", "L2: empty"]


def test_missing_items_fall_back_and_unknown_ids_are_ignored():
    bill, flags = load("duplicate")
    lines = {"L1": GOOD_LINES["L1"], "L99": "Not a real line."}
    result = explain(bill, flags, FakeLLM(output(lines, {"made_up_flag": "Something else is wrong."})))
    assert set(result.lines) == {"L1", "L2", "L3", "L4"}
    assert "L99" not in result.lines and "made_up_flag" not in result.flags
    assert result.lines["L2"].source == "template"
    [flag] = flags
    assert result.flags[flag.flag_id].text == flag.summary  # template is the flag's own summary
    assert "L2: missing" in result.problems


def test_flag_explanation_may_use_amounts_from_its_own_evidence():
    bill, flags = load("balance")
    [flag] = flags
    ok = {flag.flag_id: "Your bill asks for $95.00, but your insurer says you owe $40.00. It is worth asking why."}
    assert explain(bill, flags, FakeLLM(output(GOOD_LINES, ok))).flags[flag.flag_id].source == "llm"
    bad = {flag.flag_id: "Your bill asks for $95.00, but you probably owe $10.00."}
    assert explain(bill, flags, FakeLLM(output(GOOD_LINES, bad))).flags[flag.flag_id].source == "template"


def test_llm_cannot_change_the_set_of_flags():
    bill, flags = load("denial")
    result = explain(bill, flags, FakeLLM(output(GOOD_LINES, {})))
    assert set(result.flags) == {f.flag_id for f in flags}


# --- Whole-call failures --------------------------------------------------------------


@pytest.mark.parametrize(
    "llm, problem",
    [
        (RaisingLLM(), "llm_unavailable"),
        (FakeLLM(LLMResponse(text=None, stop_reason="refusal")), "llm_refusal"),
        (FakeLLM(LLMResponse(text='{"lines": [', stop_reason="max_tokens")), "llm_max_tokens"),
        (FakeLLM("not json"), "invalid_output"),
        (FakeLLM({"lines": [], "flags": [], "extra": 1}), "invalid_output"),
    ],
)
def test_call_failures_fall_back_to_templates(llm, problem):
    bill, flags = load("denial")
    result = explain(bill, flags, llm)
    assert result.problems == [problem]
    assert all(v.source == "template" for v in list(result.lines.values()) + list(result.flags.values()))
    assert set(result.lines) == {"L1", "L2", "L3"}


def test_problems_never_contain_document_text_or_amounts():
    bill, flags = load("denial")
    lines = {k: "It costs $999.99 per Complete blood count." for k in GOOD_LINES}
    result = explain(bill, flags, FakeLLM(output(lines)))
    for p in result.problems:
        assert "$" not in p and "999" not in p and "blood" not in p.lower()


# --- Spanish ------------------------------------------------------------------------------

from typing import get_args  # noqa: E402

from billchecker.explanation import FLAG_TEMPLATES_ES  # noqa: E402
from billchecker.models import RuleName  # noqa: E402


def test_spanish_prompt_and_templates():
    bill, flags = load("denial")
    llm = FakeLLM(LLMResponse(text=None, stop_reason="refusal"))
    result = explain(bill, flags, llm, language="es")
    assert "in Spanish" in llm.calls[0]["system"]
    assert result.lines["L2"].text == 'Aparece en su factura como "Complete blood count".'
    assert all(v.text in FLAG_TEMPLATES_ES.values() for v in result.flags.values())


def test_every_rule_has_a_spanish_template():
    assert set(FLAG_TEMPLATES_ES) == set(get_args(RuleName))


@pytest.mark.parametrize(
    "text",
    ["No pague este cargo.", "Esto parece un fraude.", "Hable con un abogado.", "No era médicamente necesario."],
)
def test_spanish_advice_is_blocked(text):
    bill, _ = load("clean")
    result = explain(bill, [], FakeLLM(output(dict(GOOD_LINES, L1=text))), language="es")
    assert result.lines["L1"].source == "template"
    assert result.lines["L1"].text.startswith("Aparece en su factura")


def test_good_spanish_passes():
    bill, _ = load("clean")
    lines = {"L1": "Una consulta con un médico que ya lo conoce.", "L2": "Un análisis de sangre común.", "L3": "La extracción de sangre de una vena."}
    result = explain(bill, [], FakeLLM(output(lines)), language="es")
    assert all(v.source == "llm" for v in result.lines.values())


def test_unknown_language_rejected():
    bill, _ = load("clean")
    with pytest.raises(ValueError):
        explain(bill, [], FakeLLM(), language="fr")
