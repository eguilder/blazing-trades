"""Shared short-strangle rules; select a file with SHORT_STRANGLE_RULESET or configure_ruleset(path)."""

from __future__ import annotations

import json
import math
import os
from dataclasses import dataclass
from pathlib import Path


DEFAULT_RULESET_PATH = Path(__file__).with_name("short_strangle_rules.json")
RULESET_PATH = Path(os.environ.get("SHORT_STRANGLE_RULESET", DEFAULT_RULESET_PATH))
REQUIRED_PARAMETERS = (
    "entry_dte", "entry_delta", "replacement_delta", "alert_delta", "threat_delta",
    "close_review_delta", "hedge_max_call_delta", "hedge_min_untested_delta",
    "hedge_max_untested_delta", "vol_spike_ratio", "roll_dte",
    "early_reposition_min_dte", "early_reposition_max_dte",
    "long_reposition_min_dte", "long_reposition_max_dte",
    "early_reposition_max_delta", "early_reposition_max_total_delta",
    "low_delta_trigger", "low_delta_replace_below", "vol_window",
    "vol_baseline_window", "contract_multiplier", "shares_per_contract",
)


def load_ruleset(path: str | Path | None = None) -> dict:
    """Load and validate a ruleset, defaulting to the selected active file."""
    selected_path = Path(path) if path is not None else RULESET_PATH
    with selected_path.open(encoding="utf-8") as handle:
        ruleset = json.load(handle)
    if ruleset.get("schema_version") != 1 or not isinstance(ruleset.get("parameters"), dict):
        raise ValueError(f"Unsupported short-strangle ruleset: {selected_path}")
    parameters = ruleset["parameters"]
    missing = [key for key in REQUIRED_PARAMETERS if key not in parameters]
    if missing:
        raise ValueError(f"Ruleset {selected_path} is missing parameters: {', '.join(missing)}")
    invalid = [
        key for key in REQUIRED_PARAMETERS
        if isinstance(parameters[key], bool)
        or not isinstance(parameters[key], (int, float))
        or not math.isfinite(parameters[key])
    ]
    if invalid:
        raise ValueError(f"Ruleset {selected_path} has non-numeric parameters: {', '.join(invalid)}")
    return ruleset


RULESET: dict = {}
PARAMETERS: dict = {}


def configure_ruleset(path: str | Path | None = None) -> dict:
    """Select the active ruleset and refresh the module's parameter constants."""
    global RULESET_PATH, RULESET, PARAMETERS
    global ENTRY_DTE, ENTRY_DELTA, REPLACEMENT_DELTA, ALERT_DELTA, THREAT_DELTA
    global CLOSE_REVIEW_DELTA, HEDGE_MAX_CALL_DELTA, HEDGE_MIN_UNTESTED_DELTA
    global HEDGE_MAX_UNTESTED_DELTA, VOL_SPIKE_RATIO, ROLL_DTE
    global EARLY_REPOSITION_MIN_DTE, EARLY_REPOSITION_MAX_DTE
    global LONG_REPOSITION_MIN_DTE, LONG_REPOSITION_MAX_DTE, LONG_REPOSITION_DELTA
    global EARLY_REPOSITION_MAX_DELTA, EARLY_REPOSITION_MAX_TOTAL_DELTA
    global LOW_DELTA_TRIGGER, LOW_DELTA_REPLACE_BELOW, VOL_WINDOW
    global VOL_BASELINE_WINDOW, CONTRACT_MULTIPLIER, SHARES_PER_CONTRACT

    selected_path = Path(path) if path is not None else RULESET_PATH
    selected = load_ruleset(selected_path)
    RULESET_PATH = selected_path
    RULESET = selected
    PARAMETERS = selected["parameters"]
    ENTRY_DTE = int(PARAMETERS["entry_dte"])
    ENTRY_DELTA = float(PARAMETERS["entry_delta"])
    REPLACEMENT_DELTA = float(PARAMETERS["replacement_delta"])
    ALERT_DELTA = float(PARAMETERS["alert_delta"])
    THREAT_DELTA = float(PARAMETERS["threat_delta"])
    CLOSE_REVIEW_DELTA = float(PARAMETERS["close_review_delta"])
    HEDGE_MAX_CALL_DELTA = float(PARAMETERS["hedge_max_call_delta"])
    HEDGE_MIN_UNTESTED_DELTA = float(PARAMETERS["hedge_min_untested_delta"])
    HEDGE_MAX_UNTESTED_DELTA = float(PARAMETERS["hedge_max_untested_delta"])
    VOL_SPIKE_RATIO = float(PARAMETERS["vol_spike_ratio"])
    ROLL_DTE = int(PARAMETERS["roll_dte"])
    EARLY_REPOSITION_MIN_DTE = int(PARAMETERS["early_reposition_min_dte"])
    EARLY_REPOSITION_MAX_DTE = int(PARAMETERS["early_reposition_max_dte"])
    LONG_REPOSITION_MIN_DTE = int(PARAMETERS["long_reposition_min_dte"])
    LONG_REPOSITION_MAX_DTE = int(PARAMETERS["long_reposition_max_dte"])
    LONG_REPOSITION_DELTA = THREAT_DELTA
    EARLY_REPOSITION_MAX_DELTA = float(PARAMETERS["early_reposition_max_delta"])
    EARLY_REPOSITION_MAX_TOTAL_DELTA = float(PARAMETERS["early_reposition_max_total_delta"])
    LOW_DELTA_TRIGGER = float(PARAMETERS["low_delta_trigger"])
    LOW_DELTA_REPLACE_BELOW = float(PARAMETERS["low_delta_replace_below"])
    VOL_WINDOW = int(PARAMETERS["vol_window"])
    VOL_BASELINE_WINDOW = int(PARAMETERS["vol_baseline_window"])
    CONTRACT_MULTIPLIER = int(PARAMETERS["contract_multiplier"])
    SHARES_PER_CONTRACT = int(PARAMETERS["shares_per_contract"])
    return RULESET


configure_ruleset()


@dataclass(frozen=True)
class RuleDecision:
    action: str
    reasons: tuple[str, ...]
    replacement_rights: tuple[str, ...] = ()


def classify_position(
    *,
    dte: int,
    put_delta: float | None,
    call_delta: float | None,
    spot: float | None = None,
    put_strike: float | None = None,
    call_strike: float | None = None,
    put_iv: float | None = None,
    call_iv: float | None = None,
    historical_vol: float | None = None,
    alert_delta: float | None = None,
    threat_delta: float | None = None,
    close_review_delta: float | None = None,
    vol_spike_ratio: float | None = None,
    hedge_max_call_delta: float | None = None,
) -> RuleDecision:
    """Apply the shared precedence rules to a short strangle snapshot."""
    alert_delta = ALERT_DELTA if alert_delta is None else alert_delta
    threat_delta = THREAT_DELTA if threat_delta is None else threat_delta
    close_review_delta = CLOSE_REVIEW_DELTA if close_review_delta is None else close_review_delta
    vol_spike_ratio = VOL_SPIKE_RATIO if vol_spike_ratio is None else vol_spike_ratio
    hedge_max_call_delta = HEDGE_MAX_CALL_DELTA if hedge_max_call_delta is None else hedge_max_call_delta
    if put_delta is None or call_delta is None:
        return RuleDecision("HOLD", ("model delta unavailable for the short legs",))

    abs_put = abs(put_delta)
    abs_call = abs(call_delta)
    max_delta = max(abs_put, abs_call)
    total_delta = abs_put + abs_call
    put_breach = spot is not None and put_strike is not None and spot <= put_strike
    call_breach = spot is not None and call_strike is not None and spot >= call_strike
    strike_breach = put_breach or call_breach
    vol_spike = (
        historical_vol is not None
        and historical_vol > 0
        and any(
            iv is not None and iv >= historical_vol * vol_spike_ratio
            for iv in (put_iv, call_iv)
        )
    )

    # Once DTE is 20 or less, a threatened leg is handled by the full-roll
    # rule before the review-only close condition.  This prevents a late
    # temporary-review flag from suppressing the scheduled roll.
    if dte <= ROLL_DTE and max_delta >= alert_delta:
        return RuleDecision("ROLL", (f"DTE is {ROLL_DTE} or less and a short leg is threatened",), ("P", "C"))

    if max_delta >= close_review_delta and (vol_spike or strike_breach):
        reasons = [f"short-leg delta is at least {close_review_delta:.2f}"]
        if vol_spike:
            reasons.append("option volatility is elevated versus its historical baseline")
        if strike_breach:
            reasons.append("spot has breached a short strike")
        return RuleDecision("TEMPORARY_CLOSE_REVIEW", tuple(reasons))

    if (
        abs_call > alert_delta
        and abs_call <= hedge_max_call_delta
        and HEDGE_MIN_UNTESTED_DELTA <= abs_put <= HEDGE_MAX_UNTESTED_DELTA
        and not vol_spike
    ):
        return RuleDecision("HEDGE", (
            f"short call delta is above {alert_delta:.2f} but not materially elevated",
            f"untested short put is between {HEDGE_MIN_UNTESTED_DELTA:.2f} and {HEDGE_MAX_UNTESTED_DELTA:.2f} delta inclusive and IV is not spiked",
            "buy stock to offset the short call delta instead of repositioning",
        ))

    if abs_put < alert_delta and abs_call < alert_delta and min(abs_put, abs_call) < LOW_DELTA_TRIGGER:
        rights = tuple(right for right, delta in (("P", abs_put), ("C", abs_call)) if delta < LOW_DELTA_REPLACE_BELOW)
        return RuleDecision("REPOSITION", (
            f"both short-leg deltas are below {alert_delta:.2f}, but at least one is below {LOW_DELTA_TRIGGER:.2f}",
            f"tighten only legs below {LOW_DELTA_REPLACE_BELOW:.2f} toward the replacement target",
        ), rights)

    if (
        EARLY_REPOSITION_MIN_DTE <= dte <= EARLY_REPOSITION_MAX_DTE
        and alert_delta <= max_delta < EARLY_REPOSITION_MAX_DELTA
        and total_delta < EARLY_REPOSITION_MAX_TOTAL_DELTA
    ):
        rights = tuple(right for right, delta in (("P", abs_put), ("C", abs_call)) if delta >= alert_delta)
        return RuleDecision("REPOSITION", (
            f"DTE is above {ROLL_DTE}, so repositioning is preferred over an early full roll",
            f"the threatened leg is between {alert_delta:.2f} and {EARLY_REPOSITION_MAX_DELTA:.2f} delta and combined absolute delta is below {EARLY_REPOSITION_MAX_TOTAL_DELTA:.2f}",
        ), rights)

    if LONG_REPOSITION_MIN_DTE <= dte <= LONG_REPOSITION_MAX_DTE and max_delta >= threat_delta:
        rights = tuple(right for right, delta in (("P", abs_put), ("C", abs_call)) if delta >= threat_delta)
        return RuleDecision("REPOSITION", (
            f"DTE is still long ({LONG_REPOSITION_MIN_DTE}-{LONG_REPOSITION_MAX_DTE}) and a short-leg delta is at least {threat_delta:.2f}, so repositioning is preferred over an early full roll",
        ), rights)

    return RuleDecision("HOLD", (f"both short-leg deltas remain below the {alert_delta:.2f} threat threshold",))

