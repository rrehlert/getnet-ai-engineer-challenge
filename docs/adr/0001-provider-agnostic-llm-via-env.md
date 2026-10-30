# Provider-agnostic LLM selected by environment variables

The chat model comes from `init_chat_model(LLM_MODEL)` with `LLM_MODEL="provider:model"`. By default it points at OpenRouter through the OpenAI-compatible API (`openai:` provider + `OPENAI_BASE_URL=https://openrouter.ai/api/v1`). Any other provider can be used by changing env vars only, with no code change. We chose this over a provider-specific SDK so that evaluators can run the system with whatever key they have, and so that model swaps for cost or quality need no code changes.
