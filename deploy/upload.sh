#!/bin/bash
# 从本地上传代码到服务器（在 Windows Git Bash 中运行）
# 用法: bash upload.sh

SERVER_IP="47.113.189.191"
SERVER_USER="root"
PROJECT_DIR="/opt/quant"

echo "上传项目到 $SERVER_USER@$SERVER_IP:$PROJECT_DIR ..."

# 确保服务器上有目录
ssh $SERVER_USER@$SERVER_IP "mkdir -p $PROJECT_DIR"

# 上传核心文件
scp -r \
    src/ \
    config.py \
    deploy/ \
    $SERVER_USER@$SERVER_IP:$PROJECT_DIR/

echo "上传完成！"
echo "接下来 SSH 到服务器运行:"
echo "  ssh $SERVER_USER@$SERVER_IP"
echo "  cd $PROJECT_DIR && bash deploy/deploy.sh"
