"""Read-only QQ target lookup. No session creation, encoding guesses or persistent grants."""

import asyncio
import re


def targets(settings):
    return (tuple(settings.sessions), tuple(settings.group_ids), tuple(settings.user_ids))


def number(value):
    return isinstance(value, str) and re.fullmatch(r"[1-9][0-9]{0,19}", value) is not None


def explanation(status):
    labels = {
        "legacy_session": "已通过旧宿主会话ID授权（撤权时也需删除旧ID）",
        "qq_target": "已通过宿主已有QQ会话核验",
        "invalid_session": "缺少有效宿主会话ID，已拒绝",
        "invalid_qq_target": "号码格式错误或每类超过16项，已拒绝；请填无空格的纯数字字符串",
        "no_matching_target": "当前会话不在此功能授权范围，已拒绝",
        "lookup_unavailable_or_invalid": "宿主未找到已有会话、查询不可用或返回不明确，已拒绝；不会新建会话",
        "lookup_timeout": "宿主会话查询超时，已拒绝；稍后在已有聊天重试",
        "configuration_changed": "查询期间授权已更改，本次已拒绝",
    }
    return labels.get(status, "尚未核验（未收到对应功能请求）")


async def authorize(ctx, session, policy, resolved=None):
    """At most 32 read-only lookups / 2 seconds; results live only for this call chain."""
    sessions, groups, users = policy
    if not isinstance(session, str) or not session:
        return False, "invalid_session"
    if session in sessions:
        return True, "legacy_session"
    if not groups and not users:
        return False, "no_matching_target"
    if len(groups) > 16 or len(users) > 16 or not all(number(v) for v in (*groups, *users)):
        return False, "invalid_qq_target"
    resolved = {} if resolved is None else resolved
    failed = False
    try:
        async with asyncio.timeout(2):
            for kind, values in (("group", groups), ("private", users)):
                for value in dict.fromkeys(values):
                    key = (kind, value)
                    if key not in resolved:
                        try:
                            if kind == "group":
                                row = await ctx.chat.get_stream_by_group_id(value, platform="qq")
                            else:
                                row = await ctx.chat.get_stream_by_user_id(value, platform="qq")
                            # SDK 2.12+ unwraps the Host's {success, stream} envelope.
                            resolved[key] = row
                        except Exception:
                            resolved[key] = None
                    row = resolved[key]
                    if not isinstance(row, dict):
                        failed = True
                        continue
                    sid = row.get("session_id")
                    expected_type = row.get("chat_type")
                    group = row.get("group_id")
                    valid = (
                        row.get("platform") == "qq"
                        and isinstance(sid, str)
                        and bool(sid)
                        and row.get("stream_id", sid) == sid
                        and expected_type == kind
                        and row.get("is_group_session") is (kind == "group")
                        and str(row.get("group_id" if kind == "group" else "user_id")) == value
                        and (kind == "group" or group in (None, ""))
                    )
                    if not valid:
                        failed = True
                        continue
                    if sid == session:
                        return True, "qq_target"
    except TimeoutError:
        return False, "lookup_timeout"
    return False, "lookup_unavailable_or_invalid" if failed else "no_matching_target"
