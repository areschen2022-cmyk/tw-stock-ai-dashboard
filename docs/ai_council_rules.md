# AI Council Rules

The AI Council is a second-opinion layer for candidates already scored by the
local screening engine. It should not create picks from raw news alone.

## Strong AI Pick Rule

A stock is listed as an official AI pick only when all conditions are true:

- At least `min_model_count` models returned a valid review.
- At least `min_agree_count` models voted for `pick_action`.
- The stock is already in the dashboard candidate set passed to AI Council.

Current production settings:

```yaml
ai_council:
  min_model_count: 5
  min_agree_count: 5
  fallback_pick_count: 0
  pick_action: "可追"
```

This means:

- 5 models must participate.
- 5 models must agree on `可追`.
- If only 1-3 models respond, the result is shown as review evidence only and
  will not become an AI pick.

## Why fallback picks are disabled

Free OpenRouter models can return 429, timeout, or malformed JSON. Showing a
fallback pick when only one or two models answered can look like a consensus
even though the sample is too small. Therefore `fallback_pick_count` is `0`.

## Dashboard wording

The dashboard should distinguish:

- `AI 自選股`: passed model-count and vote-count thresholds.
- `AI review`: model comments exist, but the threshold was not met.
- `AI 樣本不足`: fewer than `min_model_count` valid model reviews.
