"""Conversational coach: a tool-use loop over the Claude Messages API.

The loop is ours (not a hosted agent) so tools run locally against SQLite and Stockfish,
inputs are validated before running, and the number of tool calls per turn is bounded.
Input and output go through callbacks, so the same class can back the CLI now and an API
later.
"""

from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any, cast

import anthropic
from anthropic.types.beta import BetaContentBlock, BetaMessage, BetaMessageParam

from teachess.coach.prompts import SYSTEM_PROMPT
from teachess.coach.tools import TOOL_DEFINITIONS, CoachToolbox, ToolResult
from teachess.config import Effort

FALLBACK_BETA = "server-side-fallback-2026-07-01"
MAX_TOKENS = 16000
MAX_TOOL_ROUNDS = 8

_TOOL_LIMIT_MESSAGE = (
    "Límite de consultas alcanzado en este turno. Responde con los datos que ya tienes y, "
    "si falta algo, dilo."
)
_TRUNCATED_MESSAGE = "La entrada de la herramienta llegó cortada; vuelve a intentarlo."
# Blocks that must not be echoed when they appear before a mid-output fallback boundary.
_PRE_FALLBACK_DROP = {"thinking", "redacted_thinking", "tool_use", "server_tool_use"}


@dataclass(frozen=True)
class CoachConfig:
    model: str
    effort: Effort
    fallbacks: bool = True  # server-side retry on another model if the request is declined
    max_tokens: int = MAX_TOKENS
    max_tool_rounds: int = MAX_TOOL_ROUNDS


@dataclass
class Usage:
    input_tokens: int = 0
    output_tokens: int = 0
    cache_read_tokens: int = 0
    cache_write_tokens: int = 0

    def add(self, message: BetaMessage) -> None:
        usage = message.usage
        self.input_tokens += usage.input_tokens
        self.output_tokens += usage.output_tokens
        self.cache_read_tokens += usage.cache_read_input_tokens or 0
        self.cache_write_tokens += usage.cache_creation_input_tokens or 0


@dataclass(frozen=True)
class CoachReply:
    text: str
    refused: bool = False  # declined by the model (and by the fallback, if enabled)
    truncated: bool = False  # hit max_tokens
    tool_calls: list[str] = field(default_factory=list)


TextCallback = Callable[[str], None]
ToolCallback = Callable[[str], None]


def _ignore(_: str) -> None:
    return None


class Coach:
    """One coaching conversation about one game."""

    def __init__(
        self,
        client: anthropic.Anthropic,
        toolbox: CoachToolbox,
        config: CoachConfig,
        context: str,
    ):
        self._client = client
        self._toolbox = toolbox
        self._config = config
        self._context = context
        self._messages: list[BetaMessageParam] = []
        self.usage = Usage()

    def ask(
        self, question: str, on_text: TextCallback = _ignore, on_tool: ToolCallback = _ignore
    ) -> CoachReply:
        """Send one user message and run tools until the coach answers."""
        checkpoint = len(self._messages)
        content: list[dict[str, str]] = []
        if not self._messages:
            content.append({"type": "text", "text": self._context})
        content.append({"type": "text", "text": question})
        self._messages.append(cast(BetaMessageParam, {"role": "user", "content": content}))

        texts: list[str] = []
        tool_calls: list[str] = []
        printer = _ParagraphPrinter(on_text)
        rounds = 0
        while True:
            response = self._request(printer)
            self.usage.add(response)
            if response.stop_reason == "refusal":
                # Nothing usable came back: forget this exchange so the user can rephrase.
                del self._messages[checkpoint:]
                return CoachReply(text="".join(texts), refused=True, tool_calls=tool_calls)

            blocks = echoable_content(response.content)
            self._messages.append(cast(BetaMessageParam, {"role": "assistant", "content": blocks}))
            texts.extend(b.text for b in blocks if b.type == "text")
            tool_uses = [b for b in blocks if b.type == "tool_use"]

            if response.stop_reason == "pause_turn":
                continue
            if not tool_uses:
                return CoachReply(
                    text="".join(texts),
                    truncated=response.stop_reason == "max_tokens",
                    tool_calls=tool_calls,
                )

            rounds += 1
            results = []
            for block in tool_uses:
                if response.stop_reason == "max_tokens":
                    result = ToolResult(_TRUNCATED_MESSAGE, is_error=True)
                elif rounds > self._config.max_tool_rounds:
                    result = ToolResult(_TOOL_LIMIT_MESSAGE, is_error=True)
                else:
                    on_tool(block.name)
                    tool_calls.append(block.name)
                    result = self._toolbox.run(block.name, block.input)
                results.append(
                    {
                        "type": "tool_result",
                        "tool_use_id": block.id,
                        "content": result.content,
                        "is_error": result.is_error,
                    }
                )
            # All results of one turn go back in a single user message.
            self._messages.append(cast(BetaMessageParam, {"role": "user", "content": results}))
            if rounds > self._config.max_tool_rounds + 1:
                return CoachReply(text="".join(texts), tool_calls=tool_calls)

    def _request(self, printer: "_ParagraphPrinter") -> BetaMessage:
        extra: dict[str, Any] = {}
        if self._config.fallbacks:
            extra = {"betas": [FALLBACK_BETA], "fallbacks": "default"}
        printer.new_message()
        with self._client.beta.messages.stream(
            model=self._config.model,
            max_tokens=self._config.max_tokens,
            system=SYSTEM_PROMPT,
            tools=cast(Any, TOOL_DEFINITIONS),
            messages=self._messages,
            output_config={"effort": self._config.effort},
            cache_control={"type": "ephemeral"},
            **extra,
        ) as stream:
            for text in stream.text_stream:
                printer.write(text)
            return stream.get_final_message()


def echoable_content(content: list[BetaContentBlock]) -> list[BetaContentBlock]:
    """Blocks to send back in the history.

    After a mid-output fallback, thinking and tool-use blocks before the last `fallback`
    block must be dropped (they belong to the declined attempt); everything else is kept in
    place, including the `fallback` block itself.
    """
    boundary = max((i for i, b in enumerate(content) if b.type == "fallback"), default=-1)
    return [
        block
        for i, block in enumerate(content)
        if i >= boundary or block.type not in _PRE_FALLBACK_DROP
    ]


class _ParagraphPrinter:
    """Forwards streamed text, separating the text of consecutive messages in one turn."""

    def __init__(self, on_text: TextCallback):
        self._on_text = on_text
        self._printed = False
        self._pending_break = False

    def new_message(self) -> None:
        self._pending_break = self._printed

    def write(self, text: str) -> None:
        if self._pending_break:
            self._on_text("\n\n")
            self._pending_break = False
        self._on_text(text)
        self._printed = True
