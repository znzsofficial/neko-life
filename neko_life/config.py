"""Operator-facing labels; stable keys/defaults preserve existing installations."""

from maibot_sdk import Field as sdk_field, PluginConfigBase


def Field(*args, **kwargs):
    """The host shows `hint` inline; SDK descriptions alone are not visible."""
    extra = kwargs.get("json_schema_extra", {})
    if extra.get("label") and kwargs.get("description"):
        kwargs["json_schema_extra"] = {**extra, "hint": kwargs["description"]}
    return sdk_field(*args, **kwargs)


def ui(label, **extra):
    return {"label": label, **extra}


class PluginSettings(PluginConfigBase):
    """先打开需要的功能，最后打开总开关。关掉后停止新的生活后台任务。"""

    __ui_label__ = "总开关"
    __ui_order__ = 0
    enabled: bool = Field(
        default=False,
        description="启用生活日程及下面单独打开的功能；首次安装默认关闭。",
        json_schema_extra=ui("启用Neko Life"),
    )
    config_version: str = Field(default="1.0.0", json_schema_extra=ui("配置版本", hidden=True))


class ExploreSettings(PluginConfigBase):
    """让她自己选题、搜索公开网页并记下见闻；不保证每一轮都有收获。"""

    __ui_label__ = "自己上网找见闻"
    __ui_order__ = 1
    enabled: bool = Field(
        default=False,
        description="允许她自行搜索和阅读公开网页。还需开启后台模型，并配好联网插件。",
        json_schema_extra=ui("允许自主探索"),
    )
    interests: list[str] = Field(
        default_factory=list,
        description="每项填一个想让她关注的领域，如天文、读书、新技术。留空不探索；不要填个人隐私。",
        json_schema_extra=ui("感兴趣的话题"),
    )
    exclusions: list[str] = Field(
        default_factory=list,
        description="每项填一个不要搜索的话题关键词；命中就跳过。",
        json_schema_extra=ui("不要探索的话题"),
    )
    start: str = Field(
        default="09:00",
        description="北京时间，24小时制，如09:00。与结束时间相同则不探索。",
        json_schema_extra=ui("每天几点开始", placeholder="09:00"),
    )
    end: str = Field(
        default="23:00",
        description="北京时间，如23:00；早于开始时间表示跨午夜。",
        json_schema_extra=ui("每天几点结束", placeholder="23:00"),
    )
    interval_minutes: int = Field(
        default=120,
        ge=5,
        le=10080,
        description="隔多久尝试探索一次，单位分钟。默认120分钟；没兴趣时可以跳过。",
        json_schema_extra=ui("探索间隔（分钟）"),
    )


class ModelSettings(PluginConfigBase):
    """用于选题、整理笔记和补充角色场景，会产生额外模型用量。"""

    __ui_label__ = "后台使用的模型"
    __ui_order__ = 5
    enabled: bool = Field(
        default=False,
        description="允许生活后台额外调用模型。关闭后只能使用本地模板日程，不能自主研究。",
        json_schema_extra=ui("允许后台调用模型"),
    )
    task: str = Field(
        default="utils",
        description="填麦麦已有的模型任务名，默认utils。不是具体模型名，一般不用改。",
        json_schema_extra=ui("模型任务名", placeholder="utils"),
    )


class ChatTargets(PluginConfigBase):
    """三种功能各自授权；旧会话 ID 与新号码取并集，不会自动迁移。"""

    group_ids: list[str] = Field(
        default_factory=list,
        max_length=16,
        description="每项填一个QQ群号（纯数字，最多16项）。仅匹配宿主已有群会话；不创建会话。与高级会话ID取并集，撤权须同时移除旧ID。",
        json_schema_extra=ui("允许的QQ群号", placeholder="123456789"),
    )
    user_ids: list[str] = Field(
        default_factory=list,
        max_length=16,
        description="每项填一个私聊QQ号（纯数字，最多16项）。不授权该用户所在的群；群号与QQ号即使相同也不混用。解析失败拒绝授权，见管理状态。",
        json_schema_extra=ui("允许私聊的QQ号", placeholder="123456789"),
    )
    account_id: str = Field(
        default="",
        max_length=20,
        description="高级：多个机器人账号时可限定机器人QQ号，留空不额外限定。旧授权迁移会保留原账号范围；这不是聊天对象QQ号。",
        json_schema_extra=ui("高级：限定机器人QQ账号"),
    )


class ContextSettings(ChatTargets):
    """聊天时让她知道自己在做什么、最近看过什么；不会主动发消息。"""

    __ui_label__ = "聊天里用到生活见闻"
    __ui_order__ = 2
    enabled: bool = Field(
        default=False,
        description="让允许的聊天用到当前角色活动及相关见闻；不修改原人设或聊天历史。",
        json_schema_extra=ui("在聊天中提供生活背景"),
    )
    sessions: list[str] = Field(
        default_factory=list,
        description="高级兼容：仅填宿主会话ID，不是QQ号/群号。与上面的号码取并集；已有授权保留。三项都空才不注入，撤权需移除所有对应项。",
        json_schema_extra=ui("高级：允许的宿主会话ID"),
    )
    drawing_context: bool = Field(
        default=False,
        description="用户明确要求画图时，补充当前角色场景。它不会单独开启自主配图。",
        json_schema_extra=ui("用户要画图时补充场景"),
    )


class BudgetSettings(PluginConfigBase):
    """以下都是每日用量上限，填0表示不限。不影响超时、并发和防刷屏保护。"""

    __ui_label__ = "每日费用与用量控制（0为不限）"
    __ui_order__ = 6
    rounds: int = Field(
        default=3,
        ge=0,
        description="一天最多尝试几轮自主探索；0不限。一次探索可能搜索并阅读多篇网页。",
        json_schema_extra=ui("每天探索几轮"),
    )
    search: int = Field(
        default=6,
        ge=0,
        description="一天最多搜索几次公开网页；0不限。联网插件自己的上限也会生效。",
        json_schema_extra=ui("每天搜索几次"),
    )
    read: int = Field(
        default=6,
        ge=0,
        description="一天最多读取几篇网页正文；0不限。",
        json_schema_extra=ui("每天读取几篇正文"),
    )
    model: int = Field(
        default=16,
        ge=0,
        description="生活后台一天最多调用几次模型；0不限。不限制普通聊天回复。",
        json_schema_extra=ui("每天调用几次后台模型"),
    )
    input_units: int = Field(
        default=50000,
        ge=0,
        description="后台模型每日输入的估算额度；0不限。不是供应商账单Token，不能精确折算金额。",
        json_schema_extra=ui("每日模型输入额度（估算）"),
    )
    output_units: int = Field(
        default=8000,
        ge=0,
        description="后台模型每日输出额度；0不限。隐藏推理和供应商续写可能超出单次请求，不保证金额封顶。",
        json_schema_extra=ui("每日模型输出额度（估算）"),
    )


class SharingSettings(ChatTargets):
    """通过原主动聊天插件择机分享，不另起发言定时器，不改变原概率和冷却。"""

    __ui_label__ = "主动分享见闻"
    __ui_order__ = 3
    enabled: bool = Field(
        default=False,
        description="把公开见闻交给原主动聊天插件选用；还需对方开启Life联动，未必每次都发。",
        json_schema_extra=ui("允许主动分享见闻"),
    )
    daily_max: int = Field(
        default=2,
        ge=1,
        le=8,
        description="每个会话每天最多分享几次；未知投递也占一次，不是每日任务。",
        json_schema_extra=ui("每日分享上限"),
    )
    interval_minutes: int = Field(
        default=180,
        ge=30,
        le=1440,
        description="Life分享之间的最短间隔，不改变主动插件检查频率。",
        json_schema_extra=ui("分享间隔（分钟）"),
    )
    unknown_max: int = Field(
        default=8,
        ge=1,
        le=32,
        description="每个会话最多保留多少条未知占位；达到后暂停新分享，不重发。旧记录也计入。",
        json_schema_extra=ui("未知积压上限"),
    )
    sessions: list[str] = Field(
        default_factory=list,
        description="高级兼容：已有宿主会话ID，与上面的号码取并集。三项都空不分享；还须通过原主动插件目标、时段、概率和冷却检查。",
        json_schema_extra=ui("高级：允许分享的宿主会话ID"),
    )


class DrawingSettings(ChatTargets):
    """允许她择机画当前生活环境，不画人物；不是每轮探索都出图。"""

    __ui_label__ = "自主配生活插画"
    __ui_order__ = 4
    enabled: bool = Field(
        default=False,
        description="无需用户逐次要求，可按需画环境插画。还需生图插件开启Life授权并配对密钥；会消耗生图额度。",
        json_schema_extra=ui("允许自主配图"),
    )
    sessions: list[str] = Field(
        default_factory=list,
        description="高级兼容：已有宿主会话ID，与上面的号码取并集。三项都空不配图；Draw侧life.sessions仍须独立授权同一宿主会话，填Life群号不能绕过。",
        json_schema_extra=ui("高级：允许配图的宿主会话ID"),
    )
    cooldown_seconds: int = Field(
        default=1800,
        ge=300,
        le=86400,
        description="不同场景至少隔多久再画，单位秒。1800秒=30分钟；同一场景不重复，失败未知不自动补画。",
        json_schema_extra=ui("两次配图至少间隔（秒）"),
    )


class MemorySettings(PluginConfigBase):
    """可选的角色虚构素材，不是现实经历，也不读取私聊原文。默认关闭。"""

    __ui_label__ = "可选的角色生活片段"
    __ui_order__ = 7
    dreams: bool = Field(
        default=False,
        description="醒来后偶尔生成一小段虚构梦境，使用后台模型额度；不是现实记忆。",
        json_schema_extra=ui("生成角色梦境"),
    )
    diary: bool = Field(
        default=False,
        description="晚上按角色日程写短日记，使用后台模型额度；不记录用户聊天或写入宿主长期记忆。",
        json_schema_extra=ui("生成角色短日记"),
    )


class Settings(PluginConfigBase):
    plugin: PluginSettings = Field(default_factory=PluginSettings)
    explore: ExploreSettings = Field(default_factory=ExploreSettings)
    models: ModelSettings = Field(default_factory=ModelSettings)
    context: ContextSettings = Field(default_factory=ContextSettings)
    sharing: SharingSettings = Field(default_factory=SharingSettings)
    drawing: DrawingSettings = Field(default_factory=DrawingSettings)
    budget: BudgetSettings = Field(default_factory=BudgetSettings)
    memory: MemorySettings = Field(default_factory=MemorySettings)
    admin_users: list[str] = Field(
        default_factory=list,
        description="允许在私聊中使用/neko-life管理命令的QQ号，每项一个。留空则没人能用管理命令。",
        json_schema_extra=ui("管理命令允许的QQ号"),
    )
