"""受控压测服务：关掉会花钱/写库的后台派发，再启动 uvicorn。

本文件只用于压测，不修改仓库代码；所有开关都是运行期 monkeypatch。
"""

import uvicorn

from app.services import health_records
from app.services.news import auto as news_auto

# 1) 健康记录后台抽取：会脱离请求事务、可能调用真实付费模型 —— 压测必须关
health_records.EXTRACTION_SCHEDULING_ENABLED = False
# 2) 资讯「每日首次访问自动刷新」：会访问外网 —— 关
news_auto.AUTO_REFRESH_ENABLED = False

from app.core.config import get_settings  # noqa: E402

get_settings().news_portal_enabled = False

from app.main import app  # noqa: E402

if __name__ == "__main__":
    print("压测服务启动：健康抽取已关闭 =", health_records.EXTRACTION_SCHEDULING_ENABLED)
    uvicorn.run(app, host="127.0.0.1", port=8010, log_level="warning", access_log=False)