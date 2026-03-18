"""
查询26034期中奖详情
"""
import sys
import os
sys.path.insert(0, os.path.dirname(__file__))

from app import create_app
from extensions import db
from models.ticket import LotteryTicket
from models.result import MatchResult

app = create_app()

with app.app_context():
    print("=" * 100)
    print("26034期中奖详情查询")
    print("=" * 100)

    # 查询赛果信息
    match_result = MatchResult.query.filter_by(detail_period='26034').first()
    if match_result:
        print(f"\n[赛果信息]")
        print(f"期号: {match_result.detail_period}")
        print(f"计算状态: {match_result.calc_status}")
        print(f"总票数: {match_result.tickets_total}")
        print(f"中奖票数: {match_result.tickets_winning}")
        print(f"总中奖金额: {match_result.total_winning_amount} 元")
        print(f"计算时间: {match_result.calc_started_at} ~ {match_result.calc_finished_at}")

    # 查询所有中奖票
    winning_tickets = LotteryTicket.query.filter_by(
        detail_period='26034',
        is_winning=True
    ).order_by(LotteryTicket.id).all()

    print(f"\n[中奖彩票列表] 共 {len(winning_tickets)} 张")
    print("-" * 100)

    for i, ticket in enumerate(winning_tickets, 1):
        print(f"\n第 {i} 张中奖票:")
        print(f"  票ID: {ticket.id}")
        print(f"  彩种: {ticket.lottery_type}")
        print(f"  倍投: {ticket.multiplier}")
        print(f"  投注内容: {ticket.raw_content}")
        print(f"  税前金额: {ticket.winning_gross} 元")
        print(f"  税后金额: {ticket.winning_amount} 元")
        print(f"  扣税金额: {ticket.winning_tax} 元")
        print(f"  用户: {ticket.assigned_username or '未分配'}")
        print(f"  完成时间: {ticket.completed_at}")

    # 查询未中奖的票（抽样显示）
    non_winning_tickets = LotteryTicket.query.filter_by(
        detail_period='26034',
        is_winning=False
    ).limit(5).all()

    print(f"\n[未中奖彩票示例] 显示前5张")
    print("-" * 100)

    for i, ticket in enumerate(non_winning_tickets, 1):
        print(f"\n第 {i} 张未中奖票:")
        print(f"  票ID: {ticket.id}")
        print(f"  彩种: {ticket.lottery_type}")
        print(f"  倍投: {ticket.multiplier}")
        print(f"  投注内容: {ticket.raw_content[:60]}...")

    # 查询部分赛果数据
    if match_result and match_result.result_data:
        print(f"\n[赛果数据示例] 显示前3个场次")
        print("-" * 100)
        import json
        result_data = match_result.result_data
        for seq_no in sorted(result_data.keys(), key=lambda x: int(x) if x.isdigit() else 0)[:3]:
            print(f"\n场次 {seq_no}:")
            print(json.dumps(result_data[seq_no], indent=2, ensure_ascii=False))

    print("\n" + "=" * 100)
