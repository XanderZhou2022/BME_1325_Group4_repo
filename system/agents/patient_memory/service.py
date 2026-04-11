from .schemas import MemoryRequest, TemporalStateSummary, VitalSignEvent, InterventionEvent
from .memory_manager import calculate_trend, calculate_trend_for_metric, calculate_volatility, extract_window_data
from datetime import datetime
from typing import Dict

def process_memory(request: MemoryRequest) -> TemporalStateSummary:
    current_time = datetime.utcnow()
    
    # 提取 Vital Signs 窗口数据
    def vs_extractor(e: VitalSignEvent): return e.heart_rate
    def vs_time(e: VitalSignEvent): return e.timestamp
    
    # 提取关键指标列表
    vital_metrics = ["heart_rate", "mean_arterial_pressure", "respiratory_rate", "temperature", "spo2"]
    current_vitals = {}
    trend_vectors = {}
    volatility_index = {}
    
    all_completeness = []
    
    for metric in vital_metrics:
        def extractor(e): return getattr(e, metric)
        def time_ext(e): return e.timestamp
        
        values, times, comp = extract_window_data(
            request.vital_sign_events, current_time, request.window_hours,
            extractor, time_ext
        )
        all_completeness.append(comp)
        
        if values:
            # 取最新值作为当前值 (或最差值，按任务书要求)
            current_vitals[metric] = values[-1]
            trend_vectors[metric] = calculate_trend_for_metric(metric, values)
            volatility_index[metric] = calculate_volatility(values)
        else:
            current_vitals[metric] = None
            
    # 处理 Interventions
    interventions_sorted = sorted(request.intervention_events, key=lambda x: x.timestamp, reverse=True)
    latest_interventions = interventions_sorted[:3]
    
    avg_completeness = sum(all_completeness) / len(all_completeness) if all_completeness else 0.0
    
    return TemporalStateSummary(
        admission_id=request.admission_id,
        window_hours=request.window_hours,
        current_vitals=current_vitals,
        trend_vectors=trend_vectors,
        volatility_index=volatility_index,
        latest_interventions=latest_interventions,
        data_completeness_ratio=avg_completeness,
        snapshot_generated_at=current_time
    )