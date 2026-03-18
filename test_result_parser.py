"""
测试赛果文件解析
"""
import sys
import os
sys.path.insert(0, os.path.dirname(__file__))

from services.result_parser import parse_result_file
import json

# 测试解析彩果文件
result_file_path = r'C:\Users\徐逸飞\Desktop\测试\26034期彩果.txt'
detail_period = '26034'

print(f"正在解析文件: {result_file_path}")
print(f"期号: {detail_period}")
print("-" * 80)

# 模拟解析（不写入数据库）
try:
    with open(result_file_path, 'r', encoding='utf-8') as f:
        lines = f.readlines()
except UnicodeDecodeError:
    with open(result_file_path, 'r', encoding='gbk') as f:
        lines = f.readlines()

result_data = {}
count = 0

for line in lines:
    line = line.strip()
    if not line or '序号' in line:
        continue

    cols = line.split('\t')
    if len(cols) < 2:
        import re
        cols = re.split(r'\s+', line)

    if not cols:
        continue

    # 提取序号
    first_col = cols[0].strip()
    if '→' in first_col:
        seq_no = first_col.split('→')[-1].strip()
    else:
        seq_no = first_col

    if not seq_no.isdigit():
        continue

    # 解析这一行
    def safe_get(idx):
        return cols[idx].strip() if idx < len(cols) else ''

    field_data = {}

    # SPF
    spf_result = safe_get(1)
    spf_sp = safe_get(2)
    if spf_result:
        field_data['SPF'] = {'result': spf_result, 'sp': float(spf_sp) if spf_sp else 0}

    # CBF
    cbf_result = safe_get(3)
    cbf_sp = safe_get(4)
    if cbf_result:
        field_data['CBF'] = {'result': cbf_result, 'sp': float(cbf_sp) if cbf_sp else 0}

    # JQS
    jqs_result = safe_get(5)
    jqs_sp = safe_get(6)
    if jqs_result:
        field_data['JQS'] = {'result': jqs_result, 'sp': float(jqs_sp) if jqs_sp else 0}

    # BQC
    bqc_result = safe_get(7)
    bqc_sp = safe_get(8)
    if bqc_result:
        field_data['BQC'] = {'result': bqc_result, 'sp': float(bqc_sp) if bqc_sp else 0}

    # SXP - 转换为数字
    SXP_MAP = {'上单': '0', '上双': '1', '下单': '2', '下双': '3'}
    sxp_result_raw = safe_get(9)
    sxp_sp = safe_get(10)
    if sxp_result_raw:
        sxp_result = SXP_MAP.get(sxp_result_raw, sxp_result_raw)
        field_data['SXP'] = {'result': sxp_result, 'sp': float(sxp_sp) if sxp_sp else 0}

    # SF
    SF_MAP = {'胜': '3', '负': '0', '平': '1'}
    sf_result_raw = safe_get(12)
    sf_sp = safe_get(13)
    if sf_result_raw:
        sf_result = SF_MAP.get(sf_result_raw, sf_result_raw)
        field_data['SF'] = {'result': sf_result, 'sp': float(sf_sp) if sf_sp else 0}

    if field_data:
        result_data[seq_no] = field_data
        count += 1
        if count <= 3:  # 只打印前3条
            print(f"\n场次 {seq_no}:")
            print(json.dumps(field_data, indent=2, ensure_ascii=False))

print(f"\n{'='*80}")
print(f"解析完成！共解析 {count} 个场次")
print(f"\n示例：场次1的数据")
if '1' in result_data:
    print(json.dumps(result_data['1'], indent=2, ensure_ascii=False))
