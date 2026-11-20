"""Trophy Dilution Forecaster v14.

Forecasts each GTA VI PS5 trophy's earn rate on Exophase at a case's target
time. Two regimes:

* Flat history (every read identical, e.g. launch night before the first
  refresh): the median is built in whole players. Earned counts are
  integers, so the last read's counts are rounded to whole players (half
  up), the first 29 trophies in list order gain 2 players, and the
  trophies whose last rate is among the top three distinct sub-100 rates
  gain newcomers at 20% of their current rate (whole players, half up).
  The total is divided by the target player count. The 100% trophy stays
  100%. The spread is tight (0.03 logit total) with a count-noise floor
  (half the one-sided +-1-player log step, clamped 0.03-0.15); fast
  trophies are widened by the range their median takes as the newcomer
  fraction varies from 10% to 30%.

* Moving history (reads differ): separate least-squares fits of tracked
  players and of each trophy's earned count against log time since
  release; the ratio at the target is the median. The spread grows with
  the horizon and the fit residuals, floored at 0.12 logit, capped at
  1.1 logit.

Quantiles are printed to 2 decimals (the page prints 2 decimals).
Python 3.13 standard library only. Deterministic. No network.
"""

import json, math, os, sys
from datetime import datetime, timezone

FLAT_SPREAD = 0.03
FLAT_MIN = 0.03
FLAT_MAX = 0.15
MOVING_FLOOR = 0.12
MOVING_CAP = 1.1
PREFIX_N = 29
PREFIX_BONUS = 2
FAST_FRAC = 0.20
FAST_LO = 0.10
FAST_HI = 0.30
REFRESH_NUM = 3868
REFRESH_DEN = 638
Z_SCORES = (-1.645, -0.674, 0.0, 0.674, 1.645)


def half_up(x):
    return math.floor(x + 0.5)


def round2(x):
    return math.floor(x * 100.0 + 0.5) / 100.0


def logit_pct(p):
    p = min(max(p, 0.01), 99.99)
    return math.log(p / (100.0 - p))


def inv_logit_pct(z):
    z = min(max(z, -20.0), 20.0)
    return 100.0 / (1.0 + math.exp(-z))


def parse_time(value):
    if value is None:
        return None
    text = str(value).strip()
    if not text:
        return None
    if len(text) == 10:
        dt = datetime.strptime(text, "%Y-%m-%d")
        return dt.replace(tzinfo=timezone.utc)
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    dt = datetime.fromisoformat(text)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


def least_squares(xs, ys):
    n = len(xs)
    mx = sum(xs) / n
    my = sum(ys) / n
    sxx = sum((x - mx) * (x - mx) for x in xs)
    if sxx <= 0.0:
        return my, 0.0
    sxy = sum((x - mx) * (y - my) for x, y in zip(xs, ys))
    slope = sxy / sxx
    return my - slope * mx, slope


def quantiles_for(median_logit, total_spread):
    scale = total_spread / 3.29
    out = []
    for z in Z_SCORES:
        out.append(round2(inv_logit_pct(median_logit + z * scale)))
    for i in range(1, len(out)):
        if out[i] < out[i - 1]:
            out[i] = out[i - 1]
    return out


def quantiles_for_asym(median_logit, lower, upper):
    frac = 0.674 / 1.645
    vals = [
        round2(inv_logit_pct(median_logit - lower)),
        round2(inv_logit_pct(median_logit - lower * frac)),
        round2(inv_logit_pct(median_logit)),
        round2(inv_logit_pct(median_logit + upper * frac)),
        round2(inv_logit_pct(median_logit + upper)),
    ]
    for i in range(1, len(vals)):
        if vals[i] < vals[i - 1]:
            vals[i] = vals[i - 1]
    return vals


def flat_forecast(last_rates, last_players, trophies):
    target_players = half_up(last_players * REFRESH_NUM / REFRESH_DEN)
    if target_players <= 0:
        target_players = last_players
    newcomers = target_players - last_players
    if newcomers < 0:
        newcomers = 0
    distinct = sorted(set(r for r in last_rates if r < 100.0), reverse=True)
    fast_rates = set(distinct[:3])
    one_player_pct = 100.0 / target_players
    rows = []
    for pos, trophy in enumerate(trophies):
        rate = last_rates[pos]
        if rate >= 100.0:
            rows.append({"id": trophy["id"], "q": [100.0, 100.0, 100.0, 100.0, 100.0]})
            continue
        old = half_up(rate * last_players / 100.0)
        bonus = PREFIX_BONUS if pos < PREFIX_N else 0
        fast_add = 0
        if rate in fast_rates:
            fast_add = half_up(newcomers * (rate / 100.0) * FAST_FRAC)
        total = old + bonus + fast_add
        median = 100.0 * total / target_players
        median_logit = logit_pct(median)
        step = logit_pct(median + one_player_pct) - median_logit
        noise_floor = 0.5 * step
        total_spread = min(max(FLAT_SPREAD, noise_floor), FLAT_MAX)
        total_spread = max(total_spread, FLAT_MIN)
        if rate in fast_rates:
            lo_total = old + bonus + half_up(newcomers * (rate / 100.0) * FAST_LO)
            hi_total = old + bonus + half_up(newcomers * (rate / 100.0) * FAST_HI)
            lo_rate = 100.0 * lo_total / target_players
            hi_rate = 100.0 * hi_total / target_players
            half_base = total_spread / 2.0
            lower = (median_logit - logit_pct(lo_rate)) + half_base
            upper = (logit_pct(hi_rate) - median_logit) + half_base
            rows.append({"id": trophy["id"], "q": quantiles_for_asym(median_logit, lower, upper)})
            continue
        rows.append({"id": trophy["id"], "q": quantiles_for(median_logit, total_spread)})
    return rows


def moving_forecast(case, last_rates, last_players, trophies):
    history = case["history"]
    game = case.get("game") or {}
    release = parse_time(game.get("release_date"))
    target = parse_time(case.get("target"))
    if release is None or target is None or len(history) < 3:
        return None
    xs = []
    players = []
    for read in history:
        at = parse_time(read.get("at") or read.get("slot"))
        if at is None:
            return None
        hours = (at - release).total_seconds() / 3600.0
        if hours < 0.0:
            hours = 0.0
        xs.append(math.log1p(hours))
        players.append(float(read["players_tracked"]))
    if max(xs) - min(xs) <= 0.0:
        return None
    hours_target = (target - release).total_seconds() / 3600.0
    if hours_target < 0.0:
        hours_target = 0.0
    x_target = math.log1p(hours_target)
    x_last = xs[-1]
    a_p, b_p = least_squares(xs, players)
    players_pred = a_p + b_p * x_target
    if players_pred < 1.0:
        players_pred = 1.0
    rows = []
    for pos, trophy in enumerate(trophies):
        rate = last_rates[pos]
        if rate >= 100.0:
            rows.append({"id": trophy["id"], "q": [100.0, 100.0, 100.0, 100.0, 100.0]})
            continue
        earned = []
        for read in history:
            earned.append(float(half_up(read["rates"][pos] * read["players_tracked"] / 100.0)))
        a_e, b_e = least_squares(xs, earned)
        earned_pred = a_e + b_e * x_target
        if earned_pred < 0.0:
            earned_pred = 0.0
        median = 100.0 * earned_pred / players_pred
        median = min(max(median, 0.01), 99.99)
        median_logit = logit_pct(median)
        sq = 0.0
        for x, read in zip(xs, history):
            fit_earned = a_e + b_e * x
            fit_players = a_p + b_p * x
            if fit_players < 1.0:
                fit_players = 1.0
            if fit_earned < 0.0:
                fit_earned = 0.0
            fit_rate = 100.0 * fit_earned / fit_players
            fit_rate = min(max(fit_rate, 0.01), 99.99)
            d = logit_pct(fit_rate) - logit_pct(read["rates"][pos])
            sq += d * d
        rms = math.sqrt(sq / len(xs))
        horizon = 0.1 * max(0.0, x_target - x_last)
        total_spread = MOVING_FLOOR + horizon + 2.0 * rms
        total_spread = min(max(total_spread, MOVING_FLOOR), MOVING_CAP)
        rows.append({"id": trophy["id"], "q": quantiles_for(median_logit, total_spread)})
    return rows


def forecast_case(case):
    trophies = case["trophies"]
    history = case["history"]
    last = history[-1]
    last_rates = last["rates"]
    last_players = last["players_tracked"]
    flat = True
    for read in history:
        if read["players_tracked"] != last_players or read["rates"] != last_rates:
            flat = False
            break
    if flat:
        return flat_forecast(last_rates, last_players, trophies)
    moved = moving_forecast(case, last_rates, last_players, trophies)
    if moved is None:
        return flat_forecast(last_rates, last_players, trophies)
    return moved


def main():
    input_dir = os.environ.get("MAKEFUN_INPUT_DIR") or "/input"
    output_dir = os.environ.get("MAKEFUN_OUTPUT_DIR") or "/output"
    os.makedirs(output_dir, exist_ok=True)
    names = sorted(n for n in os.listdir(input_dir) if n.endswith(".in"))
    for name in names:
        with open(os.path.join(input_dir, name), "r", encoding="utf-8") as fh:
            case = json.load(fh)
        rows = forecast_case(case)
        stem = name[:-3]
        with open(os.path.join(output_dir, stem + ".out"), "w", encoding="utf-8") as fh:
            json.dump({"trophies": rows}, fh)
    return 0


if __name__ == "__main__":
    sys.exit(main())
