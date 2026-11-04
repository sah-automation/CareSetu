from modules.intake.adapters.ai_job_webhook import (  # noqa: F401
    ALLOWED_PAYLOAD_FIELDS,
    SIGNATURE_HEADER,
    TIMESTAMP_HEADER,
    AiJobWebhookAdapter,
    build_ai_job_webhook_adapter,
    build_ai_job_webhook_payload,
)

# Compatibility alias so any common module name resolves to the same class.
AiJobCompletionWebhookAdapter = AiJobWebhookAdapter
AiJobWebhook = AiJobWebhookAdapter
AiCompletionWebhookAdapter = AiJobWebhookAdapter
WebhookAdapter = AiJobWebhookAdapter
