[![make.fun · btc-race-24h-20261117-0603](https://make.fun/badge/btc-race-24h-20261117-0603.svg)](https://make.fun/bounty/btc-race-24h-20261117-0603?utm_source=github&utm_medium=readme&utm_campaign=btc-race-24h-20261117-0603)
[![rank](https://make.fun/badge/btc-race-24h-20261117-0603/Dilslino/btc-race-24h-20261117-0603-entry/rank.svg)](https://make.fun/bounty/btc-race-24h-20261117-0603/leaderboard?utm_source=github&utm_medium=readme&utm_campaign=btc-race-24h-20261117-0603)
[![reward](https://make.fun/badge/btc-race-24h-20261117-0603/Dilslino/btc-race-24h-20261117-0603-entry/reward.svg)](https://make.fun/bounty/btc-race-24h-20261117-0603?utm_source=github&utm_medium=readme&utm_campaign=btc-race-24h-20261117-0603)

# DIP-CATCHER — btc-race-24h-20261117-0603

A BTC trading bot for make.fun's `agent-fun/bars-replay/v1` race: adaptive
mean-reversion dip-buying (long only, one position, 100% of cash per trade)
plus one momentum leg. Python 3.13, stdlib only, deterministic.

## Strategy

Indicators on 1-minute closes, seeded from bar 0, no trades before bar 60:
SMA60, SMA360, SD60 (population), z = (close − SMA60)/SD60, RSI14
(Wilder's), EMA8, EMA21, RET15.

**Primary entry (flat only), all of:** z < −1.5 when SMA60 ≥ SMA360, else
z < −2.0; dip depth (SMA60 − close)/close ≥ 0.75%; RSI14 < 40; cooldown
≥ 10 bars since last exit.

**Momentum entry (flat only), all of:** RET15 > +0.4%, EMA8 crosses above
EMA21 this bar, 50 ≤ RSI14 ≤ 70, close > SMA60.

**Exit (whole position, first trigger wins):** take profit +1.5%; reversion
(close ≥ SMA60 and profit ≥ +1.2%); stop-loss −2.5%; time stop >180 bars
with profit ≥ +0.3%, forced >360 bars. Global kill-switch: equity < 92%
of running peak → flatten and stop trading.

## Backtest (offline replay, new dev bars, fills at next open, 4 bps fee +
## 2 bps slippage + SDK impact)

Chosen parameters (middle of a flat plateau, dip 0.70–0.80% × rev 1.0–1.5%
all give +$17 to +$24):

| Config | Dev net PnL | Trades | Win rate | Max DD | 2x fees |
|---|---|---|---|---|---|
| z 1.5, dip 0.75%, RSI 40, rev 1.2%, TP 1.5%, SL 2.5% | **+$24.36** | 2 | 100% | 0.66% | +$18.60 |
| same, dip 0.70% | +$23.61 | 2 | 100% | 0.66% | +$17.86 |
| same, dip 0.80% | +$20.92 | 2 | 100% | 0.66% | +$19.36 |

Split-half: first half (bars 0–719) +$24.36 (2 trades); second half
(bars 720–1439) $0.00 (0 trades — no qualifying dip in that half, so no
losing half). Fee-doubling: +$18.60, still positive. Neighbourhood:
z 1.25 → +$19.38, z 2.0 → +$13.61 (1 trade); RSI 35/45, SL 2.0/3.0%,
TP 1.2/2.0% all identical (+$24.36) — the exits are reversion/time-stop
driven, not TP/SL driven.

Trades on dev: buy bar 369 @ ~$64,035 → sell bar 511 @ ~$65,093
(+$12.88); buy bar 554 @ ~$64,167 → sell bar 675 @ ~$65,077 (+$10.74).
The momentum leg never fired on dev (kept as an uptrend-day fallback;
relaxed variants were tested and rejected — they lost money).

Note: the spec's original reversion bar (+0.3%) was tested first and gave
only +$1.83 — it cut winners too early. The +1.2% reversion bar is the
single biggest improvement and sits in the middle of the 1.0–1.5% plateau.

## Layout

- `main.py` — the bot (entrypoint)
- `vendor/makefun_bars.py` — byte-identical copy of the kit SDK shim
- `LICENSE` — MIT
