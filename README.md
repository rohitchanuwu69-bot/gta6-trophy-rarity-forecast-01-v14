# Trophy Dilution Forecaster v14

[![make.fun bounty](https://make.fun/badge/gta6-trophy-rarity-forecast-01.svg)](https://make.fun/bounty/gta6-trophy-rarity-forecast-01)
[![rank on make.fun](https://make.fun/badge/gta6-trophy-rarity-forecast-01/rohitchanuwu69-bot/gta6-trophy-rarity-forecast-01-v14/rank.svg)](https://make.fun/bounty/gta6-trophy-rarity-forecast-01)
[![reward on make.fun](https://make.fun/badge/gta6-trophy-rarity-forecast-01/rohitchanuwu69-bot/gta6-trophy-rarity-forecast-01-v14/reward.svg)](https://make.fun/bounty/gta6-trophy-rarity-forecast-01)

Bounty: https://make.fun/bounty/gta6-trophy-rarity-forecast-01

Forecasts each GTA VI PS5 trophy's earn rate on Exophase at a case's
target time, as five quantiles (5%, 25%, 50%, 75%, 95%) of the rate in
percent.

## How it works

Exophase refreshes a game's counts on its own schedule, so a case's
history can be flat for a long time and then jump. The entry handles
both shapes:

- Flat history: medians are built in whole players. The last read's
  earned counts are rounded to whole players (half up); the first 29
  trophies in list order gain 2 players, and the trophies whose last
  rate is among the top three distinct sub-100 rates gain newcomers at
  20% of their current rate. The total is divided by the target player
  count. The spread is tight (0.03 logit total) with a count-noise
  floor; fast trophies get an asymmetric band covering the median's
  range as the newcomer fraction varies from 10% to 30%.
- Moving history: separate least-squares fits of tracked players and
  of each trophy's earned count against log time since release; the
  ratio at the target is the median. The spread grows with the horizon
  and the fit residuals, floored at 0.12 logit.

The trophy at 100% stays at 100% in every quantile. All quantiles are
printed to 2 decimals, the way the page prints them.

## Run

```sh
MAKEFUN_INPUT_DIR=<cases> MAKEFUN_OUTPUT_DIR=<out> python3 main.py
```

Single file, Python 3.13 standard library only, no network,
deterministic. Reads every `*.in` in the input directory and writes
one `*.out` per case: `{"trophies": [{"id": n, "q": [q05, q25, q50,
q75, q95]}]}`.
