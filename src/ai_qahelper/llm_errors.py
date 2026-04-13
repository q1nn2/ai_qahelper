"""Ошибки LLM-слоя с понятными сообщениями для логов и CLI."""


class LlmError(Exception):
    """Базовая ошибка вызова модели или разбора ответа."""


class LlmEmptyResponse(LlmError):
    """Пустой output_text от API."""


class LlmJsonParseError(LlmError):
    """Ответ не удалось разобрать как JSON."""


class LlmSchemaValidationError(LlmError):
    """JSON не прошёл Pydantic-валидацию целевой схемы."""
