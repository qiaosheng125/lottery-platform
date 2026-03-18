"""
测试中奖计算逻辑
"""
import sys
import os
sys.path.insert(0, os.path.dirname(__file__))

from utils.winning_calculator import calculate_winning
from decimal import Decimal

# 模拟赛果数据（从解析结果中提取）
result_data = {
    "1": {
        "SPF": {"result": "3", "sp": 4.918},
        "CBF": {"result": "1-3", "sp": 17.454},
        "JQS": {"result": "1", "sp": 6.812},
        "BQC": {"result": "1-3", "sp": 11.514},
        "SXP": {"result": "2", "sp": 6.206},  # 下单
        "SF": {"result": "3", "sp": 1.88}
    },
    "2": {
        "SPF": {"result": "0", "sp": 3.627},
        "CBF": {"result": "0-0", "sp": 16.527},
        "JQS": {"result": "3", "sp": 4.799},
        "BQC": {"result": "0-0", "sp": 8.135},
        "SXP": {"result": "0", "sp": 3.271},  # 上单
        "SF": {"result": "0", "sp": 2.06}
    },
    "3": {
        "SPF": {"result": "1", "sp": 3.323},
        "CBF": {"result": "1-1", "sp": 6.88},
        "JQS": {"result": "2", "sp": 3.399},
        "BQC": {"result": "1-1", "sp": 6.386},
        "SXP": {"result": "3", "sp": 2.762},  # 下双
        "SF": {"result": "3", "sp": 1.5}
    }
}

# 测试用例
test_cases = [
    {
        "name": "SPF单场全中",
        "raw_content": "SPF|1=3|2*1|1",
        "multiplier": 1,
        "expected_win": True,
        "description": "场次1选3（主胜），赛果是3，应该中奖"
    },
    {
        "name": "SPF单场不中",
        "raw_content": "SPF|1=0|2*1|1",
        "multiplier": 1,
        "expected_win": False,
        "description": "场次1选0（客胜），赛果是3，不中奖"
    },
    {
        "name": "SPF两场串关全中",
        "raw_content": "SPF|1=3,2=0|2*1|1",
        "multiplier": 1,
        "expected_win": True,
        "description": "场次1选3，场次2选0，都中奖"
    },
    {
        "name": "SPF两场串关部分中",
        "raw_content": "SPF|1=3,2=1|2*1|1",
        "multiplier": 1,
        "expected_win": False,
        "description": "场次1选3中，场次2选1不中（实际是0），不中奖"
    },
    {
        "name": "SPF单场多选项",
        "raw_content": "SPF|1=0/1/3|2*1|1",
        "multiplier": 1,
        "expected_win": True,
        "description": "场次1选0/1/3，赛果是3，应该中奖"
    },
    {
        "name": "SXP单场中奖",
        "raw_content": "SXP|1=2|2*1|1",
        "multiplier": 1,
        "expected_win": True,
        "description": "场次1选2（下单），赛果是2（下单），应该中奖"
    },
    {
        "name": "SXP单场不中",
        "raw_content": "SXP|1=0|2*1|1",
        "multiplier": 1,
        "expected_win": False,
        "description": "场次1选0（上单），赛果是2（下单），不中奖"
    },
    {
        "name": "SXP两场串关",
        "raw_content": "SXP|1=2,2=0|2*1|1",
        "multiplier": 1,
        "expected_win": True,
        "description": "场次1选2（下单），场次2选0（上单），都中奖"
    },
    {
        "name": "CBF比分中奖",
        "raw_content": "CBF|1=1-3|2*1|1",
        "multiplier": 1,
        "expected_win": True,
        "description": "场次1选1-3，赛果是1-3，应该中奖"
    },
    {
        "name": "JQS总进球中奖",
        "raw_content": "JQS|1=1|2*1|1",
        "multiplier": 1,
        "expected_win": True,
        "description": "场次1选1球，赛果是1球，应该中奖"
    },
    {
        "name": "BQC半全场中奖",
        "raw_content": "BQC|1=1-3|2*1|1",
        "multiplier": 1,
        "expected_win": True,
        "description": "场次1选1-3（半场平，全场客胜），赛果是1-3，应该中奖"
    },
    {
        "name": "SF胜负中奖",
        "raw_content": "SF|1=3|2*1|1",
        "multiplier": 1,
        "expected_win": True,
        "description": "场次1选3（主胜），赛果是3，应该中奖"
    },
    {
        "name": "高倍投中奖",
        "raw_content": "SPF|1=3|2*1|5",
        "multiplier": 5,
        "expected_win": True,
        "description": "场次1选3，5倍投注，应该中奖且金额×5"
    },
]

print("=" * 80)
print("中奖计算测试")
print("=" * 80)

passed = 0
failed = 0

for i, test in enumerate(test_cases, 1):
    print(f"\n测试 {i}: {test['name']}")
    print(f"描述: {test['description']}")
    print(f"投注内容: {test['raw_content']}")
    print(f"倍投: {test['multiplier']}")

    is_winning, gross, net, tax = calculate_winning(
        test['raw_content'],
        result_data,
        test['multiplier']
    )

    print(f"预期中奖: {test['expected_win']}")
    print(f"实际中奖: {is_winning}")

    if is_winning:
        print(f"税前金额: {gross} 元")
        print(f"税后金额: {net} 元")
        if tax > 0:
            print(f"扣税金额: {tax} 元")

    if is_winning == test['expected_win']:
        print("[通过]")
        passed += 1
    else:
        print("[失败]")
        failed += 1

print("\n" + "=" * 80)
print(f"测试结果: {passed} 通过, {failed} 失败")
print("=" * 80)
