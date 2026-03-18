"""
26034期完整兑奖流程测试

步骤：
1. 检查数据库连接
2. 上传测试彩票数据（如果没有）
3. 上传26034期彩果文件
4. 触发中奖计算
5. 查看计算结果
"""

import sys
import os
sys.path.insert(0, os.path.dirname(__file__))

from app import create_app
from extensions import db
from models.ticket import LotteryTicket
from models.result import MatchResult, ResultFile
from models.file import UploadedFile
from services.result_parser import parse_result_file
from services.winning_calc_service import process_match_result
from services.file_parser import process_uploaded_file
from datetime import datetime
from decimal import Decimal

print("=" * 80)
print("26034期完整兑奖流程测试")
print("=" * 80)

app = create_app()

with app.app_context():
    # 步骤1: 检查数据库连接
    print("\n[步骤1] 检查数据库连接...")
    try:
        db.session.execute(db.text('SELECT 1'))
        print("[OK] 数据库连接正常")
    except Exception as e:
        print(f"[FAIL] 数据库连接失败: {e}")
        sys.exit(1)

    # 步骤2: 检查是否有26034期的彩票数据
    print("\n[步骤2] 检查26034期彩票数据...")
    existing_tickets = LotteryTicket.query.filter_by(detail_period='26034').all()
    print(f"当前数据库中26034期的彩票数量: {len(existing_tickets)}")

    if len(existing_tickets) == 0:
        print("\n需要先上传彩票数据文件...")
        test_files = [
            r'C:\Users\徐逸飞\Desktop\测试\岩_P26总进球3倍投_金额180元_8张_21.55_26034.txt',
            r'C:\Users\徐逸飞\Desktop\测试\岩_V33胜负5倍投_金额200元_9张_21.55_26034.txt',
            r'C:\Users\徐逸飞\Desktop\测试\岩_W39比分2倍投_金额120元_8张_21.55_26034.txt',
            r'C:\Users\徐逸飞\Desktop\测试\测_P7上下盘3倍投_金额150元_7张_21.55_26034.txt',
            r'C:\Users\徐逸飞\Desktop\测试\岩_V99胜平负3倍投_金额600元_27张_21.55_26034.txt',
            r'C:\Users\徐逸飞\Desktop\测试\岩_P33半全场2倍投_金额120元_8张_21.55_26034.txt',
        ]

        for test_file in test_files:
            if os.path.exists(test_file):
                print(f"\n上传文件: {os.path.basename(test_file)}")
                result = process_uploaded_file(test_file, uploader_id=1)
                if result['success']:
                    print(f"  [OK] 成功解析 {result['total_tickets']} 张彩票")
                else:
                    print(f"  [FAIL] 解析失败: {result.get('error')}")

        # 重新统计
        existing_tickets = LotteryTicket.query.filter_by(detail_period='26034').all()
        print(f"\n上传后，26034期彩票总数: {len(existing_tickets)}")

    # 模拟一些票已经完成（状态改为completed）
    print("\n[步骤2.5] 模拟部分彩票已出票...")
    completed_count = 0
    for ticket in existing_tickets[:20]:  # 前20张改为已完成
        if ticket.status == 'pending':
            ticket.status = 'completed'
            ticket.assigned_user_id = 1
            ticket.assigned_username = '测试用户'
            ticket.completed_at = datetime.now()
            completed_count += 1

    if completed_count > 0:
        db.session.commit()
        print(f"[OK] 已将 {completed_count} 张彩票状态改为completed")

    # 步骤3: 上传26034期彩果文件
    print("\n[步骤3] 上传26034期彩果文件...")
    result_file_path = r'C:\Users\徐逸飞\Desktop\测试\26034期彩果.txt'

    if not os.path.exists(result_file_path):
        print(f"[FAIL] 彩果文件不存在: {result_file_path}")
        sys.exit(1)

    print(f"彩果文件: {result_file_path}")

    # 解析彩果文件
    result = parse_result_file(result_file_path, '26034', uploader_id=1)

    if not result['success']:
        print(f"[FAIL] 彩果文件解析失败: {result.get('error')}")
        sys.exit(1)

    print(f"[OK] 彩果文件解析成功，共解析 {result['count']} 个场次")
    match_result_id = result['match_result_id']

    # 步骤4: 触发中奖计算
    print("\n[步骤4] 触发中奖计算...")
    match_result = MatchResult.query.get(match_result_id)
    print(f"期号: {match_result.detail_period}")
    print(f"计算状态: {match_result.calc_status}")

    # 执行中奖计算
    print("\n开始计算中奖...")
    process_match_result(match_result_id, app)

    # 步骤5: 查看计算结果
    print("\n[步骤5] 查看计算结果...")
    db.session.refresh(match_result)

    print(f"\n计算状态: {match_result.calc_status}")
    print(f"开始时间: {match_result.calc_started_at}")
    print(f"完成时间: {match_result.calc_finished_at}")
    print(f"总票数: {match_result.tickets_total}")
    print(f"中奖票数: {match_result.tickets_winning}")
    print(f"总中奖金额: {match_result.total_winning_amount} 元")

    # 查看中奖详情
    print("\n[中奖详情]")
    winning_tickets = LotteryTicket.query.filter_by(
        detail_period='26034',
        is_winning=True
    ).all()

    print(f"\n共有 {len(winning_tickets)} 张彩票中奖")

    if len(winning_tickets) > 0:
        print("\n前10张中奖彩票详情:")
        print("-" * 120)
        print(f"{'票ID':<8} {'彩种':<8} {'倍投':<6} {'投注内容':<40} {'税前':<12} {'税后':<12} {'扣税':<12}")
        print("-" * 120)

        for i, ticket in enumerate(winning_tickets[:10], 1):
            print(f"{ticket.id:<8} {ticket.lottery_type:<8} {ticket.multiplier:<6} "
                  f"{ticket.raw_content[:40]:<40} "
                  f"{float(ticket.winning_gross or 0):<12.2f} "
                  f"{float(ticket.winning_amount or 0):<12.2f} "
                  f"{float(ticket.winning_tax or 0):<12.2f}")

    # 统计各玩法中奖情况
    print("\n[各玩法中奖统计]")
    from sqlalchemy import func
    stats = db.session.query(
        LotteryTicket.lottery_type,
        func.count(LotteryTicket.id).label('count'),
        func.sum(LotteryTicket.winning_amount).label('total')
    ).filter(
        LotteryTicket.detail_period == '26034',
        LotteryTicket.is_winning == True
    ).group_by(LotteryTicket.lottery_type).all()

    print("-" * 60)
    print(f"{'玩法':<15} {'中奖票数':<15} {'总中奖金额(元)':<20}")
    print("-" * 60)
    for stat in stats:
        lottery_type = stat[0] or '未知'
        count = stat[1]
        total = float(stat[2] or 0)
        print(f"{lottery_type:<15} {count:<15} {total:<20.2f}")
    print("-" * 60)

    # 检查是否有扣税的票
    print("\n[扣税情况检查]")
    taxed_tickets = LotteryTicket.query.filter(
        LotteryTicket.detail_period == '26034',
        LotteryTicket.winning_tax > 0
    ).all()

    if len(taxed_tickets) > 0:
        print(f"共有 {len(taxed_tickets)} 张彩票需要扣税（中奖金额>10000元）")
        for ticket in taxed_tickets:
            print(f"  票ID {ticket.id}: 税前 {ticket.winning_gross} 元, "
                  f"税后 {ticket.winning_amount} 元, 扣税 {ticket.winning_tax} 元")
    else:
        print("没有彩票需要扣税（所有中奖金额都<=10000元）")

    print("\n" + "=" * 80)
    print("26034期兑奖流程测试完成")
    print("=" * 80)
