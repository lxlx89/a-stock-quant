#!/bin/bash
# 量化选股系统 一键部署脚本
# 在服务器上运行: bash deploy.sh

set -e

DOMAIN="YOUR_DOMAIN"  # ← 改成你的域名
PROJECT_DIR="/opt/quant"

echo "=========================================="
echo "  量化选股系统 - 阿里云部署"
echo "=========================================="

# 1. 安装 Docker
echo "[1/6] 安装 Docker..."
if ! command -v docker &>/dev/null; then
    curl -fsSL https://get.docker.com | bash
    systemctl enable docker
    systemctl start docker
fi

if ! command -v docker-compose &>/dev/null && ! docker compose version &>/dev/null; then
    apt-get install -y docker-compose-plugin
fi
echo "  Docker 就绪"

# 2. 防火墙
echo "[2/6] 配置防火墙..."
ufw allow 22/tcp 2>/dev/null || true
ufw allow 80/tcp 2>/dev/null || true
ufw allow 443/tcp 2>/dev/null || true
ufw --force enable 2>/dev/null || true
echo "  防火墙已配置"

# 3. 创建项目目录
echo "[3/6] 创建目录..."
mkdir -p $PROJECT_DIR/data/outputs $PROJECT_DIR/data/cache $PROJECT_DIR/data/logs
mkdir -p $PROJECT_DIR/deploy/nginx/certs

# 4. 写入 Nginx 配置（替换域名）
echo "[4/6] 配置 Nginx..."
sed "s/YOUR_DOMAIN/$DOMAIN/g" deploy/nginx/nginx.conf > deploy/nginx/nginx.conf.tmp
mv deploy/nginx/nginx.conf.tmp deploy/nginx/nginx.conf

# 5. 构建并启动
echo "[5/6] 构建 Docker 镜像..."
cd $PROJECT_DIR
docker compose -f deploy/docker-compose.yml build
docker compose -f deploy/docker-compose.yml up -d

# 6. 等待就绪
echo "[6/6] 等待服务启动..."
sleep 5
curl -s http://localhost:8000/api/health && echo "" && echo "  API 就绪"
curl -s http://localhost:80/ && echo "" && echo "  Nginx 就绪"

echo ""
echo "=========================================="
echo "  部署完成！"
echo "  访问: http://$DOMAIN"
echo "  API:  http://$DOMAIN/api/scan"
echo "=========================================="
