"""浏览器实例管理表模型。"""

from tortoise import fields, models


class BrowserInstance(models.Model):
    """浏览器实例管理表：记录每个受管浏览器实例的运行信息。"""

    sessionid = fields.CharField(
        max_length=255, primary_key=True, description="浏览器会话 ID（主键）"
    )
    cfg = fields.TextField(description="浏览器配置（base64 编码的长字符串）")
    create_at = fields.DatetimeField(auto_now_add=True, description="创建时间")
    pid = fields.IntField(default=0, description="浏览器进程 ID，默认 0 表示尚未启动")

    class Meta:
        table = "browser_instance"
        ordering = ["-create_at"]
