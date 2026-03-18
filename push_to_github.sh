#!/bin/bash
# 推送到GitHub的脚本

echo "配置远程仓库..."
git remote add origin https://github.com/qiaosheng125/lottery-platform.git 2>/dev/null || git remote set-url origin https://github.com/qiaosheng125/lottery-platform.git

echo "查看远程仓库..."
git remote -v

echo "推送到GitHub..."
git branch -M main
git push -u origin main

echo "完成！"
