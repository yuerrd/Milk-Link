from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
    )

    # Database
    database_url: str = "mysql+aiomysql://root:password@localhost:3306/milklink"

    # 企业微信
    wechat_webhook_key: str = ""

    # 设备认证
    device_secret: str = "change-me"

    # 时段定义
    night_start_hour: int = 0   # 00:00
    night_end_hour: int = 6     # 06:00  → [00:00, 06:00) 为夜晚

    # 防重复冷却（分钟）
    debounce_minutes: int = 5

    # 时区
    timezone: str = "Asia/Shanghai"

    # 调试模式：True 时跳过所有企业微信推送
    debug_no_push: bool = False

    # MQTT Broker（设备通过 MQTT 上报喂奶事件）
    mqtt_broker_host: str = "localhost"
    mqtt_broker_port: int = 1883
    mqtt_username: str = ""
    mqtt_password: str = ""
    mqtt_topic_prefix: str = "milk-link"

    @property
    def night_amount_ml(self) -> int:
        return 120

    @property
    def day_amount_ml(self) -> int:
        return 160


settings = Settings()
