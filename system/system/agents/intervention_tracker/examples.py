from __future__ import annotations

from datetime import datetime, timedelta, timezone

from .schemas import InterventionType, VitalPoint


def get_intervention_cases(now: datetime | None = None) -> dict[str, dict]:
    """
    Pure, self-contained example pre/post vital sequences.

    These can be evaluated directly by `rules.run_intervention_tracker` without DB access.
    """
    t0 = (now or datetime.now(timezone.utc)).replace(microsecond=0)
    intervention_time = t0

    # Helper: generate VitalPoint with only relevant metrics filled.
    def map_point(minutes_after: int, *, map_val: float) -> VitalPoint:
        return VitalPoint(
            timestamp=intervention_time - timedelta(minutes=minutes_after),
            mean_arterial_pressure=map_val,
            spo2=None,
            respiratory_rate=None,
        )

    def map_post(minutes_after: int, *, map_val: float) -> VitalPoint:
        return VitalPoint(
            timestamp=intervention_time + timedelta(minutes=minutes_after),
            mean_arterial_pressure=map_val,
            spo2=None,
            respiratory_rate=None,
        )

    def vent_pre(minutes_before: int, *, spo2: float, rr: float) -> VitalPoint:
        return VitalPoint(
            timestamp=intervention_time - timedelta(minutes=minutes_before),
            spo2=spo2,
            respiratory_rate=rr,
            mean_arterial_pressure=None,
        )

    def vent_post(minutes_after: int, *, spo2: float, rr: float) -> VitalPoint:
        return VitalPoint(
            timestamp=intervention_time + timedelta(minutes=minutes_after),
            spo2=spo2,
            respiratory_rate=rr,
            mean_arterial_pressure=None,
        )

    return {
        "fluid_after_improves": {
            "intervention_type": "fluid",
            "intervention_time": intervention_time,
            "pre_vitals": [map_point(60, map_val=58), map_point(40, map_val=59), map_point(20, map_val=60)],
            "post_vitals": [map_post(10, map_val=67), map_post(30, map_val=71), map_post(50, map_val=70)],
            "observation_window": "pre 60m / post 60m",
        },
        "fluid_non_improving": {
            "intervention_type": "fluid",
            "intervention_time": intervention_time,
            "pre_vitals": [map_point(60, map_val=68), map_point(30, map_val=67), map_point(10, map_val=69)],
            "post_vitals": [map_post(10, map_val=69), map_post(30, map_val=68), map_post(50, map_val=67)],
            "observation_window": "pre 60m / post 60m",
        },
        "vasopressor_after_improves": {
            "intervention_type": "vasopressor",
            "intervention_time": intervention_time,
            "pre_vitals": [map_point(60, map_val=56), map_point(40, map_val=58), map_point(20, map_val=57)],
            "post_vitals": [map_post(10, map_val=66), map_post(30, map_val=67), map_post(50, map_val=65)],
            "observation_window": "pre 60m / post 60m",
        },
        "ventilator_change_spo2_still_poor": {
            "intervention_type": "ventilator_change",
            "intervention_time": intervention_time,
            "pre_vitals": [
                vent_pre(60, spo2=89, rr=22),
                vent_pre(30, spo2=88, rr=23),
                vent_pre(10, spo2=90, rr=24),
            ],
            "post_vitals": [
                vent_post(10, spo2=87, rr=25),
                vent_post(30, spo2=85, rr=27),
                vent_post(50, spo2=86, rr=26),
            ],
            "observation_window": "pre 60m / post 60m",
        },
    }

