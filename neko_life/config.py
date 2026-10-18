from maibot_sdk import Field, PluginConfigBase


class PluginSettings(PluginConfigBase):
    enabled: bool = Field(default=False, description="启用生活服务；新安装关闭")
    config_version: str = Field(default="1.0.0")


class ExploreSettings(PluginConfigBase):
    enabled: bool = Field(default=False, description="自主搜索/阅读；需独立授权及Web能力密钥")
    interests: list[str] = Field(
        default_factory=list, description="批准的公开兴趣领域，不填个人身份或私密内容"
    )
    exclusions: list[str] = Field(default_factory=list, description="禁止探索的话题关键词")
    start: str = Field(default="09:00")
    end: str = Field(default="23:00")
    interval_minutes: int = Field(default=120, ge=5, le=10080, description="探索间隔；最少5分钟避免后台空转")


class ModelSettings(PluginConfigBase):
    enabled: bool = Field(default=False, description="允许额外模型调用；仍受统一预算控制")
    task: str = Field(default="utils", description="宿主模型任务名，不是供应商模型名")


class ContextSettings(PluginConfigBase):
    enabled: bool = Field(default=False, description="为指定会话提供相关短背景")
    sessions: list[str] = Field(default_factory=list, description="允许注入的宿主会话ID；空列表不注入")
    drawing_context: bool = Field(
        default=False, description="为明确的角色绘图请求补充当前场景；不授权自主配图"
    )


class BudgetSettings(PluginConfigBase):
    rounds: int = Field(default=3, ge=0, description="每日探索轮数，0不限")
    search: int = Field(default=6, ge=0, description="每日搜索次数，0不限")
    read: int = Field(default=6, ge=0, description="每日正文读取次数，0不限")
    model: int = Field(default=16, ge=0, description="每日额外模型调用次数，0不限")
    input_units: int = Field(default=50000, ge=0, description="输入预留预算，0不限；非精确账单token")
    output_units: int = Field(default=8000, ge=0, description="输出预留预算，0不限；不影响单次响应安全大小")


class SharingSettings(PluginConfigBase):
    enabled: bool = Field(default=False, description="允许主动插件获取公开见闻候选；不是独立调度器")
    sessions: list[str] = Field(
        default_factory=list, description="批准主动分享的宿主会话ID；仍受原主动白名单约束"
    )


class MemorySettings(PluginConfigBase):
    dreams: bool = Field(default=False, description="醒后可选虚构梦境片段；计入统一模型预算")
    diary: bool = Field(default=False, description="晚间角色日程短日记；不读私聊、不写宿主长期记忆")


class Settings(PluginConfigBase):
    plugin: PluginSettings = Field(default_factory=PluginSettings)
    explore: ExploreSettings = Field(default_factory=ExploreSettings)
    models: ModelSettings = Field(default_factory=ModelSettings)
    context: ContextSettings = Field(default_factory=ContextSettings)
    sharing: SharingSettings = Field(default_factory=SharingSettings)
    budget: BudgetSettings = Field(default_factory=BudgetSettings)
    memory: MemorySettings = Field(default_factory=MemorySettings)
    admin_users: list[str] = Field(default_factory=list, description="管理QQ号；空名单拒绝管理命令")
