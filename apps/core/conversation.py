from copy import deepcopy

from pydantic import BaseModel, Field

from .context import InferenceContext

class ChatMessage(BaseModel):
    role: str = Field(
        pattern="^(user|assistant|system)$",
    )
    content: str = Field(
        min_length=1,
        max_length=4096,
    )

class ConversationHistory:
    def __init__(
        self,
        max_turns: int = 10,
    ):
        if max_turns < 1:
            raise ValueError(
                "max_turns must be >= 1",
            )
        self.max_turns = max_turns
        self._messages: list[ChatMessage] = []

    def add(
        self,
        role: str,
        content: str,
    ) -> ChatMessage:
        msg = ChatMessage(
            role=role,
            content=content,
        )
        self._messages.append(msg)
        while len(self._messages) > self.max_turns:
            self._messages.pop(0)
        return msg

    def add_user(
        self,
        content: str,
    ) -> ChatMessage:
        return self.add("user", content)

    def add_assistant(
        self,
        content: str,
    ) -> ChatMessage:
        return self.add("assistant", content)

    def add_system(
        self,
        content: str,
    ) -> ChatMessage:
        return self.add("system", content)

    def messages(self) -> list[ChatMessage]:
        return deepcopy(self._messages)

    def clear(self) -> None:
        self._messages.clear()

    def __len__(self) -> int:
        return len(self._messages)

class ContextManager:
    def __init__(
        self,
        max_turns: int = 10,
        max_chars: int = 6000,
    ):
        if max_turns < 1:
            raise ValueError(
                "max_turns must be >= 1",
            )
        if max_chars < 100:
            raise ValueError(
                "max_chars must be >= 100",
            )
        self.max_turns = max_turns
        self.max_chars = max_chars
        self.history = ConversationHistory(
            max_turns=max_turns,
        )

    def add_user(
        self,
        content: str,
    ) -> ChatMessage:
        return self.history.add_user(
            content,
        )

    def add_assistant(
        self,
        content: str,
    ) -> ChatMessage:
        return self.history.add_assistant(
            content,
        )

    def add_system(
        self,
        content: str,
    ) -> ChatMessage:
        return self.history.add_system(
            content,
        )

    def messages(self) -> list[ChatMessage]:
        return self.history.messages()

    def clear(self) -> None:
        self.history.clear()

    def __len__(self) -> int:
        return len(self.history)

    def _render(
        self,
        msgs: list[ChatMessage],
        new_prompt: str,
    ) -> str:
        parts = []
        for m in msgs:
            parts.append(
                f"{m.role}: {m.content}",
            )
        parts.append(
            f"user: {new_prompt}",
        )
        parts.append("assistant:")
        return "\n".join(parts)

    def build_prompt(
        self,
        new_prompt: str,
    ) -> str:
        if not new_prompt.strip():
            raise ValueError(
                "prompt is empty",
            )
        msgs = self.history.messages()
        full = self._render(
            msgs,
            new_prompt,
        )
        while len(full) > self.max_chars and msgs:
            msgs.pop(0)
            full = self._render(
                msgs,
                new_prompt,
            )
        return full

    def build_context(
        self,
        user_id,
        prompt: str,
        max_tokens: int = 256,
        temperature: float = 0.7,
        top_k: int = 0,
        top_p: float = 1.0,
    ) -> InferenceContext:
        combined = self.build_prompt(
            prompt,
        )
        return InferenceContext(
            user_id=user_id,
            prompt=combined,
            max_tokens=max_tokens,
            temperature=temperature,
            top_k=top_k,
            top_p=top_p,
        )
