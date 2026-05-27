"""
一键部署：上传早盘文件 + 设置服务器 9:25 cron
"""
import paramiko
import os

import os

HOST = os.getenv("DEPLOY_HOST", "47.113.189.191")
USER = os.getenv("DEPLOY_USER", "root")
PASS = os.getenv("DEPLOY_PASSWORD", "")
REMOTE_DIR = "/opt/quant"

# 本地要上传的文件/目录
UPLOAD_ITEMS = [
    ("auto_morning.py", "auto_morning.py"),
    ("src/", "src/"),
    ("config.py", "config.py"),
    ("deploy/", "deploy/"),
]

client = paramiko.SSHClient()
client.set_missing_host_key_policy(paramiko.AutoAddPolicy())

print(f"[1/4] 连接 {USER}@{HOST} ...")
client.connect(HOST, username=USER, password=PASS)

sftp = client.open_sftp()

print("[2/4] 上传文件...")
base = "D:/code/a_stock_quant_assistant"
for local_rel, remote_rel in UPLOAD_ITEMS:
    local_path = os.path.join(base, local_rel)
    remote_path = f"{REMOTE_DIR}/{remote_rel}"
    if os.path.isdir(local_path):
        try:
            sftp.mkdir(remote_path)
        except:
            pass
        for root, dirs, files in os.walk(local_path):
            rel = os.path.relpath(root, local_path)
            if rel == ".":
                target_dir = remote_path
            else:
                target_dir = f"{remote_path}/{rel}"
                try:
                    sftp.mkdir(target_dir)
                except:
                    pass
            for f in files:
                src_file = os.path.join(root, f)
                dst_file = f"{target_dir}/{f}"
                sftp.put(src_file, dst_file)
                print(f"  {rel}/{f}" if rel != "." else f"  {f}")
    else:
        sftp.put(local_path, remote_path)
        print(f"  {local_rel}")

sftp.mkdir(f"{REMOTE_DIR}/data")
print("  (created data/)")

sftp.close()

print("[3/4] 设置 cron (9:25 北京时间 = 1:25 UTC, 周一至周五)...")
cron_line = "25 1 * * 1-5 cd /opt/quant && /usr/bin/python3 /opt/quant/auto_morning.py >> /opt/quant/data/morning_cron.log 2>&1"

# 读取现有 crontab，追加新行（去重）
stdin, stdout, stderr = client.exec_command("crontab -l 2>/dev/null || true")
existing = stdout.read().decode().strip()
lines = [l for l in existing.split("\n") if l.strip() and not l.startswith("#")]

# 移除旧版 morning cron (如有)
lines = [l for l in lines if "auto_morning" not in l]
lines.append(cron_line)
new_cron = "\n".join(lines) + "\n"

# 写入 crontab
cmd = f"echo '{new_cron}' | crontab -"
stdin2, stdout2, stderr2 = client.exec_command(cmd)
err = stderr2.read().decode()
if err:
    print(f"  Cron 设置失败: {err}")
else:
    print("  Cron 已设置!")

print("[4/4] 验证...")
stdin3, stdout3, stderr3 = client.exec_command("crontab -l")
print("  当前 crontab:")
for line in stdout3.read().decode().strip().split("\n"):
    print(f"    {line}")

# 重启 quant 服务使新代码生效
print("\n重启 quant 服务...")
stdin4, stdout4, stderr4 = client.exec_command("systemctl restart quant 2>&1 || echo 'restart failed'")
out = stdout4.read().decode() + stderr4.read().decode()
print(f"  {out.strip() or 'done'}")

client.close()
print("\n完成！面板地址: https://lhz456.xyz")
