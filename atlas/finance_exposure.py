from __future__ import annotations

import sqlite3
from datetime import date
from typing import Any


MODEL_VERSION = "tracker-finance-exposure-1"


def build_contract_exposure(
    conn: sqlite3.Connection,
    career_id: int,
    *,
    reference_date: date,
    horizon_end: date,
    policy_key: str,
    due90_minor: int = 0,
) -> dict[str, Any]:
    """Return the read-only community exposure surface.

    Project Atlas Tracker does not create contract clauses, negotiations, renewal
    promises or transfer obligations. Ordinary open finance commitments remain
    available through Financial Core and are already included in its cash forecast.
    """
    return {
        "modelVersion": MODEL_VERSION,
        "policyKey": policy_key,
        "referenceDate": reference_date.isoformat(),
        "horizonEnd": max(reference_date, horizon_end).isoformat(),
        "items": [],
        "summary": {
            "guaranteedPayableMinor": 0,
            "guaranteedReceivableMinor": 0,
            "policyWeightedPayableMinor": 0,
            "policyWeightedReceivableMinor": 0,
            "maximumPayableMinor": 0,
            "maximumReceivableMinor": 0,
            "unbookedGuaranteedPayableMinor": 0,
            "unbookedGuaranteedReceivableMinor": 0,
            "unbookedPolicyWeightedPayableMinor": 0,
            "unbookedPolicyWeightedReceivableMinor": 0,
            "unbookedMaximumPayableMinor": 0,
            "unbookedMaximumReceivableMinor": 0,
            "liquidityReserveMinor": 0,
            "linkedCommitmentsBeyond90Minor": 0,
            "unbookedRiskReserveMinor": 0,
            "unknownMaximumPayableCount": 0,
            "unknownMaximumReceivableCount": 0,
            "unknownCommittedPayableCount": 0,
            "unknownCommittedReceivableCount": 0,
            "activeItemCount": 0,
            "horizonItemCount": 0,
        },
        "notes": [
            "Contract negotiations and generated contract obligations are not part of Project Atlas Tracker."
        ],
    }
