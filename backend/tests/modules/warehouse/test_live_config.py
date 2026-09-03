"""S0 ticket 01 验收：WAREHOUSE_* 配置键从 .env.development 正确加载（live）。

.env.development 含真实凭证（gitignore），本测试只断言关键非空与前缀，
不把密钥明文写进断言。
"""

from app.core.config import get_settings


def test_warehouse_feishu_app_credentials_loaded() -> None:
    settings = get_settings()
    assert settings.WAREHOUSE_FEISHU_APP_ID == "cli_aaa0eaf293fa5be0"
    assert settings.WAREHOUSE_FEISHU_APP_SECRET  # 非空即可，不断言明文


def test_warehouse_bitable_tokens_loaded() -> None:
    settings = get_settings()
    # 物料系统测试版（计划文档引用版）
    assert settings.WAREHOUSE_FEISHU_BITABLE_MATERIAL_APP_TOKEN.startswith("LmuBb3")
    for token in (
        settings.WAREHOUSE_FEISHU_BITABLE_GMP_APP_TOKEN,
        settings.WAREHOUSE_FEISHU_BITABLE_PROD_APP_TOKEN,
        settings.WAREHOUSE_FEISHU_BITABLE_SALES_APP_TOKEN,
    ):
        assert token  # 非空


def test_warehouse_agent_model_config_loaded() -> None:
    settings = get_settings()
    assert settings.WAREHOUSE_AGENT_BASE_URL == "https://api.deepseek.com"
    assert settings.WAREHOUSE_AGENT_API_KEY  # 非空即可
    assert settings.WAREHOUSE_AGENT_MODEL == "deepseek-v4-flash-vision-exp"
    assert settings.WAREHOUSE_AGENT_TIMEOUT == 120


def test_warehouse_keys_not_required_by_check() -> None:
    """WAREHOUSE_* 为可选键：未配置时 check() 不报缺失（对照现有白名单校验）。"""
    settings = get_settings()
    # check() 只校验白名单必填键，WAREHOUSE_* 不在其中——直接调用不应抛错
    settings.check()
