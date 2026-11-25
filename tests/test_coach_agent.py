import json
from typing import Any, cast

import anthropic

from teachess.coach.agent import FALLBACK_BETA, Coach, CoachConfig, echoable_content
from teachess.coach.prompts import SYSTEM_PROMPT, game_context
from teachess.coach.tools import CoachToolbox
from tests.fakes import (
    FakeAnthropic,
    api_message,
    fallback_block,
    text_block,
    thinking_block,
    tool_block,
)

CONFIG = CoachConfig(model="claude-opus-5-5", effort="medium")


def make_coach(toolbox: CoachToolbox, client: FakeAnthropic, config: CoachConfig = CONFIG) -> Coach:
    context = game_context(toolbox.game_summary(), toolbox.critical_moments("inaccuracy"))
    return Coach(cast(anthropic.Anthropic, client), toolbox, config, context)


def tool_results(request: dict[str, Any]) -> list[dict[str, Any]]:
    last = request["messages"][-1]
    assert last["role"] == "user"
    results: list[dict[str, Any]] = last["content"]
    assert all(r["type"] == "tool_result" for r in results)
    return results


def test_first_question_sends_context_and_request_settings(toolbox: CoachToolbox) -> None:
    client = FakeAnthropic(api_message(text_block("Hola, ")), api_message(text_block("Claro.")))
    coach = make_coach(toolbox, client)
    streamed: list[str] = []

    reply = coach.ask("¿Qué tal jugué?", on_text=streamed.append)

    assert reply.text == "Hola, " and streamed == ["Hola, "]
    request = client.requests[0]
    assert request["model"] == "claude-opus-5-5"
    assert request["system"] == SYSTEM_PROMPT
    assert request["output_config"] == {"effort": "medium"}
    assert request["cache_control"] == {"type": "ephemeral"}
    assert request["betas"] == [FALLBACK_BETA] and request["fallbacks"] == "default"
    assert [t["name"] for t in request["tools"]][0] == "get_game_summary"
    first = request["messages"][0]["content"]
    assert "<datos_partida>" in first[0]["text"] and "3...Nf6" in first[0]["text"]
    assert first[1]["text"] == "¿Qué tal jugué?"

    coach.ask("¿Y la apertura?")
    second = client.requests[1]["messages"]
    assert [m["role"] for m in second] == ["user", "assistant", "user"]
    assert second[2]["content"] == [{"type": "text", "text": "¿Y la apertura?"}]  # no context


def test_tool_calls_are_executed_and_answered_in_one_message(toolbox: CoachToolbox) -> None:
    fen = "r1bqkbnr/pppp1ppp/2n5/4p2Q/2B1P3/8/PPPP1PPP/RNB1K1NR b KQkq - 3 3"
    client = FakeAnthropic(
        api_message(
            text_block("Lo miro."),
            tool_block("t1", "evaluate_move", {"fen": fen, "move": "Nf6"}),
            tool_block("t2", "evaluate_position", {"fen": "garbage"}),
            stop_reason="tool_use",
        ),
        api_message(text_block("Nf6 permite mate.")),
    )
    coach = make_coach(toolbox, client)
    streamed: list[str] = []
    tools_seen: list[str] = []

    reply = coach.ask("¿Y Nf6?", on_text=streamed.append, on_tool=tools_seen.append)

    results = tool_results(client.requests[1])
    assert [r["tool_use_id"] for r in results] == ["t1", "t2"]
    assert json.loads(results[0]["content"])["classification"] == "blunder"
    assert results[0]["is_error"] is False
    assert results[1]["is_error"] is True and "FEN no válido" in results[1]["content"]
    assert tools_seen == reply.tool_calls == ["evaluate_move", "evaluate_position"]
    assert streamed == ["Lo miro.", "\n\n", "Nf6 permite mate."]
    assert reply.text == "Lo miro.Nf6 permite mate."
    assert coach.usage.input_tokens == 200 and coach.usage.cache_read_tokens == 160


def test_refusal_is_reported_and_forgotten(toolbox: CoachToolbox) -> None:
    client = FakeAnthropic(
        api_message(stop_reason="refusal"),
        api_message(text_block("Vale.")),
    )
    coach = make_coach(toolbox, client)

    assert coach.ask("pregunta rechazada").refused
    coach.ask("otra pregunta")
    messages = client.requests[1]["messages"]
    assert len(messages) == 1  # the refused exchange was dropped from the history
    assert "<datos_partida>" in messages[0]["content"][0]["text"]
    assert messages[0]["content"][1]["text"] == "otra pregunta"


def test_tool_rounds_are_bounded(toolbox: CoachToolbox) -> None:
    def summary_call(tool_id: str) -> Any:
        return api_message(tool_block(tool_id, "get_game_summary", {}), stop_reason="tool_use")

    client = FakeAnthropic(summary_call("a"), summary_call("b"), summary_call("c"))
    coach = make_coach(toolbox, client, CoachConfig("m", "low", max_tool_rounds=1))

    reply = coach.ask("bucle")

    assert reply.tool_calls == ["get_game_summary"]  # only the first round ran a tool
    assert len(client.requests) == 3
    assert "Límite de consultas" in tool_results(client.requests[2])[0]["content"]
    # The history stays valid: every tool_use has its tool_result.
    coach_history = coach._messages
    assert coach_history[-1]["role"] == "user"


def test_truncated_tool_input_is_not_executed(toolbox: CoachToolbox) -> None:
    client = FakeAnthropic(
        api_message(tool_block("t1", "evaluate_position", {"fe": ""}), stop_reason="max_tokens"),
        api_message(text_block("Hecho.")),
    )
    coach = make_coach(toolbox, client)

    reply = coach.ask("algo")

    assert reply.tool_calls == []
    assert "cortada" in tool_results(client.requests[1])[0]["content"]


def test_fallbacks_can_be_disabled(toolbox: CoachToolbox) -> None:
    client = FakeAnthropic(api_message(text_block("ok")))
    make_coach(toolbox, client, CoachConfig("m", "high", fallbacks=False)).ask("hola")
    assert "betas" not in client.requests[0] and "fallbacks" not in client.requests[0]


def test_echoable_content_drops_declined_attempt_blocks() -> None:
    before_text = text_block("parcial")
    blocks = [
        thinking_block(),
        before_text,
        tool_block("x", "get_game_summary", {}),
        fallback_block(),
        thinking_block(),
        text_block("sigue"),
    ]
    kept = echoable_content(blocks)
    assert [b.type for b in kept] == ["text", "fallback", "thinking", "text"]
    assert kept[0] is before_text
    no_fallback = [thinking_block(), text_block("hola")]
    assert echoable_content(no_fallback) == no_fallback
