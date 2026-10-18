# 插件协作与能力桥

## 支持组合

| 组件 | 要求 | 是否必需 |
| --- | --- | --- |
| MaiBot / SDK | ≥1.3.9 / ≥2.12，Python≥3.12 | 必需 |
| neko-web | ≥1.6.1，已配置可用搜索来源 | 自主探索需要 |
| attention-seeker-mai | ≥2.1.0，Life联动开关 | 主动分享需要 |
| neko-draw | 现有`neko_draw`工具及外貌记忆提示 | 显式绘图场景增强可选 |
| neko-tts / neko-video | 各自正常配置 | 可独立工作，不是Life加载依赖 |

Life不复制搜索密钥，不启动第二个主动聊天调度器，不直接发QQ、不直接生图。
不装Web时可使用本地角色日程；不装主动插件时仍可探索和在允许会话中查询见闻。

## 配对密钥

先加载各插件以确认实际`data_dir`。下面是**占位路径**，必须换成你的宿主数据目录，
不是插件源码目录。不要把真实路径内的私密文件提交到仓库。

```bash
# 先预览，不写文件、不调用供应商。
python scripts/configure_bridge.py \
  --web-data-dir /path/to/data/plugins/neko.web \
  --life-data-dir /path/to/data/plugins/neko.life \
  --proactive-data-dir /path/to/data/plugins/attention-seeker-mai

# 检查无误后，用同样参数加 --approve 才生成/配对。
```

只需要自主探索时，省略`--proactive-data-dir`。脚本不会开启插件或修改供应商配置；
已有正确配对保持不变，配对不一致/损坏/符号链接/不安全权限会拒绝，不自动轮换或覆盖。
执行账户应是服务账户；POSIX文件0600，Windows还需要正确的NTFS访问控制。

生成的对应关系：

- Web的`automation-keys.json`与Life的`web-client.json`：`neko.life`客户端能力密钥。
- Life的`sharing-keys.json`与主动插件的`life-client.json`：`attention-seeker-mai`客户端能力密钥。

两组密钥独立；它们不是供应商API Key。脚本只打印文件路径和操作，不打印密钥。
不要手工复用一组密钥，不要在Issue、截图或聊天中粘贴其内容。

## 按顺序启用

1. 先确认现有neko-web交互搜索可用，检查供应商计费；开启其`automation.enabled`。
2. Life配置公开兴趣、禁区及模型任务名，按需开启`models.enabled`、`explore.enabled`，最后开启总开关。
3. 需要聊天背景时开启`context.enabled`，填写宿主真实会话ID；空列表不注入。QQ号不是会话ID，不猜测前缀。
4. 需要主动分享时，Life开启`sharing.enabled`及允许会话，主动插件开启`life.enabled`；目标仍必须在其原白名单中。
5. 只开探索不会自动授权画图。`context.drawing_context`仅增强明确的绘图请求，自画像继续先查外貌记忆。

新安装默认关闭所有新行为；示例、能力配对和Release解压都不等于自动启用。

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

先关闭Life总开关及主动插件Life联动，再回滚匹配版本；保留数据库、能力密钥和outbox，
不要让旧版打开未知schema，也不重放结果未知的外部任务。日程/笔记位于宿主分配的私有数据目录，
不是源码文件；使用SQLite一致快照或停写备份，配置、密钥和审计分别保护。原插件仍能独立运行。

完整协议见[protocol.md](protocol.md)，隐私与威胁边界见[SECURITY.md](../SECURITY.md)。
