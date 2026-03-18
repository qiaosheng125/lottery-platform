#!/bin/bash
# 自动创建GitHub私人仓库并推送代码

echo "=========================================="
echo "GitHub私人仓库创建和推送脚本"
echo "=========================================="
echo ""

# 检查是否提供了token
if [ -z "$GITHUB_TOKEN" ]; then
    echo "请输入您的GitHub Personal Access Token:"
    echo "(访问 https://github.com/settings/tokens 创建)"
    read -s GITHUB_TOKEN
    echo ""
fi

# GitHub用户名和仓库名
GITHUB_USER="qiaosheng125"
REPO_NAME="lottery-platform"

echo "步骤1: 创建私人仓库..."
CREATE_RESPONSE=$(curl -s -X POST \
  -H "Authorization: token $GITHUB_TOKEN" \
  -H "Accept: application/vnd.github.v3+json" \
  https://api.github.com/user/repos \
  -d "{
    \"name\": \"$REPO_NAME\",
    \"description\": \"彩票数据管理分发平台\",
    \"private\": true,
    \"auto_init\": false
  }")

# 检查是否创建成功
if echo "$CREATE_RESPONSE" | grep -q "\"full_name\""; then
    echo "✓ 仓库创建成功: https://github.com/$GITHUB_USER/$REPO_NAME"
elif echo "$CREATE_RESPONSE" | grep -q "already exists"; then
    echo "✓ 仓库已存在，继续推送..."
else
    echo "✗ 创建失败，错误信息:"
    echo "$CREATE_RESPONSE" | grep -o '"message":"[^"]*"'
    exit 1
fi

echo ""
echo "步骤2: 配置远程仓库..."
git remote remove origin 2>/dev/null
git remote add origin https://$GITHUB_TOKEN@github.com/$GITHUB_USER/$REPO_NAME.git
echo "✓ 远程仓库已配置"

echo ""
echo "步骤3: 推送代码到GitHub..."
git branch -M main
if git push -u origin main; then
    echo "✓ 代码推送成功！"
else
    echo "✗ 推送失败"
    exit 1
fi

echo ""
echo "=========================================="
echo "完成！"
echo "=========================================="
echo "仓库地址: https://github.com/$GITHUB_USER/$REPO_NAME"
echo ""
echo "注意: 为了安全，请运行以下命令移除token:"
echo "git remote set-url origin https://github.com/$GITHUB_USER/$REPO_NAME.git"
