# Milk-Link Docker 镜像部署指南

## 📦 镜像信息

- **镜像名称**: milk-link:latest
- **导出文件**: milk-link-latest.tar.gz （压缩版）
- **文件大小**: 80MB
- **构建时间**: 2026-03-05 22:42
- **包含迁移**: 360b08025977 (添加 unit 和 amount_value 字段)

## 🚀 部署步骤

### 0. 前置说明

⚠️ **重要**：数据库结构已通过 `manual-upgrade.sql` 手动升级完成，所有新字段已添加。
- 当前数据库迁移版本：`a2555c5f3358`（已回退）
- 容器启动时会自动升级到：`360b08025977`
- 这样可以让 entrypoint 脚本正常执行所有迁移

### 1. 上传镜像到服务器

```bash
# 在本地执行（使用压缩版本，传输更快）
scp milk-link-latest.tar.gz ubuntu@43.138.35.101:~/
```

### 2. 在目标服务器导入镜像

```bash
# SSH 到服务器
ssh ubuntu@43.138.35.101

# 解压并导入镜像
gunzip -c ~/milk-link-latest.tar.gz | docker load

# 验证镜像已导入
docker images | grep milk-link
```

确保服务器上有以下文件：

```
~/docker-compose-yaml/milk-link/
├── .env                # 环境变量配置
├── docker-compose.yml  # Docker Compose 配置
└── mosquitto.conf      # MQTT 配置（可选）
```

### 3. 停止旧容器并启动新服务

```bash
cd ~/docker-compose-yaml/milk-link

# 停止并删除旧容器
sudo docker-compose down

# 启动新容器（entrypoint 会自动运行 Alembic 迁移）
sudo docker-compose up -d
```

### 4. 查看启动日志

```bash
# 实时查看日志，确认迁移成功
sudo docker-compose logs -f --tail=100
```

**成功启动应看到**：
```
[entrypoint] Running Alembic migrations...
INFO  [alembic.runtime.migration] Context impl MySQLImpl.
INFO  [alembic.runtime.migration] Running upgrade a2555c5f3358 -> b3f1a8e2c047
INFO  [alembic.runtime.migration] Running upgrade b3f1a8e2c047 -> 360b08025977
[entrypoint] Starting Uvicorn...
INFO:     Application startup complete.
INFO:     Uvicorn running on http://0.0.0.0:8000
```

### 5. 验证部署

**健康检查**：
```bash
curl http://43.138.35.101:8000/health
```

**访问管理后台**：
- URL: http://43.138.35.101:8000/admin
- 用户名: `admin`
- 密码: `CalmMilk@2026`

**测试新功能**：
1. ✅ Tab 页切换（全部 | 🍼喂奶 | 🥣辅食）
2. ✅ 筛选条件面板（日期范围、设备ID、记录类型）
3. ✅ 分页浏览记录
4. ✅ 导出 CSV
5. ✅ 添加辅食记录（单位为克）

## 🔧 环境变量配置

关键环境变量（在 `.env` 文件中配置）：

```env
# 数据库
DATABASE_URL=mysql+aiomysql://user:pass@host:3306/dbname

# 企业微信
WECHAT_WEBHOOK_KEY=your-webhook-key

# 设备密钥
DEVICE_SECRET=your-secret

# 管理后台
ADMIN_USERNAME=admin
ADMIN_PASSWORD=your-password

# MQTT
MQTT_BROKER_HOST=your-mqtt-host
MQTT_BROKER_PORT=1883
MQTT_USERNAME=your-mqtt-user
MQTT_PASSWORD=your-mqtt-password
```

## 📊 访问服务

- **管理后台**: http://your-server:8000/admin
- **健康检查**: http://your-server:8000/health
- **API 文档**: http://your-server:8000/docs

## 🔄 更新部署

### 方式一：使用新镜像

```bash
# 停止旧容器
docker compose down

# 导入新镜像
docker load -i milk-link-latest-new.tar

# 重新启动
docker compose up -d
```

### 方式二：重新构建

```bash
# 在开发机器上重新构建
docker build -t milk-link:$(date +%Y%m%d) .

# 导出新镜像
docker save milk-link:$(date +%Y%m%d) -o milk-link-$(date +%Y%m%d).tar
```

## 🐛 故障排查

### 查看容器日志
```bash
docker logs -f milk-link
```

### 进入容器调试
```bash
docker exec -it milk-link sh
```

### 重启服务
```bash
docker restart milk-link
```

### 数据库迁移问题
```bash
# 手动执行迁移
docker exec milk-link uv run alembic upgrade head
```

## 📝 注意事项

1. **数据库连接**: 确保 `DATABASE_URL` 正确，数据库服务器允许容器 IP 访问
2. **MQTT 连接**: 如果使用 docker-compose，MQTT broker 地址应为 `mosquitto`（服务名）
3. **端口映射**: 确保宿主机 8000 端口未被占用
4. **时区设置**: 默认使用 Asia/Shanghai，可通过环境变量 `TIMEZONE` 修改
5. **日志级别**: 生产环境建议设置 `DEBUG_NO_PUSH=false` 以启用企业微信推送

## 🔒 安全建议

- 修改默认的 `ADMIN_PASSWORD`
- 使用强密码作为 `DEVICE_SECRET`
- 配置防火墙规则，限制 8000 端口访问
- 定期备份数据库

## 📞 联系支持

如有问题，请检查日志并参考项目文档。
