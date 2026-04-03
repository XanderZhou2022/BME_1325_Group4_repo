from datetime import datetime, timedelta
from typing import List, Dict, Tuple, Optional
import numpy as np

def calculate_trend(values: List[float]) -> str:
    if len(values) < 2: return "stable"
    mid = len(values) // 2
    first_half_avg = np.mean(values[:mid])
    second_half_avg = np.mean(values[mid:])
    diff = second_half_avg - first_half_avg
    threshold = 0.05 * max(abs(first_half_avg), 1.0) # 5% 变化阈值
    if diff > threshold: return "improving" # 假设值越高越好(如MAP, SpO2)，具体逻辑可在 service 层按指标反转
    elif diff < -threshold: return "worsening"
    return "stable"

def calculate_trend_for_metric(metric: str, values: List[float]) -> str:
    # 特殊处理: 对于 HR, Temp 等，过高是恶化，需结合临床逻辑
    # 此处简化为数值下降即 improving (需按实际情况调整)
    return calculate_trend(values)

def calculate_volatility(values: List[float]) -> float:
    if len(values) < 2: return 0.0
    return float(np.std(values) / (np.mean(values) + 1e-9))

def interpolate_missing(values: List[Optional[float]]) -> List[Optional[float]]:
    # 简单前向填充 + 线性插值逻辑占位
    # 实际项目可用 pandas 或 scipy
    result = values[:]
    for i in range(1, len(result)):
        if result[i] is None:
            result[i] = result[i-1]
    return result

def extract_window_data(
    events: List,
    current_time: Optional[datetime],
    window_hours: int,
    value_extractor,
    time_extractor
) -> Tuple[List[float], List[datetime], float]:
    """
    从事件流中提取指定时间窗口的数据
    返回: (数值列表, 时间列表, 数据完整度)
    """
    if not current_time:
        current_time = datetime.utcnow()
    
    cutoff = current_time - timedelta(hours=window_hours)
    windowed = [e for e in events if time_extractor(e) >= cutoff]
    windowed.sort(key=time_extractor)
    
    if not windowed:
        return [], [], 0.0
        
    # 假设理想采样频率 (如 15min 一次)
    expected_count = max(1, window_hours * 4)
    completeness = len(windowed) / expected_count
    
    values = [value_extractor(e) for e in windowed]
    timestamps = [time_extractor(e) for e in windowed]
    
    # 简单插值
    clean_values = interpolate_missing(values)
    
    return clean_values, timestamps, min(completeness, 1.0)