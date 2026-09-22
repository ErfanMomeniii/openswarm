"""Tests for turning an agent's questions into an answerable form."""

from __future__ import annotations

from openswarm.cli.questions import Question, ask_questions, format_answers, parse_questions

CHATBOT_REPLY = """I'll help you create a chatbot. First, I need to understand your requirements:

1. What kind of chatbot do you need? (e.g., customer support, FAQ, conversational companion)

2. What platform should it run on? (e.g., web interface, command line, Discord)

Please provide these details so I can implement the appropriate chatbot.
"""


def test_questions_and_their_suggestions_are_extracted():
    questions = parse_questions(CHATBOT_REPLY)

    assert [q.text for q in questions] == [
        "What kind of chatbot do you need?",
        "What platform should it run on?",
    ]
    assert questions[0].options == ["customer support", "FAQ", "conversational companion"]


def test_numbered_steps_are_not_questions():
    """A plan is not a form; only offer the form when something was asked."""
    assert parse_questions("Steps:\n1. Install it\n2. Run the tests") == []


def test_ordinary_answers_are_left_alone():
    assert parse_questions("Done. The function is in utils.py.") == []


def test_questions_without_suggestions_still_parse():
    questions = parse_questions("1. What should the module be called?")

    assert questions[0].text == "What should the module be called?"
    assert questions[0].options == []


# --- the form ---


def _run(questions, choices, typed=""):
    """Drive the form with a scripted sequence of menu choices."""
    picks = iter(choices)
    return ask_questions(
        questions,
        chooser=lambda options: next(picks),
        prompt=lambda label: typed,
    )


def test_choosing_suggestions_then_sending():
    questions = [
        Question("Platform?", ["web", "cli"]),
        Question("Database?", ["sqlite", "postgres"]),
    ]

    # first suggestion, second suggestion, then "Send these answers"
    result = _run(questions, [0, 1, 0])

    assert "1. Platform?\n   web" in result
    assert "2. Database?\n   postgres" in result


def test_typing_your_own_answer():
    questions = [Question("Platform?", ["web", "cli"])]

    result = _run(questions, [2, 0], typed="a Telegram bot")  # index 2 = "Type my own"

    assert "a Telegram bot" in result


def test_skipping_a_question():
    questions = [Question("Platform?", ["web"])]

    result = _run(questions, [2, 0])  # index 2 here = "Skip this one"

    assert result == "1. Platform?\n   "


def test_going_back_to_change_an_answer():
    """A wrong answer two questions ago must be fixable before sending."""
    questions = [
        Question("Platform?", ["web", "cli"]),
        Question("Database?", ["sqlite", "postgres"]),
    ]

    # web, sqlite, "Go back and change one", postgres, send
    result = _run(questions, [0, 0, 1, 1, 0])

    assert "postgres" in result
    assert "sqlite" not in result


def test_back_from_the_second_question():
    questions = [Question("A?", ["a1", "a2"]), Question("B?", ["b1"])]

    # a1, then "< Back" (last option), then a2, then b1, then send
    result = _run(questions, [0, 3, 1, 0, 0])

    assert "a2" in result


def test_cancelling_returns_nothing():
    questions = [Question("Platform?", ["web"])]

    assert _run(questions, [0, 2]) is None  # answer, then Cancel


def test_escaping_a_question_returns_nothing():
    questions = [Question("Platform?", ["web"])]

    assert _run(questions, [None]) is None


def test_format_answers_is_readable():
    text = format_answers([(Question("Platform?"), "web"), (Question("DB?"), "sqlite")])

    assert text == "1. Platform?\n   web\n2. DB?\n   sqlite"


# --- requests for details, which carry no question mark ---

PROVIDE_REPLY = """I'd be happy to create a text file for you. Could you please provide:
1. The filename (e.g., myfile.txt)
2. The content you'd like in the file
"""


def test_please_provide_lists_are_questions():
    """Agents ask for details without ever typing a question mark."""
    questions = parse_questions(PROVIDE_REPLY)

    assert [q.text for q in questions] == [
        "The filename?",
        "The content you'd like in the file?",
    ]
    assert questions[0].options == ["myfile.txt"]


def test_other_request_wordings_are_caught():
    for lead_in in ("I need the following:", "Please specify:", "Let me know:"):
        assert parse_questions(f"{lead_in}\n1. The filename\n2. The content")


def test_a_plan_after_a_colon_is_still_not_a_question():
    """'Here are the steps:' must not turn a plan into a form."""
    assert parse_questions("Here are the steps:\n1. Install it\n2. Run the tests") == []
    assert parse_questions("I will do the following:\n1. Write it\n2. Test it") == []


# --- the structured path: agents state their questions outright ---

ASK_USER = """{"action": "ask_user", "questions": [
  {"question": "Which filename?", "options": ["notes.txt", "output.txt"]},
  {"question": "What should it contain?"}
]}"""


def test_structured_questions_are_preferred():
    """No guessing: the agent said what it wants to know and what the answers might be."""
    questions = parse_questions(ASK_USER)

    assert [q.text for q in questions] == ["Which filename?", "What should it contain?"]
    assert questions[0].options == ["notes.txt", "output.txt"]
    assert questions[1].options == []


def test_structured_questions_survive_a_truncated_reply():
    """Models drop closing braces; the salvage path still finds the questions."""
    truncated = '{"action": "ask_user", "questions": [{"question": "Which filename?"}]'

    assert [q.text for q in parse_questions(truncated)] == ["Which filename?"]


def test_plain_string_questions_are_accepted():
    payload = '{"action": "ask_user", "questions": ["Which filename?", "  "]}'

    assert [q.text for q in parse_questions(payload)] == ["Which filename?"]


def test_other_actions_are_not_questions():
    assert parse_questions('{"action": "respond", "content": "1. Done\\n2. Also done"}') == []
