"""
APACHE II Scoring Rules Implementation
Standardized logic for ICU Risk Sentinel Agent
"""

from typing import Dict, Optional, Any

# ==============================================================================
# 1. Individual Parameter Scoring Functions
# ==============================================================================

def get_temp_score(value: Optional[float]) -> int:
    """直肠温度 (Rectal Temperature) 评分"""
    if value is None: return 0
    if value >= 41.0: return 4
    if value >= 39.0: return 3
    if value >= 38.5: return 1
    if value >= 36.0: return 0
    if value >= 34.0: return 1
    if value >= 32.0: return 2
    if value >= 30.0: return 3
    return 4  # < 30.0

def get_map_score(value: Optional[float]) -> int:
    """平均动脉压 (MAP) 评分"""
    if value is None: return 0
    if value >= 160: return 4
    if value >= 130: return 3
    if value >= 110: return 2
    if value >= 70: return 0
    if value >= 50: return 2
    return 4  # < 50

def get_hr_score(value: Optional[float]) -> int:
    """心率 (Heart Rate) 评分"""
    if value is None: return 0
    if value >= 180: return 4
    if value >= 140: return 3
    if value >= 110: return 2
    if value >= 70: return 0
    if value >= 55: return 2
    if value >= 40: return 3
    return 4  # < 40

def get_rr_score(value: Optional[float]) -> int:
    """呼吸频率 (Respiratory Rate) 评分"""
    if value is None: return 0
    if value >= 50: return 4
    if value >= 35: return 3
    if value >= 25: return 1
    if value >= 12: return 0
    if value >= 10: return 1
    if value >= 6: return 2
    return 4  # < 6

def get_oxygen_score(
    fiO2: Optional[float] = None, 
    paO2: Optional[float] = None, 
    aaDO2: Optional[float] = None
) -> int:
    """
    氧合评分 (Oxygenation Score)
    - 若 FiO2 < 0.5，使用 PaO2 评分
    - 若 FiO2 >= 0.5，使用 A-aDO2 评分 (此函数中若未传入 aaDO2 则无法评分，需外部支持)
    """
    # 如果没有 FiO2 数据，默认按非机械通气处理 (尝试用 PaO2)
    f = fiO2 if fiO2 is not None else 0.21 
    
    if f < 0.5:
        # 使用 PaO2 (mmHg)
        if paO2 is None: return 0
        if paO2 > 70: return 0
        if paO2 >= 61: return 1
        if paO2 >= 55: return 3
        return 4  # < 55
    else:
        # 使用 A-aDO2 (mmHg)
        if aaDO2 is None: return 0
        if aaDO2 >= 500: return 4
        if aaDO2 >= 350: return 3
        if aaDO2 >= 200: return 2
        return 0  # < 200

def get_ph_score(value: Optional[float]) -> int:
    """动脉 pH 评分"""
    if value is None: return 0
    if value >= 7.7: return 4
    if value >= 7.6: return 3
    if value >= 7.5: return 1
    if value >= 7.33: return 0
    if value >= 7.25: return 2
    if value >= 7.15: return 3
    return 4  # < 7.15

def get_serum_sodium_score(value: Optional[float]) -> int:
    """血清钠 (Na+) 评分"""
    if value is None: return 0
    if value >= 180: return 4
    if value >= 160: return 3
    if value >= 155: return 2
    if value >= 150: return 1
    if value >= 130: return 0
    if value >= 120: return 2
    if value >= 111: return 3
    return 4  # < 111

def get_serum_potassium_score(value: Optional[float]) -> int:
    """血清钾 (K+) 评分"""
    if value is None: return 0
    if value >= 7.0: return 4
    if value >= 6.0: return 3
    if value >= 5.5: return 1
    if value >= 3.5: return 0
    if value >= 3.0: return 2
    if value >= 2.5: return 3
    return 4  # < 2.5

def get_creatinine_score(value: Optional[float], arf: bool = False) -> int:
    """
    血清肌酐 (Creatinine) 评分
    修正点: < 0.6 标准分为 0 分 (除非标记 ARF)
    """
    if value is None: return 0
    
    base_score = 0
    if value >= 3.5: base_score = 4
    elif value >= 2.0: base_score = 3
    elif value >= 1.5: base_score = 2
    elif value >= 0.6: base_score = 0
    else: base_score = 0  # 标准 APACHE II 中 < 0.6 为 0 分
    
    # 如果有急性肾衰竭 (Acute Renal Failure)，分数翻倍
    return base_score * 2 if arf else base_score

def get_hematocrit_score(value: Optional[float]) -> int:
    """红细胞压积 (Hematocrit) 评分"""
    if value is None: return 0
    if value >= 60.0: return 4
    if value >= 50.0: return 2
    if value >= 46.0: return 1
    if value >= 30.0: return 0
    if value >= 20.0: return 2
    return 4  # < 20.0

def get_wbc_score(value: Optional[float]) -> int:
    """白细胞计数 (WBC) 评分 (单位: K/uL 或 *10^9/L)"""
    if value is None: return 0
    if value >= 40.0: return 4
    if value >= 20.0: return 2
    if value >= 15.0: return 1
    if value >= 3.0: return 0
    if value >= 1.0: return 2
    return 4  # < 1.0

def get_gcs_score(gcs_total: Optional[int]) -> int:
    """
    Glasgow 昏迷评分 (GCS)
    APACHE II 计分规则为: 15 - GCS得分
    """
    if gcs_total is None: return 0
    if gcs_total > 15: gcs_total = 15
    if gcs_total < 3: gcs_total = 3
    return 15 - gcs_total

def get_age_score(age: Optional[int]) -> int:
    """年龄评分"""
    if age is None: return 0
    if age <= 44: return 0
    if age <= 54: return 2
    if age <= 64: return 3
    if age <= 74: return 5
    return 6  # > 74

def get_chronic_health_points(
    has_organ_insufficiency: bool = False,
    is_immunocompromised: bool = False,
    surgery_type: str = "none" # 选项: "none", "emergency", "elective"
) -> int:
    """
    慢性健康状况评分 (Chronic Health Points)
    - 器官功能不全/免疫抑制: 
      - 非手术或急诊手术: +5
      - 择期手术: +2
    - 其他情况: 0
    """
    if not (has_organ_insufficiency or is_immunocompromised):
        return 0
    
    if surgery_type == "elective":
        return 2
    # 默认包括 none (内科病人) 和 emergency
    return 5

# ==============================================================================
# 2. Main Aggregator
# ==============================================================================

def calculate_apache_ii_score(
    vitals: Dict[str, Any],
    age: Optional[int] = None,
    has_organ_insufficiency: bool = False,
    is_immunocompromised: bool = False,
    surgery_type: str = "none",
    is_arf: bool = False # Acute Renal Failure
) -> int:
    """
    计算 APACHE II 总分
    
    Args:
        vitals: 包含生理指标的字典 (keys: temp, map, hr, rr, fio2, pao2, ph, sodium, potassium, creatinine, hematocrit, wbc, gcs)
        age: 患者年龄
        is_arf: 是否合并急性肾衰竭 (影响肌酐评分)
    
    Returns:
        int: APACHE II 总分
    """
    # 1. 提取指标 (处理 Key 缺失或 None 的情况)
    temp = vitals.get("temperature") or vitals.get("temp")
    map_val = vitals.get("map")
    hr = vitals.get("heart_rate") or vitals.get("hr")
    rr = vitals.get("respiratory_rate") or vitals.get("rr")
    
    fio2 = vitals.get("fio2")
    pao2 = vitals.get("pao2")
    aado2 = vitals.get("aado2") # 若未提供则为 None
    
    ph = vitals.get("ph")
    na = vitals.get("sodium") or vitals.get("serum_sodium")
    k = vitals.get("potassium") or vitals.get("serum_potassium")
    cr = vitals.get("creatinine")
    hct = vitals.get("hematocrit") or vitals.get("hct")
    wbc = vitals.get("wbc")
    gcs = vitals.get("gcs")

    # 2. 累加生理评分 (APS)
    score = 0
    score += get_temp_score(temp)
    score += get_map_score(map_val)
    score += get_hr_score(hr)
    score += get_rr_score(rr)
    score += get_oxygen_score(fio2, pao2, aado2)
    score += get_ph_score(ph)
    score += get_serum_sodium_score(na)
    score += get_serum_potassium_score(k)
    score += get_creatinine_score(cr, arf=is_arf)
    score += get_hematocrit_score(hct)
    score += get_wbc_score(wbc)
    score += get_gcs_score(gcs)

    # 3. 加上年龄评分
    score += get_age_score(age)

    # 4. 加上慢性健康评分
    score += get_chronic_health_points(
        has_organ_insufficiency, 
        is_immunocompromised, 
        surgery_type
    )

    return score