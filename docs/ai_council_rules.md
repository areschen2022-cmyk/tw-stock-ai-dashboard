# AI Council Rules

The AI Council is a second-opinion layer for candidates already scored by the
local screening engine. It should not create picks from raw news alone.

## DeepSeek Primary Mode

Production now uses the official DeepSeek API as the primary review model:

```yaml
ai_council:
  provider: "deepseek"
  fallback_provider: "openrouter"
  models:
    - "deepseek-chat"
  min_model_count: 1
  min_agree_count: 1
  fallback_pick_count: 0
  pick_action: "可追"
```

GitHub Actions must have `DEEPSEEK_API_KEY` in Repository Secrets. The local
`.env` can also define `DEEPSEEK_API_KEY` for manual testing. If DeepSeek is not
configured, the system may fall back to OpenRouter when `OPENROUTER_API_KEY` is
available; otherwise AI review is skipped and the dashboard keeps the rule-based
stock list.

## Strong AI Pick Rule

A stock is listed as an official AI pick only when all conditions are true:

- At least `min_model_count` models returned a valid review.
- At least `min_agree_count` models voted for `pick_action`.
- The stock is already in the dashboard candidate set passed to AI Council.

This means:

- In DeepSeek primary mode, the single paid model must return a valid review and
  vote `可追`.
- The AI layer still cannot create picks from raw news; it can only review
  candidates already selected by the local scoring engine.
- If the paid API is unavailable, AI review is skipped or downgraded to the
  configured fallback provider.

## Why free-model consensus was replaced

Free OpenRouter models frequently returned 429, timeout, or malformed JSON. The
old 5-model consensus rule looked strict, but in practice the system often had
only 1-3 valid responses and therefore no useful AI picks. DeepSeek primary mode
trades multi-model voting for stable paid availability, while keeping
`fallback_pick_count` at `0` to avoid weak fallback picks.

## Dashboard wording

The dashboard should distinguish:

- `AI 自選股`: passed model-count and vote-count thresholds.
- `AI review`: model comments exist, but the threshold was not met.
- `AI 樣本不足`: fewer than `min_model_count` valid model reviews.
