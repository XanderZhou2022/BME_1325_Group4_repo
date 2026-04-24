"""
ICU 多智能体系统模拟脚本 (Simulator)

该脚本模拟典型 ICU 病患的临床过程，通过 API 向系统抛出事件数据（生命体征、干预、化验），
以供 Bedside Monitor 和 Intervention Tracker 等 Agent 收集和分析。

使用前请确保：
1. 后端服务 (FastAPI) 已在 http://localhost:8000 运行。
2. 数据库中已存在模拟所需的 Bed (例如 sim_b1, sim_b2) 和 Patient (例如 sim_p1, sim_p2)。
   (可参考 backend/seed_test_data.py 进行初始化)
"""

import requests
import time
from datetime import datetime, timedelta, timezone
from typing import Optional

# ==========================================
# 配置区域
# ==========================================

# API 基础地址
BASE_URL = "http://localhost:8000/api/v1"

# 模拟速度控制：
# False: 极速模式（适合调试，无延迟）
# True: 实时模式（模拟秒/分钟流逝，例如 delay 60 会休眠 60 秒）
REAL_TIME_DELAY = False

# 模拟场景定义
# 每个场景包含 admission_id, patient_id, bed_id 以及一系列步骤
SCENARIOS = [
    {
        "admission_id": "sim_adm_sepsis",
        "patient_id": "sim_p1",
        "bed_id": "sim_b1",
        "diagnosis": "Septic Shock",
        "reason": "ED Transfer due to hypotension",
        "severity": "critical",
        "team": "ICU Team A",
        "steps": [
            # T=0: 初始状态 - 感染性休克征象
            {"delay": 0, "type": "vital", "data": {"heart_rate": 122, "mean_arterial_pressure": 62, "temperature": 38.8, "respiratory_rate": 26, "spo2": 92, "fio2": 0.5}},
            {"delay": 5, "type": "lab", "data": {"lab_type": "lactate", "value": 4.2, "unit": "mmol/L", "flag": "high"}},
            
            # T=10min: 首次干预 - 液体复苏
            {"delay": 10, "type": "intervention", "data": {"type": "fluid", "desc": "500ml Normal Saline Bolus", "dosage": 500, "unit": "ml"}},
            
            # T=25min: 干预后评估 - 反应不佳 (MAP 未升)
            {"delay": 25, "type": "vital", "data": {"heart_rate": 128, "mean_arterial_pressure": 58, "temperature": 38.9, "respiratory_rate": 28, "spo2": 89, "fio2": 0.6}},
            
            # T=30min: 升压药介入
            {"delay": 30, "type": "intervention", "data": {"type": "vasopressor", "desc": "Norepinephrine started", "dosage": 0.05, "unit": "mcg/kg/min"}},
            
            # T=45min: 再次评估 - 趋势稳定
            {"delay": 45, "type": "vital", "data": {"heart_rate": 110, "mean_arterial_pressure": 66, "spo2": 94, "fio2": 0.5}},
        ]
    },
    {
        "admission_id": "sim_adm_resp",
        "patient_id": "sim_p2",
        "bed_id": "sim_b2",
        "diagnosis": "Acute Hypoxemic Respiratory Failure",
        "reason": "Ward deterioration",
        "severity": "unstable",
        "team": "ICU Team B",
        "steps": [
            # T=0: 呼吸困难
            {"delay": 0, "type": "vital", "data": {"heart_rate": 105, "respiratory_rate": 32, "spo2": 88, "fio2": 0.6, "pao2": 58}},
            
            # T=10min: 呼吸机调整
            {"delay": 10, "type": "intervention", "data": {"type": "ventilator_change", "desc": "PEEP increased from 8 to 12", "dosage": 12, "unit": "cmH2O"}},
            
            # T=30min: 评估 - 氧合改善
            {"delay": 30, "type": "vital", "data": {"heart_rate": 98, "respiratory_rate": 24, "spo2": 93, "fio2": 0.6, "pao2": 75}},
        ]
    },
    {
        "admission_id": "sim_adm_stable",
        "patient_id": "sim_p3",
        "bed_id": "sim_b3",
        "diagnosis": "Post-op Observation",
        "reason": "Routine Post-op Monitoring",
        "severity": "stable",
        "team": "ICU Team A",
        "steps": [
            {"delay": 0, "type": "vital", "data": {"heart_rate": 75, "mean_arterial_pressure": 85, "spo2": 98, "respiratory_rate": 16}},
            {"delay": 20, "type": "vital", "data": {"heart_rate": 72, "mean_arterial_pressure": 88, "spo2": 99, "respiratory_rate": 14}},
        ]
    }
]

# ==========================================
# 模拟逻辑
# ==========================================

def create_admission(session: requests.Session, scenario: dict) -> bool:
    """尝试创建 Admission (假设 Patient 和 Bed 已存在)"""
    now = datetime.now(timezone.utc).isoformat()
    payload = {
        "admission_id": scenario["admission_id"],
        "patient_id": scenario["patient_id"],
        "bed_id": scenario["bed_id"],
        "admission_code": f"SIM-{scenario['admission_id'][-3:]}",
        "admit_time": now,
        "primary_diagnosis": scenario["diagnosis"],
        "admission_reason": scenario["reason"],
        "severity_on_admission": scenario["severity"],
        "attending_team": scenario["team"],
        "scenario_tag": "simulation"
    }
    print(f"Creating Admission: {scenario['admission_id']}...")
    try:
        resp = session.post(f"{BASE_URL}/admissions", json=payload)
        if resp.status_code == 200:
            print(f"  -> Success: {scenario['admission_id']}")
            return True
        else:
            # 如果已存在或其他错误，尝试继续
            print(f"  -> Warning/Info: {resp.status_code} {resp.text}")
            return True 
    except Exception as e:
        print(f"  -> Error creating admission: {e}")
        return False

def send_event(session: requests.Session, admission_id: str, step: dict, current_time: datetime):
    """根据步骤类型发送对应的事件"""
    step_type = step["type"]
    data = step["data"]
    ts = current_time.isoformat()

    if step_type == "vital":
        url = f"{BASE_URL}/admissions/{admission_id}/events/vital_sign"
        payload = {
            "timestamp": ts,
            "source": "monitor",
            "priority": "normal",
            **data
        }
    elif step_type == "intervention":
        url = f"{BASE_URL}/admissions/{admission_id}/events/intervention"
        payload = {
            "timestamp": ts,
            "source": "nurse",
            "priority": "normal",
            "intervention_type": data["type"],
            "description": data["desc"],
            "dosage": data.get("dosage"),
            "unit": data.get("unit")
        }
    elif step_type == "lab":
        url = f"{BASE_URL}/admissions/{admission_id}/events/lab"
        payload = {
            "timestamp": ts,
            "source": "lab",
            "priority": "normal",
            "lab_type": data["lab_type"],
            "value": data["value"],
            "unit": data["unit"],
            "abnormal_flag": data["flag"]
        }
    else:
        print(f"  -> Unknown step type: {step_type}")
        return

    try:
        resp = session.post(url, json=payload)
        status = resp.status_code
        if status in [200, 201]:
            print(f"  [{ts[-8:]}] Sent {step_type} -> {status} OK")
        else:
            print(f"  [{ts[-8:]}] Sent {step_type} -> {status} FAILED: {resp.text[:100]}")
    except Exception as e:
        print(f"  -> Request Error: {e}")

def main():
    session = requests.Session()
    start_time = datetime.now(timezone.utc)
    
    # 预计算所有事件的绝对时间
    scheduled_events = []
    
    print("=== Scheduling Events ===")
    for scenario in SCENARIOS:
        # 尝试创建 Admission
        if not create_admission(session, scenario):
            print(f"Skipping scenario {scenario['admission_id']} due to admission creation failure.")
            continue
            
        for step in scenario["steps"]:
            abs_time = start_time + timedelta(minutes=step["delay"])
            scheduled_events.append({
                "time": abs_time,
                "admission_id": scenario["admission_id"],
                "step": step,
                "delay": step["delay"]
            })

    # 按时间排序
    scheduled_events.sort(key=lambda x: x["time"])

    print("\n=== Running Simulation ===")
    now = datetime.now(timezone.utc)
    
    for event in scheduled_events:
        # 等待直到事件时间
        time_to_wait = (event["time"] - now).total_seconds()
        if time_to_wait > 0:
            if REAL_TIME_DELAY:
                print(f"Waiting {time_to_wait:.1f}s...")
                time.sleep(time_to_wait)
        
        # 更新当前时间
        now = datetime.now(timezone.utc)
        send_event(session, event["admission_id"], event["step"], event["time"])

    print("\n=== Simulation Finished ===")
    print("Please check the logs and database for agent outputs.")

if __name__ == "__main__":
    main()