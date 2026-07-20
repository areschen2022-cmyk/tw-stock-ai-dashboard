# AI Review Rules

The AI layer is a second-opinion review for candidates already scored by the
local screening engine. It must not create picks from raw news alone.

## DeepSeek Primary Mode

Production currently uses the official DeepSeek API as the primary review
model:

```yaml
ai_council:
  provider: "deepseek"
  models:
    - "deepseek-chat"
  min_model_count: 1
  min_agree_count: 1
  fallback_pick_count: 0
  pick_action: "可追"
```

GitHub Actions must have `DEEPSEEK_API_KEY` in Repository Secrets. The local
`.env` can also define `DEEPSEEK_API_KEY` for manual testing.

## Dashboard Wording

Because production uses one paid model, the dashboard should say
`AI 單模型複核` instead of `AI 共識` or `AI Council`.

- `AI 同意`: the configured model returned `可追`.
- `AI 保留`: the configured model preferred `等拉回` or `只觀察`.
- `AI 不建議`: the configured model returned `避免`.
- `待 AI 確認`: the candidate has not received a valid AI review yet.

The AI review is not a buy signal by itself. A stock still needs the local
score, risk guard, historical-reference check, and opening price/volume
confirmation.

## If Multi-Model Review Is Reintroduced

If more models are added later, increase `min_model_count` and
`min_agree_count` together, and then the UI may use `AI 共識` only when the
threshold is actually greater than one model.

## Why Free-Model Consensus Was Replaced

Free OpenRouter models frequently returned 429, timeout, or malformed JSON. The
old five-model rule looked strict, but in practice the system often had only
one to three valid responses and therefore no stable AI review. DeepSeek
primary mode trades multi-model voting for stable paid availability, while
keeping `fallback_pick_count` at `0` to avoid weak fallback picks.
