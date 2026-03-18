"""
测试延期场次和扣税逻辑
"""
import sys
import os
sys.path.insert(0, os.path.dirname(__file__))

from utils.winning_calculator import calculate_winning
from decimal import Decimal

# 测试延期场次
print("=" * 80)
print("测试1: 延期场次处理")
print("=" * 80)

# 场次1延期，场次2正常
result_data_postponed = {
    "1": {
        "SPF": {"result": "延期", "sp": 1.0},  # 延期场次，SP=1.0
    },
    "2": {
        "SPF": {"result": "3", "sp": 2.5},
    }
}

# 投注：场次1选0（实际延期），场次2选3（正常中奖）
raw_content = "SPF|1=0,2=3|2*1|1"
is_winning, gross, net, tax = calculate_winning(raw_content, result_data_postponed, 1)

print(f"投注内容: {raw_content}")
print(f"场次1: 延期（投注选0，但延期任何选项都算中）")
print(f"场次2: 赛果3（投注选3，正常中奖）")
print(f"是否中奖: {is_winning}")
print(f"税前金额: {gross} 元")
print(f"计算公式: 1.0(延期SP) × 2.5(场次2 SP) × 2(基注) × 1(倍投) × 1.3(系数) = {1.0 * 2.5 * 2 * 1 * 1.3}")
print()

# 测试扣税逻辑
print("=" * 80)
print("测试2: 扣税逻辑（超过10000元）")
print("=" * 80)

# 构造一个高SP值的场次，使中奖金额超过10000元
result_data_high = {
    "1": {"SPF": {"result": "3", "sp": 5000.0}},
}

raw_content_high = "SPF|1=3|2*1|1"
is_winning, gross, net, tax = calculate_winning(raw_content_high, result_data_high, 1)

print(f"投注内容: {raw_content_high}")
print(f"场次1: 赛果3，SP=5000.0（模拟高赔率）")
print(f"是否中奖: {is_winning}")
print(f"税前金额: {gross} 元")
print(f"税后金额: {net} 元")
print(f"扣税金额: {tax} 元")
print(f"扣税比例: {(tax / gross * 100):.1f}%")
print(f"验证: 税前 {gross} > 10000，应扣税20%")
print(f"验证: 税后 = 税前 × 0.8 = {gross * Decimal('0.8')}")
print()

# 测试不扣税逻辑
print("=" * 80)
print("测试3: 不扣税逻辑（不超过10000元）")
print("=" * 80)

result_data_low = {
    "1": {"SPF": {"result": "3", "sp": 100.0}},
}

raw_content_low = "SPF|1=3|2*1|1"
is_winning, gross, net, tax = calculate_winning(raw_content_low, result_data_low, 1)

print(f"投注内容: {raw_content_low}")
print(f"场次1: 赛果3，SP=100.0")
print(f"是否中奖: {is_winning}")
print(f"税前金额: {gross} 元")
print(f"税后金额: {net} 元")
print(f"扣税金额: {tax} 元")
print(f"验证: 税前 {gross} <= 10000，不扣税")
print(f"验证: 税后 = 税前 = {gross}")
print()

# 测试多个延期场次
print("=" * 80)
print("测试4: 多个延期场次")
print("=" * 80)

result_data_multi_postponed = {
    "1": {"SPF": {"result": "延期", "sp": 1.0}},
    "2": {"SPF": {"result": "postponed", "sp": 1.0}},  # 英文延期
    "3": {"SPF": {"result": "3", "sp": 3.0}},
}

raw_content_multi = "SPF|1=0,2=1,3=3|2*1|1"
is_winning, gross, net, tax = calculate_winning(raw_content_multi, result_data_multi_postponed, 1)

print(f"投注内容: {raw_content_multi}")
print(f"场次1: 延期（中文）")
print(f"场次2: postponed（英文）")
print(f"场次3: 赛果3，SP=3.0")
print(f"是否中奖: {is_winning}")
print(f"税前金额: {gross} 元")
print(f"计算公式: 1.0 × 1.0 × 3.0 × 2 × 1 × 1.3 = {1.0 * 1.0 * 3.0 * 2 * 1 * 1.3}")
print()

print("=" * 80)
print("所有延期和扣税测试完成")
print("=" * 80)
