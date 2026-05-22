# Trading Monitor Reverse Engineering Roadmap

This roadmap adapts proven ideas from Freqtrade, vectorbt, TradingAgents, OpenBB, Lean, and FinRL into the Taiwan stock monitoring dashboard.

## Phase 1: Monitoring Product Upgrade

Goal: make every daily signal observable, auditable, and trackable.

1. Signal leaderboard
   - Rank stocks by 3D, 5D, and 10D forward returns.
   - Show win rate, average return, max drawdown, and signal count.
   - Group by grade, action, theme, and trigger tag.

2. AI selected watchlist
   - Keep strong consensus picks separate from fallback AI observations.
   - Display AI model availability and failure count.
   - Track follow-up returns for each AI action.

3. Data quality guard
   - Flag stale market data, source rate limits, and insufficient histories.
   - Add a lookahead-risk checklist for new signal logic.

4. Telegram status digest
   - Include dashboard freshness, AI availability, and delivery dedupe state.
   - Notify when the morning report is delayed or skipped.

## Phase 2: Strategy Lab

Goal: test whether signals have repeatable edge before promoting them.

1. Parameter sweeps
   - Test MA breakout, volume expansion, institutional flow, and theme momentum thresholds.
   - Produce heatmaps and robustness rankings.

2. Walk-forward validation
   - Split historical windows into train/test periods.
   - Penalize strategies that only work in one short regime.

3. Theme pool performance
   - Measure each theme pool after activation: 3D/5D/10D returns and drawdown.
   - Rank themes by hit rate and persistence.

4. Risk overlay
   - Add market turbulence/regime filters inspired by FinRL.
   - Reduce signal confidence during weak breadth, high volatility, or data-quality warnings.

## Phase 3: Portfolio Layer

Goal: move from single-stock alerts to portfolio construction.

1. Position sizing
   - Convert score, volatility, and stop distance into suggested risk units.

2. Exposure limits
   - Cap theme concentration and total risk by market regime.

3. Paper portfolio
   - Simulate fills and exits from generated signals.
   - Compare portfolio P/L against TAIEX and equal-weight baskets.
