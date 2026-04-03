from __future__ import annotations

from datetime import datetime, timedelta, timezone

from .schemas import UrineOutputPoint, VitalPoint


def get_bedside_cases(now: datetime | None = None) -> dict[str, dict]:
    """
    Pure, self-contained example time-series.

    These are used by demo scripts and can later be translated into DB seed data.
    """
    end = (now or datetime.now(timezone.utc)).replace(microsecond=0)

    # Common cadence: every 20 minutes for 2 hours, plus a few points near the end for persistence rules.
    def v(
        ts_min_ago: int,
        *,
        hr: int | None,
        map: float | None,
        spo2: float | None,
        temp: float | None,
    ) -> VitalPoint:
        return VitalPoint(
            timestamp=end - timedelta(minutes=ts_min_ago),
            heart_rate=hr,
            mean_arterial_pressure=map,
            spo2=spo2,
            temperature=temp,
            respiratory_rate=None,
        )

    def urine(ts_min_ago: int, ml_per_h: float) -> UrineOutputPoint:
        return UrineOutputPoint(
            timestamp=end - timedelta(minutes=ts_min_ago), urine_output_ml_per_hour=ml_per_h
        )

    return {
        "normal_stable": {
            "analysis_window": "last_4h",
            "vitals": [
                v(180, hr=88, map=75, spo2=97, temp=36.9),
                v(160, hr=90, map=76, spo2=96, temp=37.0),
                v(140, hr=92, map=78, spo2=97, temp=37.1),
                v(120, hr=89, map=74, spo2=98, temp=36.8),
                v(100, hr=91, map=77, spo2=97, temp=37.0),
                v(80, hr=90, map=76, spo2=96, temp=37.0),
                v(60, hr=92, map=75, spo2=97, temp=37.0),
                v(40, hr=89, map=74, spo2=98, temp=36.9),
                v(20, hr=90, map=75, spo2=97, temp=37.0),
                v(10, hr=89, map=76, spo2=97, temp=37.0),
            ],
            "urine_output_points": None,
        },
        "persistent_low_bp": {
            "analysis_window": "last_4h",
            "vitals": [
                v(180, hr=95, map=70, spo2=97, temp=37.0),
                v(140, hr=98, map=68, spo2=96, temp=37.1),
                v(100, hr=102, map=66, spo2=95, temp=37.2),
                v(70, hr=110, map=64, spo2=95, temp=37.2),
                # Trigger: last 30 minutes MAP < 65 with at least 2 points
                v(30, hr=115, map=60, spo2=95, temp=37.1),
                v(20, hr=118, map=58, spo2=94, temp=37.1),
                v(10, hr=116, map=59, spo2=94, temp=37.2),
            ],
            "urine_output_points": None,
        },
        "hypoxemia_worsening": {
            "analysis_window": "last_4h",
            "vitals": [
                v(220, hr=95, map=72, spo2=95, temp=37.0),
                v(180, hr=98, map=70, spo2=94, temp=37.1),
                v(140, hr=102, map=69, spo2=93, temp=37.2),
                v(100, hr=108, map=68, spo2=92, temp=37.3),
                # Trigger: last 30 minutes SpO2 < 90
                v(35, hr=115, map=67, spo2=89, temp=37.4),
                v(25, hr=118, map=66, spo2=88, temp=37.4),
                v(15, hr=120, map=65, spo2=86, temp=37.5),
            ],
            "urine_output_points": None,
        },
        "urine_decline_and_fever": {
            "analysis_window": "last_4h",
            "vitals": [
                v(200, hr=90, map=74, spo2=97, temp=37.0),
                v(150, hr=92, map=73, spo2=96, temp=37.1),
                v(110, hr=96, map=72, spo2=95, temp=37.2),
                v(50, hr=105, map=68, spo2=94, temp=37.6),
                # Trigger: last 10 minutes Temp >= 38 with >=2 points
                v(12, hr=108, map=67, spo2=93, temp=38.2),
                v(7, hr=110, map=66, spo2=92, temp=39.0),
                v(4, hr=109, map=66, spo2=92, temp=38.6),
            ],
            # Trigger oliguria: recent mean <= 30 AND decreasing trend.
            "urine_output_points": [
                urine(60, 35),
                urine(40, 25),
                urine(20, 20),
            ],
        },
    }

