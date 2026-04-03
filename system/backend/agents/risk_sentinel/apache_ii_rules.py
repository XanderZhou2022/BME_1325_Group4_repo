"from typing import Optional

def get_temp_score(value: Optional[float]) -> int:
    if value is None: return 0
    if value >= 41.0: return 4
    if value >= 39.0: return 3
    if value >= 38.5: return 1
    if value >= 36.0: return 0
    if value >= 34.0: return 1
    if value >= 32.0: return 2
    if value >= 30.0: return 3
    return 4

def get_map_score(value: Optional[float]) -> int:
    if value is None: return 0
    if value >= 160: return 4
    if value >= 130: return 3
    if value >= 110: return 2
    if value >= 70: return 0
    if value >= 50: return 2
    return 4

def get_hr_score(value: Optional[float]) -> int:
    if value is None: return 0
    if value >= 180: return 4
    if value >= 140: return 3
    if value >= 110: return 2
    if value >= 70: return 0
    if value >= 55: return 2
    if value >= 40: return 3
    return 4

def get_rr_score(value: Optional[float]) -> int:
    if value is None: return 0
    if value >= 50: return 4
    if value >= 35: return 3
    if value >= 25: return 1
    if value >= 12: return 0
    if value >= 10: return 1
    if value >= 6: return 2
    return 4

def get_oxygen_score(fio2: Optional[float] = None, pao2: Optional[float] = None, aado2: Optional[float] = None) -> int:
    if pao2 is not None and (fio2 is None or fio2 < 0.5):
        if pao2 > 70: return 0
        if pao2 >= 61: return 1
        if pao2 >= 55: return 3
        return 4
    if aado2 is not None:
        if aado2 >= 500: return 4
        if aado2 >= 350: return 3
        if aado2 >= 200: return 2
        return 0
    return 0

def get_ph_score(value: Optional[float]) -> int:
    if value is None: return 0
    if value >= 7.7: return 4
    if value >= 7.6: return 3
    if value >= 7.5: return 1
    if value >= 7.33: return 0
    if value >= 7.25: return 2
    if value >= 7.15: return 3
    return 4

def get_sodium_score(value: Optional[float]) -> int:
    if value is None: return 0
    if value >= 180: return 4
    if value >= 160: return 3
    if value >= 155: return 2
    if value >= 150: return 1
    if value >= 130: return 0
    if value >= 120: return 2
    if value >= 111: return 3
    return 4

def get_potassium_score(value: Optional[float]) -> int:
    if value is None: return 0
    if value >= 7.0: return 4
    if value >= 6.0: return 3
    if value >= 5.5: return 1
    if value >= 3.5: return 0
    if value >= 3.0: return 2
    if value >= 2.5: return 3
    return 4

def get_creatinine_score(value: Optional[float]) -> int:
    if value is None: return 0
    if value >= 3.5: return 4
    if value >= 2.0: return 3
    if value >= 1.5: return 2
    if value >= 0.6: return 0
    return 2

def get_hct_score(value: Optional[float]) -> int:
    if value is None: return 0
    if value >= 60.0: return 4
    if value >= 50.0: return 2
    if value >= 46.0: return 1
    if value >= 30.0: return 0
    if value >= 20.0: return 2
    return 4

def get_wbc_score(value: Optional[float]) -> int:
    if value is None: return 0
    if value >= 40.0: return 4
    if value >= 20.0: return 2
    if value >= 15.0: return 1
    if value >= 3.0: return 0
    if value >= 1.0: return 2
    return 4

def get_gcs_score(value: Optional[float]) -> int:
    if value is None: return 0
    return 15 - int(value)

def get_age_score(age: int) -> int:
    if age < 45: return 0
    if age < 55: return 2
    if age < 65: return 3
    if age < 75: return 5
    return 6

def get_chronic_health_score(status: Optional[str] = None, is_elective_surgery: bool = False) -> int:
    if status and 'insufficiency' in status.lower():
        return 5 if not is_elective_surgery else 2
    return 0"
