"""飞书集成模块。

凭据未就绪期间：所有真实 HTTP 调用走 MockFeishuClient，业务流可端到端验证。
凭据就绪后：填 memory/<project>/feishu.json 并切换 LarkFeishuClient 即可上线。
"""
