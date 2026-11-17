"""DIP-CATCHER for btc-race-24h-20261117-0603 (agent-fun/bars-replay/v1).

Adaptive mean-reversion dip-buying (long only, single position, 100% of
cash per trade) plus one momentum leg. Stdlib only, no clock, no network,
no randomness: identical input bars give identical replies.

Parameters (chosen from the middle of a flat plateau on the dev window;
see README.md for the backtest numbers):
  z entry -1.5 (uptrend) / -2.0 (downtrend), dip depth >= 0.75% below SMA60,
  RSI14 < 40, cooldown 10 bars, take profit +1.5%, stop loss -2.5%,
  reversion exit at close >= SMA60 with profit >= +1.2%,
  time stop >180 bars with profit >= +0.3% (forced >360 bars),
  global kill-switch at 8% drawdown from running equity peak.
"""

import math
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "vendor"))
import makefun_bars

SYMBOL = "CBBTC"

# --- strategy parameters ---
Z_UP = 1.5            # z threshold when SMA60 >= SMA360
Z_DOWN = 2.0          # z threshold when SMA60 < SMA360
DIP_MIN = 0.0075      # (SMA60 - close) / close
RSI_MAX = 40.0
COOLDOWN = 10         # bars since last exit before a new entry
TAKE_PROFIT = 0.015
STOP_LOSS = 0.025
REVERSION_PROFIT = 0.012
TIME_STOP_BARS = 180
TIME_STOP_PROFIT = 0.003
FORCE_EXIT_BARS = 360
KILL_SWITCH_DD = 0.08
MOM_RET15 = 0.004
MAX_SLIPPAGE_BPS = 100
MIN_BARS = 60         # no trades until indicators are seeded


class DipCatcher:
    def __init__(self):
        self.closes = []          # closes in bar order (float USDC)
        self.entry_seq = None     # seq of the bar whose batch reported the buy fill
        self.last_exit_seq = -10 ** 9
        self.peak_equity = None   # quote units (int)
        self.stopped = False

    # ---- indicators, recomputed from the stored closes (deterministic) ----
    def indicators(self):
        c = self.closes
        n = len(c)
        if n < MIN_BARS:
            return None
        sma60 = sum(c[-60:]) / 60.0
        mean60 = sma60
        var60 = sum((x - mean60) * (x - mean60) for x in c[-60:]) / 60.0
        sd60 = math.sqrt(var60)
        sma360 = sum(c[-360:]) / 360.0 if n >= 360 else None
        # RSI14, Wilder's smoothing, seeded on the first 14 deltas.
        gain = 0.0
        loss = 0.0
        for i in range(1, 15):
            d = c[i] - c[i - 1]
            if d > 0:
                gain += d
            else:
                loss -= d
        avg_gain = gain / 14.0
        avg_loss = loss / 14.0
        for i in range(15, n):
            d = c[i] - c[i - 1]
            g = d if d > 0 else 0.0
            l = -d if d < 0 else 0.0
            avg_gain = (avg_gain * 13.0 + g) / 14.0
            avg_loss = (avg_loss * 13.0 + l) / 14.0
        if avg_loss == 0.0:
            rsi = 100.0
        else:
            rsi = 100.0 - 100.0 / (1.0 + avg_gain / avg_loss)
        # EMA8 / EMA21, seeded on the first close.
        ema8 = c[0]
        ema21 = c[0]
        for i in range(1, n):
            ema8 = c[i] * (2.0 / 9.0) + ema8 * (7.0 / 9.0)
            ema21 = c[i] * (2.0 / 22.0) + ema21 * (20.0 / 22.0)
        prev_ema8 = c[0]
        prev_ema21 = c[0]
        for i in range(1, n - 1):
            prev_ema8 = c[i] * (2.0 / 9.0) + prev_ema8 * (7.0 / 9.0)
            prev_ema21 = c[i] * (2.0 / 22.0) + prev_ema21 * (20.0 / 22.0)
        ret15 = c[-1] / c[-16] - 1.0 if n >= 16 else 0.0
        return {
            "close": c[-1],
            "sma60": sma60,
            "sd60": sd60,
            "sma360": sma360,
            "rsi": rsi,
            "ema8": ema8,
            "ema21": ema21,
            "prev_ema8": prev_ema8,
            "prev_ema21": prev_ema21,
            "ret15": ret15,
        }

    def on_batch(self, state, batch):
        # Fold fills first: track entries/exits from what actually filled.
        for fill in batch.get("fills", []):
            if fill.get("symbol") != SYMBOL or fill.get("status") != "filled":
                continue
            if fill.get("side") == "buy":
                self.entry_seq = batch["seq"]
            elif fill.get("side") == "sell":
                self.last_exit_seq = batch["seq"]
                self.entry_seq = None
        # Append this bar's close (skip the batch if CBBTC is absent).
        bar = None
        for b in batch.get("bars", []):
            if b.get("symbol") == SYMBOL:
                bar = b
                break
        if bar is None:
            return []
        close = int(bar["c"]) / 100000.0  # price_scale 5
        self.closes.append(close)

        # Equity peak / kill-switch bookkeeping.
        equity = state.equity
        if self.peak_equity is None or equity > self.peak_equity:
            self.peak_equity = equity

        holding = state.positions.get(SYMBOL)
        qty = holding.qty if holding else 0
        cost = holding.cost if holding else 0

        if self.stopped:
            if qty > 0:
                return [{"side": "sell", "symbol": SYMBOL, "qty": qty,
                         "max_slippage_bps": MAX_SLIPPAGE_BPS}]
            return []

        if qty > 0 and equity < (1.0 - KILL_SWITCH_DD) * self.peak_equity:
            self.stopped = True
            return [{"side": "sell", "symbol": SYMBOL, "qty": qty,
                     "max_slippage_bps": MAX_SLIPPAGE_BPS}]

        ind = self.indicators()
        if ind is None:
            return []
        close_now = ind["close"]

        if qty > 0:
            value = state.value(SYMBOL, qty)
            profit = value / cost - 1.0 if cost > 0 else 0.0
            held = batch["seq"] - self.entry_seq if self.entry_seq is not None else 0
            exit_now = False
            if value >= cost * (1.0 + TAKE_PROFIT):
                exit_now = True
            elif close_now >= ind["sma60"] and profit >= REVERSION_PROFIT:
                exit_now = True
            elif value <= cost * (1.0 - STOP_LOSS):
                exit_now = True
            elif held > TIME_STOP_BARS and profit >= TIME_STOP_PROFIT:
                exit_now = True
            elif held > FORCE_EXIT_BARS:
                exit_now = True
            if exit_now:
                return [{"side": "sell", "symbol": SYMBOL, "qty": qty,
                         "max_slippage_bps": MAX_SLIPPAGE_BPS}]
            return []

        # Flat: entries only.
        if batch["seq"] - self.last_exit_seq < COOLDOWN:
            return []
        if state.warming_up:
            return []
        if ind["sd60"] == 0.0:
            return []

        z = (close_now - ind["sma60"]) / ind["sd60"]
        uptrend = ind["sma360"] is not None and ind["sma60"] >= ind["sma360"]
        z_lim = -Z_UP if uptrend else -Z_DOWN
        dip = (ind["sma60"] - close_now) / close_now
        cash = state.cash
        if cash < 1000000:
            return []
        if z < z_lim and dip >= DIP_MIN and ind["rsi"] < RSI_MAX:
            return [{"side": "buy", "symbol": SYMBOL,
                     "notional_quote_units": cash,
                     "max_slippage_bps": MAX_SLIPPAGE_BPS}]
        crossed = ind["ema8"] > ind["ema21"] and ind["prev_ema8"] <= ind["prev_ema21"]
        if (ind["ret15"] > MOM_RET15 and crossed
                and 50.0 <= ind["rsi"] <= 70.0 and close_now > ind["sma60"]):
            return [{"side": "buy", "symbol": SYMBOL,
                     "notional_quote_units": cash,
                     "max_slippage_bps": MAX_SLIPPAGE_BPS}]
        return []


def main():
    bot = DipCatcher()
    makefun_bars.run(bot.on_batch)


if __name__ == "__main__":
    main()
