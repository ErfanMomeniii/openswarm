"""Turn an agent's questions into an interactive form.

Agents routinely answer a vague request with a numbered list of questions. Making
the user retype prose answers is the worst part of that exchange, so the questions
are parsed out and offered as choices instead.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

#: "1. What platform?" / "2) Which database?" — the shape models actually produce.
#: The whole line is captured because the question mark is often followed by
#: suggestions in brackets.
NUMBERED_QUESTION = re.compile(r"^\s*\d+[.)]\s+(.+)$", re.MULTILINE)

#: Suggestions the model already offered: "(e.g., web, CLI, Discord)".
SUGGESTIONS = re.compile(r"\((?:e\.g\.|eg|such as|for example)[,:]?\s*(.+?)\)", re.IGNORECASE)

MAX_OPTIONS = 6

#: "Could you please provide:" / "I need the following:" — a request for details
#: whose items are questions even though none of them ends in a question mark.
REQUEST_LEAD_IN = re.compile(
    r"(provide|need|tell me|let me know|specify|clarify|confirm|share|send me)\b[^.!?]*:\s*$",
    re.IGNORECASE | re.MULTILINE,
)


def _is_request_list(reply: str) -> bool:
    """Whether the numbered items are things being asked of the user."""
    first_item = NUMBERED_QUESTION.search(reply)
    if not first_item:
        return False
    return bool(REQUEST_LEAD_IN.search(reply[: first_item.start()]))


@dataclass
class Question:
    text: str
    options: list[str] = field(default_factory=list)


def _structured_questions(reply: str) -> list[Question]:
    """Read questions an agent asked with the `ask_user` action.

    This is the reliable path: the agent states its questions and suggestions
    outright instead of the CLI guessing them out of prose.
    """
    from openswarm.workflow.parsing import parse_agent_response

    try:
        parsed = parse_agent_response(reply)
    except Exception:
        return []
    if parsed.get("action") != "ask_user":
        return []

    items = parsed.get("questions")
    if not items:
        # Truncated replies lose the nested list; the questions themselves are
        # still recoverable from the raw text.
        return [Question(text=text) for text in re.findall(r'"question"\s*:\s*"([^"]+)"', reply)]

    questions = []
    for item in items:
        if isinstance(item, dict) and item.get("question"):
            options = [str(o) for o in (item.get("options") or []) if str(o).strip()]
            questions.append(Question(text=str(item["question"]), options=options[:MAX_OPTIONS]))
        elif isinstance(item, str) and item.strip():
            questions.append(Question(text=item.strip()))
    return questions


def parse_questions(reply: str) -> list[Question]:
    """Pull numbered questions, and any suggestions they carry, out of a reply.

    Returns an empty list when the reply is not a question list, so callers can
    treat it as an ordinary answer.
    """
    structured = _structured_questions(reply)
    if structured:
        return structured

    questions: list[Question] = []
    requested = _is_request_list(reply)
    for raw in NUMBERED_QUESTION.findall(reply):
        if "?" not in raw and not requested:
            continue  # a numbered step, not a question
        suggestion = SUGGESTIONS.search(raw)
        options: list[str] = []
        if suggestion:
            options = [
                part.strip(" .")
                for part in re.split(r",| or ", suggestion.group(1))
                if part.strip(" .") and not part.strip().lower().startswith("etc")
            ][:MAX_OPTIONS]
            raw = raw[: suggestion.start()].strip()
        raw = raw.split("?")[0].strip().rstrip(":").strip() + "?"
        questions.append(Question(text=" ".join(raw.split()), options=options))
    return questions


def format_answers(answers: list[tuple[Question, str]]) -> str:
    """Compose the reply that goes back to the team."""
    return "\n".join(f"{i}. {q.text}\n   {a}" for i, (q, a) in enumerate(answers, 1))


def ask_questions(questions: list[Question], chooser=None, prompt=None) -> str | None:
    """Walk the user through the questions and return a composed reply.

    Every question offers the model's own suggestions, a free-text option, and a
    way back. The final step is a review, so a wrong answer three questions ago
    is still fixable. Returns None if the user backs all the way out.
    """
    from openswarm.cli.utils import choose, console

    pick = chooser or choose
    ask_text = prompt or (lambda label: console.input(f"[bold]{label}[/bold] "))

    answers: list[str] = [""] * len(questions)
    index = 0

    while True:
        if index >= len(questions):
            console.print("\n[bold]Your answers[/bold]")
            for i, (question, answer) in enumerate(zip(questions, answers, strict=True), 1):
                console.print(f"  [dim]{i}.[/dim] {question.text}")
                console.print(f"     [cyan]{answer or '(skipped)'}[/cyan]")
            choice = pick(["Send these answers", "Go back and change one", "Cancel"])
            if choice == 0:
                return format_answers(list(zip(questions, answers, strict=True)))
            if choice == 1:
                index = len(questions) - 1
                continue
            return None

        question = questions[index]
        console.print(f"\n[bold]{index + 1}/{len(questions)}  {question.text}[/bold]")

        options = [*question.options, "Type my own answer...", "Skip this one"]
        if index > 0:
            options.append("< Back")

        choice = pick(options)
        if choice is None:
            return None

        if choice < len(question.options):
            answers[index] = question.options[choice]
        elif choice == len(question.options):
            answers[index] = (ask_text("Your answer:") or "").strip()
        elif choice == len(question.options) + 1:
            answers[index] = ""
        else:
            index -= 1
            continue

        index += 1
