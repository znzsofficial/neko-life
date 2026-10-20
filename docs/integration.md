# 插件协作与能力桥

## 支持组合

| 组件 | 要求 | 是否必需 |
| --- | --- | --- |
| MaiBot / SDK | ≥1.3.9 / ≥2.12，Python≥3.12 | 必需 |
| neko-web | ≥1.6.1，已配置可用搜索来源 | 自主探索需要 |
| neko-proactive-mai | ≥2.1.0，Life联动开关 | 主动分享需要 |
| neko-draw | ≥1.3.0签名配图API，普通生图/外貌记忆仍独立 | 自主环境插画需要 |
| neko-tts / neko-video | 各自正常配置 | 可独立工作，不是Life加载依赖 |

Life不复制搜索/生图供应商密钥，不启动第二个主动聊天调度器，由已有生图引擎执行配图和发送。
不装Web时可使用本地角色日程；不装主动插件时仍可探索和在允许会话中查询见闻。

## 配对密钥

先加载各插件以确认实际`data_dir`。下面是**占位路径**，必须换成你的宿主数据目录，
不是插件源码目录。不要把真实路径内的私密文件提交到仓库。

```bash
# 先预览，不写文件、不调用供应商。
python scripts/configure_bridge.py \
  --web-data-dir /path/to/data/plugins/neko.web \
  --life-data-dir /path/to/data/plugins/neko.life \
  --proactive-data-dir /path/to/data/plugins/neko-proactive-mai

# 检查无误后，用同样参数加 --approve 才生成/配对。
```

只需要自主探索时，省略`--proactive-data-dir`。脚本不会开启插件或修改供应商配置；
已有正确配对保持不变，配对不一致/损坏/符号链接/不安全权限会拒绝，不自动轮换或覆盖。
执行账户应是服务账户；POSIX文件0600，Windows还需要正确的NTFS访问控制。

生成的对应关系：

- Web的`automation-keys.json`与Life的`web-client.json`：`neko.life`客户端能力密钥。
- Life的`sharing-keys.json`与主动插件的`life-client.json`：`neko-proactive-mai`客户端能力密钥。

两组密钥独立；它们不是供应商API Key。脚本只打印文件路径和操作，不打印密钥。
不要手工复用一组密钥，不要在Issue、截图或聊天中粘贴其内容。

自主配图另加`--draw-data-dir /path/to/data/plugins/neko.draw`，先预览、再加`--approve`。
将生成**第三组独立能力密钥**：Draw的`life-keys.json`与Life的`draw-client.json`。
Life配置`drawing.enabled=true`及`drawing.group_ids`/`drawing.user_ids`（或高级`drawing.sessions`）；Draw配置`life.enabled=true`及`life.sessions`，
仅双方会话名单的交集可执行。不更改普通生图工具或供应商配置；空名单默认拒绝。
允许会话同时开启Life背景后，Planner会看到可选配图指引，不强制触发。

## 按顺序启用

1. 先确认现有neko-web交互搜索可用，检查供应商计费；开启其`automation.enabled`。
2. Life配置公开兴趣、禁区及模型任务名，按需开启`models.enabled`、`explore.enabled`，最后开启总开关。
3. 需要聊天背景时开启`context.enabled`，填`context.group_ids`群号/`context.user_ids`私聊QQ号；高级`context.sessions`仅填宿主真实会话ID。三份列表都空不注入。
4. 需要主动分享时，Life开启`sharing.enabled`及允许会话，主动插件开启`life.enabled`；目标仍必须在其原白名单中。
5. 只开探索不会自动授权画图。`context.drawing_context`仅增强明确请求；自主环境插画需要上面的第三组配对/双方独立开关。自画像继续先查外貌记忆。

新安装默认关闭所有新行为；示例、能力配对和Release解压都不等于自动启用。
三种功能各自有`group_ids`、`user_ids`，不能互相授权；与旧`sessions`取并集，撤权需同时移除对应旧ID。
号码只通过`chat.get_stream_by_group_id` / `chat.get_stream_by_user_id`以`platform="qq"`查询已有会话，
不创建会话。每组每类最多16项、总时限2秒，不跨请求缓存；工作区显示最近核验状态。
多路由只匹配宿主lookup返回的已有会话，其他路由用经管理员核验的高级ID。详见[迁移边界](../README.md#群号--qq号与旧配置迁移)。

## 预算与保护

Life的`budget.rounds/search/read/model/input_units/output_units`分别设`0`表示该日成本预算不限。
同时检查Web的`automation.daily_search_max/daily_read_max`，否则第二层仍可能限制请求。
公开版保留保守默认值，不替部署者默认选择无限费用。

`explore.interval_minutes`控制自动探索节奏（默认120，最少5）。管理员工作区可以确认后显式探索一轮，
不强制发消息，仍保留5分钟防连点。并发、单轮请求/正文数、输入/响应大小、超时、故障退避、
去重及主动聊天冷却不会因日预算关闭而失效。用量未知不是0，也无法精确保证供应商金额。

## 主动分享与回执

原主动调度通过时段、概率、静默、冷却和目标检查后，才领取适用的公开候选。
没有候选或Life不可用时仍可走普通主动聊天；Life不决定新收件人、不新建聊天流。

租约、任务提交、平台成功回执是不同状态。只有任务ID与会话精确匹配的成功回执能标`sent`，
普通QQ引用ID、模型沉默、失联或重载后的未完成任务保持`unknown`，不按正文相似度猜测，
不为了补验收自动重发。工作区展示最近回执，过期未确认记录不会继续显示成进行中。

## 回滚与数据

配图只在Planner选择`neko_life_draw_scene`后提交，不另加定时器；同一场景不重复，跨场景仍有
`drawing.cooldown_seconds`防刷屏（默认1800秒、最少300秒），无强制每日生图成本限额。
Life保存尝试后再调用签名桥，Draw将请求ID/会话/提示摘要落盘后才启动原引擎；取消/超时/重载均不重放。
查询原`neko_draw_status`可看当前内存任务进展，任务淘汰或重载后保守未知，不宣称QQ客户端已显示。
配图只画环境/物品，无人物；不绕过自画像记忆流程，不取聊天历史拼成提示词。

先关闭Life总开关及主动插件Life联动，再回滚匹配版本；保留数据库、能力密钥和outbox，
不要让旧版打开未知schema，也不重放结果未知的外部任务。日程/笔记位于宿主分配的私有数据目录，
不是源码文件；使用SQLite一致快照或停写备份，配置、密钥和审计分别保护。原插件仍能独立运行。
回滚配图同时关闭Life的`drawing.enabled`与Draw的`life.enabled`，保留Draw的`life-admission.db`，
不要删幂等记录来重新触发未知生图。Life原数据库仍使用schema1，新增状态仅存在kv，不需破坏性迁移。

完整协议见[protocol.md](protocol.md)，隐私与威胁边界见[SECURITY.md](../SECURITY.md)。
