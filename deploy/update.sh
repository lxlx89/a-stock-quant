#!/bin/bash
# 服务器端一键更新脚本
# 用法: ssh root@47.113.189.191 "cd /opt/quant && bash deploy/update.sh"
set -e

REPO_URL="https://github.com/lxlx89/a-stock-quant.git"
PROJECT_DIR="/opt/quant"

cd $PROJECT_DIR

# 如果还没初始化 git，先初始化
if [ ! -d ".git" ]; then
    echo "初始化 Git..."
    git init
    git remote add origin "$REPO_URL"
fi

# 拉取最新代码
echo "拉取最新代码..."
git fetch origin
git reset --hard origin/main

# 重建并重启容器
echo "重建 Docker 镜像..."
docker compose -f deploy/docker-compose.yml build app --quiet

echo "重启服务..."
docker compose -f deploy/docker-compose.yml up -d --remove-orphans

echo "更新完成!"
curl -s http://localhost/api/health
