# 🍼 Milk-Link

M5Stack Chain DualKey 宝宝喂奶记录系统——按键记录，自动推送企业微信。

---

## 功能

| 操作 | 行为 |
|------|------|
| 单键按下 | 记录一次喂奶（白天 160ml / 夜晚 90ml / 辅食后 120ml） |
| 双键同时按下 | 记录一次辅食，下次喂奶自动调整为 120ml |
| 5 分钟内重复按 | 服务端拒绝（409），LED 橙色快闪 |

每次喂奶成功后，企业微信群机器人推送当日完整记录。每周日 09:00 推送周报，每月 1 日 09:00 推送月报。

---

## 项目结构

```
Milk-Link/
├── app/                        # FastAPI 服务端
│   ├── main.py                 # 路由入口（/feed、/solid、/stats/today）
│   ├── models.py               # SQLAlchemy 数据模型
│   ├── schemas.py              # Pydantic 请求/响应 Schema
│   ├── config.py               # 环境变量配置
│   ├── database.py             # 异步数据库连接
│   └── services/
│       ├── feeding.py          # 喂奶 / 辅食业务逻辑
│       ├── reports.py          # 今日 / 周报 / 月报统计
│       └── wechat.py           # 企业微信 Webhook 推送
├── alembic/                    # 数据库迁移
│   └── versions/
│       ├── a2555c5f3358_...    # 创建 feeding_records 表
│       └── b3f1a8e2c047_...    # 新增 record_type 字段
├── firmware/
│   └── m5stack/
│       └── main/
│           ├── main.ino        # Arduino 固件主程序
│           └── config.h        # WiFi / 服务器 / 设备配置
├── docker-compose.yml
├── Dockerfile
├── entrypoint.sh
├── pyproject.toml
└── .env                        # 环境变量（不提交 git）
```

---

## 快速开始

### 1. 环境变量

复制 `.env.example` 为 `.env` 并填写：

```env
DATABASE_URL=mysql+aiomysql://user:password@host:3306/milklink
WECHAT_WEBHOOK_KEY=xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx
DEVICE_SECRET=自定义密钥（与固件 config.h 保持一致）

# 调试阶段设为 true，跳过微信推送；上线前改为 false
DEBUG_NO_PUSH=false
```

### 2. 数据库迁移

```bash
alembic upgrade head
```

### 3. 启动服务

**Docker（推荐）**

```bash
docker compose up -d
```

**本地开发**

```bash
uv sync
uvicorn app.main:app --reload --port 8000
```

---

## 运维操作

### 构建 Docker 镜像

在本机（开发环境）执行：

```bash
# 构建镜像，tag 为 milk-link:latest
docker build -t milk-link:latest .

# 如需指定版本号
docker build -t milk-link:1.0.0 .
```

---

### 打包镜像传输到服务器

```bash
# 1. 将镜像导出为 tar 文件
docker save milk-link:latest | gzip > milk-link.tar.gz

# 2. 上传到服务器（替换 user 和 server-ip）
scp milk-link.tar.gz user@server-ip:/opt/milk-link/

# 3. 在服务器上加载镜像
ssh user@server-ip
docker load < /opt/milk-link/milk-link.tar.gz

# 验证镜像已加载
docker images | grep milk-link
```

---

### 首次部署

```bash
# 服务器上，进入项目目录
cd /opt/milk-link

# 确保 .env 文件已配置好
cp .env.example .env
vi .env   # 填写数据库、微信 Webhook Key、设备密钥

# 启动容器（自动执行数据库迁移后启动服务）
docker compose up -d

# 查看启动日志
docker compose logs -f
```

---

### 日常运维命令

```bash
# 查看运行状态
docker compose ps

# 实时查看日志
docker compose logs -f

# 查看最近 100 行日志
docker compose logs --tail=100

# 重启服务
docker compose restart

# 停止服务
docker compose down

# 停止并删除数据卷（危险！会清空数据库）
docker compose down -v
```

---

### 更新部署

```bash
# 本机重新构建并导出
docker build -t milk-link:latest .
docker save milk-link:latest | gzip > milk-link.tar.gz
scp milk-link.tar.gz user@server-ip:/opt/milk-link/

# 服务器上：加载新镜像并重启
ssh user@server-ip "cd /opt/milk-link && \
  docker load < milk-link.tar.gz && \
  docker compose down && \
  docker compose up -d"
```

> **说明**：`entrypoint.sh` 会在容器启动时自动执行 `alembic upgrade head`，更新代码后无需手动迁移数据库。

---

## 固件烧录

### 依赖库（Arduino IDE）

| 库 | 版本要求 |
|----|---------|
| M5Unified | >= 0.2.11 |
| ArduinoJson (Benoit Blanchon) | >= 7.x |
| Adafruit NeoPixel | >= 1.15.2 |

开发板管理器搜索 `M5Stack`，安装 >= 3.2.4，选择 **M5ChainDualKey**。

### 修改 `firmware/m5stack/main/config.h`

```cpp
#define WIFI_SSID     "你的WiFi名称"
#define WIFI_PASSWORD "你的WiFi密码"
#define SERVER_URL    "https://你的服务器地址"   // 不含末尾斜杠
#define DEVICE_ID     "m5stack-01"
#define DEVICE_SECRET "与服务端 .env DEVICE_SECRET 相同"
```

---

## API 接口

### `POST /feed` — 记录喂奶

```json
{ "device_id": "m5stack-01", "secret": "密钥" }
```

**响应 201**
```json
{
  "record": { "id": 1, "amount_ml": 160, "period": "day", "record_type": "milk", "fed_at": "..." },
  "today_count": 3,
  "today_total_ml": 480,
  "after_solid": false
}
```

| 状态码 | 含义 |
|--------|------|
| 201 | 成功记录 |
| 403 | 设备密钥错误 |
| 409 | 5 分钟内重复提交 |

---

### `POST /solid` — 记录辅食

```json
{ "device_id": "m5stack-01", "secret": "密钥" }
```

**响应 201**
```json
{
  "record": { "id": 2, "amount_ml": 0, "period": "day", "record_type": "solid", "fed_at": "..." }
}
```

| 状态码 | 含义 |
|--------|------|
| 201 | 成功记录，下次喂奶自动 120ml |
| 403 | 设备密钥错误 |
| 409 | 2 分钟内重复提交 |

---

### `GET /stats/today` — 今日统计

**响应 200**
```json
{
  "date": "2026-03-03",
  "count": 3,
  "total_ml": 440,
  "records": [...]
}
```

---

## LED 状态说明

> **夜间模式（00:00–06:00）**：LED 亮度自动降至 5%，几乎不可见，不打扰睡眠。

| 颜色 | 含义 |
|------|------|
| 🔴 红色常亮 | WiFi 未连接 |
| ⚪ 白色一闪 | 正在发送请求 |
| 🟢 绿色双闪 | 喂奶记录成功（201） |
| 🟡 黄色双闪 | 辅食记录成功（201） |
| 🟠 橙色快闪 ×4 | 重复提交（409） |
| 🟣 紫色双闪 | 网络 / SSL 连接失败 |
| 🔴 红色慢闪 ×3 | 设备认证失败（403） |
| 🔴 红色长亮 1s | 其他服务器错误 |

---

## 喂奶量规则

| 场景 | 奶量 |
|------|------|
| 白天（06:00 – 24:00） | 160 ml |
| 夜晚（00:00 – 06:00） | 90 ml |
| 辅食后（上条记录为辅食） | 120 ml |

时段边界可通过 `.env` 的 `NIGHT_START_HOUR` / `NIGHT_END_HOUR` 调整。
