"""Test doubles shared by several test modules."""

import io
from collections.abc import Iterator
from types import SimpleNamespace
from typing import Any

import chess
import chess.pgn
from anthropic.types.beta import (
    BetaContentBlock,
    BetaFallbackBlock,
    BetaMessage,
    BetaTextBlock,
    BetaThinkingBlock,
    BetaToolUseBlock,
    BetaUsage,
)

from teachess.engine.models import CHECKMATE_CP, PositionEval

SCHOLAR_PGN = "1. e4 { [%clk 0:10:00] } e5 { [%clk 0:09:58] } 2. Qh5 Nc6 3. Bc4 Nf6 4. Qxf7# 1-0"


def ev(cp: int | None = None, best: str | None = None, mate: int | None = None) -> PositionEval:
    return PositionEval(cp=cp, mate=mate, best_move=best, pv=(best,) if best else (), depth=10)


# Scripted evaluations indexed by the number of plies played so far.
SCRIPT = [
    ev(30, "e2e4"),
    ev(30, "e7e5"),
    ev(30, "g1f3"),
    ev(-100, "b8c6"),  # after 2. Qh5: -130 cp, ~12 win-% points for White: an inaccuracy
    ev(-100, "f1c4"),
    ev(-100, "g7g6"),
    ev(mate=1, best="h5f7"),  # after 3... Nf6??: mate in one for White
    ev(CHECKMATE_CP),  # checkmate on the board
]


class ScriptedEngine:
    def __init__(self) -> None:
        self.calls = 0

    def analyse(self, board: chess.Board, depth: int) -> PositionEval:
        self.calls += 1
        return SCRIPT[board.ply()]


def read(pgn: str) -> chess.pgn.Game:
    game = chess.pgn.read_game(io.StringIO(pgn))
    assert game is not None
    return game


# --- Anthropic API doubles -------------------------------------------------------


def text_block(text: str) -> BetaContentBlock:
    return BetaTextBlock.model_construct(type="text", text=text, citations=None)


def tool_block(tool_id: str, name: str, arguments: object) -> BetaContentBlock:
    return BetaToolUseBlock.model_construct(type="tool_use", id=tool_id, name=name, input=arguments)


def thinking_block() -> BetaContentBlock:
    return BetaThinkingBlock.model_construct(type="thinking", thinking="", signature="sig")


def fallback_block() -> BetaContentBlock:
    return BetaFallbackBlock.model_construct(type="fallback")


def api_message(*blocks: BetaContentBlock, stop_reason: str = "end_turn") -> BetaMessage:
    usage = BetaUsage.model_construct(
        input_tokens=100,
        output_tokens=20,
        cache_read_input_tokens=80,
        cache_creation_input_tokens=0,
    )
    return BetaMessage.model_construct(
        type="message", role="assistant", content=list(blocks), stop_reason=stop_reason, usage=usage
    )


class FakeStream:
    def __init__(self, message: BetaMessage):
        self._message = message

    def __enter__(self) -> "FakeStream":
        return self

    def __exit__(self, *exc: object) -> None:
        return None

    @property
    def text_stream(self) -> Iterator[str]:
        for block in self._message.content:
            if block.type == "text":
                yield block.text

    def get_final_message(self) -> BetaMessage:
        return self._message


class FakeAnthropic:
    """Replays scripted responses and records every request."""

    def __init__(self, *responses: BetaMessage):
        self._responses = list(responses)
        self.requests: list[dict[str, Any]] = []
        self.beta = SimpleNamespace(messages=SimpleNamespace(stream=self._stream))

    def _stream(self, **kwargs: Any) -> FakeStream:
        self.requests.append({**kwargs, "messages": list(kwargs["messages"])})
        return FakeStream(self._responses.pop(0))
