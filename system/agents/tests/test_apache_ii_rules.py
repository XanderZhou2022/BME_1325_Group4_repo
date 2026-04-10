import sys
import os
import unittest

# ==============================================================================
# 路径配置：确保能导入 risk_sentinel 中的代码
# 根据您的实际目录结构：system/agents/tests/ -> system/agents/risk_sentinel/
# ==============================================================================
current_dir = os.path.dirname(os.path.abspath(__file__))
parent_dir = os.path.dirname(current_dir)
target_dir = os.path.join(parent_dir, 'risk_sentinel')

# 将 risk_sentinel 文件夹加入系统路径，以便导入 apache_ii_rules
if target_dir not in sys.path:
    sys.path.insert(0, target_dir)

from apache_ii_rules import (
    get_temp_score, get_map_score, get_hr_score, get_rr_score,
    get_oxygen_score, get_ph_score, get_serum_sodium_score,
    get_serum_potassium_score, get_creatinine_score, get_hematocrit_score,
    get_wbc_score, get_gcs_score, get_age_score, get_chronic_health_points,
    calculate_apache_ii_score
)

class TestApacheIIScoring(unittest.TestCase):
    """APACHE II 评分单元测试"""

    # 1. 基础生命体征测试
    def test_temperature(self):
        self.assertEqual(get_temp_score(41.0), 4)
        self.assertEqual(get_temp_score(37.0), 0)
        self.assertEqual(get_temp_score(25.0), 4)
        self.assertEqual(get_temp_score(None), 0)

    def test_map(self):
        self.assertEqual(get_map_score(160), 4)
        self.assertEqual(get_map_score(80), 0)
        self.assertEqual(get_map_score(40), 4)

    def test_heart_rate(self):
        self.assertEqual(get_hr_score(180), 4)
        self.assertEqual(get_hr_score(75), 0)
        self.assertEqual(get_hr_score(30), 4)

    def test_respiratory_rate(self):
        self.assertEqual(get_rr_score(55), 4)
        self.assertEqual(get_rr_score(16), 0)
        self.assertEqual(get_rr_score(4), 4)

    # 2. 实验室指标测试（包含修复验证）
    def test_ph(self):
        self.assertEqual(get_ph_score(7.7), 4)
        self.assertEqual(get_ph_score(7.4), 0)
        self.assertEqual(get_ph_score(6.9), 4)

    def test_sodium(self):
        self.assertEqual(get_serum_sodium_score(185), 4)
        self.assertEqual(get_serum_sodium_score(140), 0)
        self.assertEqual(get_serum_sodium_score(100), 4)

    def test_potassium(self):
        self.assertEqual(get_serum_potassium_score(8.0), 4)
        self.assertEqual(get_serum_potassium_score(4.0), 0)
        self.assertEqual(get_serum_potassium_score(2.0), 4)

    def test_creatinine_fix(self):
        """验证肌酐 < 0.6 是否返回 0 分"""
        # 普通情况：0.5 应该是 0 分
        self.assertEqual(get_creatinine_score(0.5, arf=False), 0)
        # 普通情况：0.6 应该是 0 分
        self.assertEqual(get_creatinine_score(0.6, arf=False), 0)
        
        # ARF 情况：0.5 应该是 0 * 2 = 0 分
        self.assertEqual(get_creatinine_score(0.5, arf=True), 0)
        # ARF 情况：1.6 应该是 2 * 2 = 4 分
        self.assertEqual(get_creatinine_score(1.6, arf=True), 4)
        
        # 正常高分：4.0 应该是 4 分
        self.assertEqual(get_creatinine_score(4.0, arf=False), 4)

    def test_hematocrit(self):
        self.assertEqual(get_hematocrit_score(65), 4)
        self.assertEqual(get_hematocrit_score(40), 0)
        self.assertEqual(get_hematocrit_score(15), 4)

    def test_wbc(self):
        self.assertEqual(get_wbc_score(45), 4)
        self.assertEqual(get_wbc_score(10), 0)
        self.assertEqual(get_wbc_score(0.5), 4)

    # 3. 复杂逻辑测试
    def test_gcs(self):
        # 15 分意识清醒 -> 0 分
        self.assertEqual(get_gcs_score(15), 0)
        # 3 分昏迷 -> 12 分
        self.assertEqual(get_gcs_score(3), 12)

    def test_oxygen_logic(self):
        # 低氧吸入浓度 (FiO2 < 0.5) -> 用 PaO2
        # PaO2 90 -> 0 分
        self.assertEqual(get_oxygen_score(fiO2=0.21, paO2=90), 0)
        # PaO2 50 -> 4 分
        self.assertEqual(get_oxygen_score(fiO2=0.4, paO2=50), 4)

    def test_age(self):
        self.assertEqual(get_age_score(40), 0)
        self.assertEqual(get_age_score(60), 3)
        self.assertEqual(get_age_score(80), 6)

    def test_chronic_health(self):
        # 非手术器官衰竭 -> 5
        self.assertEqual(get_chronic_health_points(has_organ_insufficiency=True), 5)
        # 择期手术器官衰竭 -> 2
        self.assertEqual(get_chronic_health_points(has_organ_insufficiency=True, surgery_type="elective"), 2)
        # 无病史 -> 0
        self.assertEqual(get_chronic_health_points(), 0)

    # 4. 总分计算集成测试
    def test_total_score_calculation(self):
        vitals = {
            "temp": 37.0, "map": 85, "hr": 80, "rr": 16,
            "pao2": 90, "ph": 7.40, "sodium": 140, "potassium": 4.0,
            "creatinine": 0.8, "hematocrit": 42, "wbc": 8.0, "gcs": 15
        }
        # 一个健康年轻人的总分应该是 0
        score = calculate_apache_ii_score(vitals, age=25)
        self.assertEqual(score, 0)

# ==============================================================================
# 运行入口
# ==============================================================================
if __name__ == '__main__':
    # 这行代码允许直接 python 运行此脚本
    unittest.main()