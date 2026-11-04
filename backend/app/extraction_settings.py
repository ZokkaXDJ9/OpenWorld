from dataclasses import dataclass

from sqlalchemy.orm import Session

from .models import ExtractionProviderSettings, ProviderSettings
from .provider import ProviderError


@dataclass(frozen=True)
class ExtractionRuntime:
    base_url: str
    model: str
    encrypted_key: str
    context_window: int
    max_output_tokens: int
    temperature: float = 0
    timeout_seconds: int = 300
    provider_profile: str = "compatible"
    reasoning_mode: str = "default"
    structured_output: str = "auto"
    auto_retry: bool = True


def extraction_provider_settings(db: Session) -> ExtractionProviderSettings:
    row = db.get(ExtractionProviderSettings, 1)
    if row is None:
        row = ExtractionProviderSettings(id=1)
        db.add(row)
        db.flush()
    return row


def resolve_extraction_settings(db: Session) -> ExtractionRuntime:
    row = extraction_provider_settings(db)
    chat = db.get(ProviderSettings, 1)
    connection = chat if row.use_chat_connection else row
    if connection is None:
        raise ProviderError("Keine Verbindung für die Ereignisextraktion konfiguriert.")
    model = row.model or (chat.model if chat else "")
    if not model:
        raise ProviderError("Kein Modell für die Ereignisextraktion konfiguriert.")
    return ExtractionRuntime(
        base_url=connection.base_url,
        model=model,
        encrypted_key=connection.encrypted_key,
        context_window=row.context_window,
        max_output_tokens=row.max_output_tokens,
        temperature=row.temperature,
        timeout_seconds=row.timeout_seconds,
        provider_profile=row.provider_profile,
        reasoning_mode=row.reasoning_mode,
        structured_output=row.structured_output,
        auto_retry=row.auto_retry,
    )
