from langchain_core.language_models import BaseChatModel
from langchain_google_genai import ChatGoogleGenerativeAI

from shared.config import get_settings


class FakeChatModel:
    """Small test double for deterministic unit tests."""

    def __init__(self, canned_response: str = "Stub response") -> None:
        self.canned_response = canned_response

    async def ainvoke(self, *_args, **_kwargs) -> str:
        return self.canned_response

    def invoke(self, *_args, **_kwargs) -> str:
        return self.canned_response


def get_llm_client(
    *,
    use_fake: bool = False,
    fake_response: str = "Stub response",
    model_name: str | None = None,
) -> BaseChatModel | FakeChatModel:
    settings = get_settings()
    if use_fake or settings.environment.lower() == "test":
        return FakeChatModel(canned_response=fake_response)

    return ChatGoogleGenerativeAI(
        model=model_name or settings.gemini_model_name,
        google_api_key=settings.google_api_key,
        temperature=0,
    )
