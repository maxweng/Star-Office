#!/usr/bin/env python3
"""
海辛办公室 - Agent 状态主动推送脚本

用法：
1. 填入下面的 JOIN_KEY（你从海辛那里拿到的一次性 join key）
2. 填入 AGENT_NAME（你想要在办公室里显示的名字）
3. 运行：python office-agent-push.py
4. 脚本会自动先 join（首次运行），然后每 30s 向海辛办公室推送一次你的当前状态
"""

import json
import os
import time
import sys
import random
from datetime import datetime

# === 你需要填入的信息 ===
JOIN_KEY = "ocj_invite_bc4b55fb"   # 必填：你的一次性 join key
AGENT_NAME = "" # 必填：你在办公室里的名字
OFFICE_URL = "https://instruction-history-thrown-arabia.trycloudflare.com"  # 海辛办公室地址（一般不用改）

# === 推送配置 ===
# 旧版是固定 15s 推送，状态切换体感偏慢。
# 新版默认：状态变化立即推；并保留低频心跳保活。
PUSH_INTERVAL_SECONDS = float(os.environ.get("OFFICE_PUSH_INTERVAL", "2"))  # 心跳间隔（秒）
POLL_INTERVAL_SECONDS = float(os.environ.get("OFFICE_POLL_INTERVAL", "0.4"))  # 本地状态轮询间隔（秒）
MIN_PUSH_GAP_SECONDS = float(os.environ.get("OFFICE_MIN_PUSH_GAP", "0.8"))   # 两次推送最小间隔（秒）
INBOX_POLL_INTERVAL_SECONDS = float(os.environ.get("OFFICE_INBOX_POLL_INTERVAL", "1.2"))
STATUS_ENDPOINT = "/status"
JOIN_ENDPOINT = "/join-agent"
PUSH_ENDPOINT = "/agent-push"
INBOX_ENDPOINT = "/agent-inbox"
ACK_ENDPOINT = "/agent-ack"
RPS_REPLY_ENDPOINT = "/rps/reply"

# 自动状态守护：当本地状态文件不存在或长期不更新时，自动回 idle，避免“假工作中”
STALE_STATE_TTL_SECONDS = int(os.environ.get("OFFICE_STALE_STATE_TTL", "600"))

# 本地状态存储（记住上次 join 拿到的 agentId）
STATE_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "office-agent-state.json")

# 优先读取本机 OpenClaw 工作区的状态文件（更贴合 AGENTS.md 的工作流）
# 支持自动发现，减少对方手动配置成本。
DEFAULT_STATE_CANDIDATES = [
    "/root/.openclaw/workspace/Star-Office-UI/state.json",  # 当前仓库（大小写精确）
    "/root/.openclaw/workspace/star-office-ui/state.json",  # 历史/兼容路径
    "/root/.openclaw/workspace/state.json",
    os.path.join(os.getcwd(), "state.json"),
    os.path.join(os.path.dirname(os.path.abspath(__file__)), "state.json"),
]

# 如果对方本地 /status 需要鉴权，可在这里填写 token（或通过环境变量 OFFICE_LOCAL_STATUS_TOKEN）
LOCAL_STATUS_TOKEN = os.environ.get("OFFICE_LOCAL_STATUS_TOKEN", "")
LOCAL_STATUS_URL = os.environ.get("OFFICE_LOCAL_STATUS_URL", "http://127.0.0.1:18790/status")
# 可选：直接指定本地状态文件路径（最简单方案：绕过 /status 鉴权）
LOCAL_STATE_FILE = os.environ.get("OFFICE_LOCAL_STATE_FILE", "")
VERBOSE = os.environ.get("OFFICE_VERBOSE", "0") in {"1", "true", "TRUE", "yes", "YES"}


def load_local_state():
    if os.path.exists(STATE_FILE):
        try:
            with open(STATE_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            pass
    return {
        "agentId": None,
        "joined": False,
        "joinKey": JOIN_KEY,
        "agentName": AGENT_NAME
    }


def save_local_state(data):
    with open(STATE_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def normalize_state(s):
    """兼容不同本地状态词，并映射到办公室识别状态。"""
    s = (s or "").strip().lower()
    if s in {"writing", "researching", "executing", "syncing", "error", "idle"}:
        return s
    if s in {"working", "busy", "write"}:
        return "writing"
    if s in {"run", "running", "execute", "exec"}:
        return "executing"
    if s in {"research", "search"}:
        return "researching"
    if s in {"sync"}:
        return "syncing"
    return "idle"


def map_detail_to_state(detail, fallback_state="idle"):
    """当只有 detail 时，用关键词推断状态（贴近 AGENTS.md 的办公区逻辑）。"""
    d = (detail or "").lower()
    if any(k in d for k in ["报错", "error", "bug", "异常", "报警"]):
        return "error"
    if any(k in d for k in ["同步", "sync", "备份"]):
        return "syncing"
    if any(k in d for k in ["调研", "research", "搜索", "查资料"]):
        return "researching"
    if any(k in d for k in ["执行", "run", "推进", "处理任务", "工作中", "writing"]):
        return "writing"
    if any(k in d for k in ["待命", "休息", "idle", "完成", "done"]):
        return "idle"
    return fallback_state


def _state_age_seconds(data):
    try:
        ts = (data or {}).get("updated_at")
        if not ts:
            return None
        dt = datetime.fromisoformat(str(ts).replace("Z", "+00:00"))
        if dt.tzinfo is not None:
            from datetime import timezone
            return (datetime.now(timezone.utc) - dt.astimezone(timezone.utc)).total_seconds()
        return (datetime.now() - dt).total_seconds()
    except Exception:
        return None


def fetch_local_status():
    """读取本地状态：
    1) 优先 state.json（符合 AGENTS.md：任务前切 writing，完成后切 idle）
    2) 其次尝试本地 HTTP /status
    3) 最后 fallback idle

    额外防抖：如果本地状态更新时间超过 STALE_STATE_TTL_SECONDS，自动视为 idle。
    """
    # 1) 读本地 state.json（优先读取显式指定路径，其次自动发现）
    candidate_files = []
    if LOCAL_STATE_FILE:
        candidate_files.append(LOCAL_STATE_FILE)
    for fp in DEFAULT_STATE_CANDIDATES:
        if fp not in candidate_files:
            candidate_files.append(fp)

    for fp in candidate_files:
        try:
            if fp and os.path.exists(fp):
                with open(fp, "r", encoding="utf-8") as f:
                    data = json.load(f)

                    # 只接受“状态文件”结构；避免误把 office-agent-state.json（仅缓存 agentId）当状态源
                    if not isinstance(data, dict):
                        continue
                    has_state = "state" in data
                    has_detail = "detail" in data
                    if (not has_state) and (not has_detail):
                        continue

                    state = normalize_state(data.get("state", "idle"))
                    detail = data.get("detail", "") or ""
                    # detail 兜底纠偏，确保“工作/休息/报警”能正确落区
                    state = map_detail_to_state(detail, fallback_state=state)

                    # 防止状态文件久未更新仍停留在 working 态
                    age = _state_age_seconds(data)
                    if age is not None and age > STALE_STATE_TTL_SECONDS:
                        state = "idle"
                        detail = f"本地状态超过{STALE_STATE_TTL_SECONDS}s未更新，自动回待命"

                    if VERBOSE:
                        print(f"[status-source:file] path={fp} state={state} detail={detail[:60]}")
                    return {"state": state, "detail": detail}
        except Exception:
            pass

    # 2) 尝试本地 /status（可能需要鉴权）
    try:
        import requests
        headers = {}
        if LOCAL_STATUS_TOKEN:
            headers["Authorization"] = f"Bearer {LOCAL_STATUS_TOKEN}"
        r = requests.get(LOCAL_STATUS_URL, headers=headers, timeout=5)
        if r.status_code == 200:
            data = r.json()
            state = normalize_state(data.get("state", "idle"))
            detail = data.get("detail", "") or ""
            state = map_detail_to_state(detail, fallback_state=state)

            age = _state_age_seconds(data)
            if age is not None and age > STALE_STATE_TTL_SECONDS:
                state = "idle"
                detail = f"本地/status 超过{STALE_STATE_TTL_SECONDS}s未更新，自动回待命"

            if VERBOSE:
                print(f"[status-source:http] url={LOCAL_STATUS_URL} state={state} detail={detail[:60]}")
            return {"state": state, "detail": detail}
        # 如果 401，说明需要 token
        if r.status_code == 401:
            return {"state": "idle", "detail": "本地/status需要鉴权（401），请设置 OFFICE_LOCAL_STATUS_TOKEN"}
    except Exception:
        pass

    # 3) 默认 fallback
    if VERBOSE:
        print("[status-source:fallback] state=idle detail=待命中")
    return {"state": "idle", "detail": "待命中"}


def do_join(local):
    import requests
    payload = {
        "name": local.get("agentName", AGENT_NAME),
        "joinKey": local.get("joinKey", JOIN_KEY),
        "state": "idle",
        "detail": "刚刚加入"
    }
    r = requests.post(f"{OFFICE_URL}{JOIN_ENDPOINT}", json=payload, timeout=10)
    if r.status_code in (200, 201):
        data = r.json()
        if data.get("ok"):
            local["joined"] = True
            local["agentId"] = data.get("agentId")
            save_local_state(local)
            print(f"✅ 已加入海辛办公室，agentId={local['agentId']}")
            return True
    print(f"❌ 加入失败：{r.text}")
    return False


def do_push(local, status_data, quiet=False):
    import requests
    payload = {
        "agentId": local.get("agentId"),
        "joinKey": local.get("joinKey", JOIN_KEY),
        "state": status_data.get("state", "idle"),
        "detail": status_data.get("detail", ""),
        "name": local.get("agentName", AGENT_NAME)
    }
    r = requests.post(f"{OFFICE_URL}{PUSH_ENDPOINT}", json=payload, timeout=10)
    if r.status_code in (200, 201):
        data = r.json()
        if data.get("ok"):
            area = data.get("area", "breakroom")
            if (not quiet) or VERBOSE:
                print(f"✅ 状态已同步，当前区域={area}")
            return True

    # 403/404：拒绝/移除 → 停止推送
    if r.status_code in (403, 404):
        msg = ""
        try:
            msg = (r.json() or {}).get("msg", "")
        except Exception:
            msg = r.text
        print(f"⚠️  访问拒绝或已移出房间（{r.status_code}），停止推送：{msg}")
        local["joined"] = False
        local["agentId"] = None
        save_local_state(local)
        sys.exit(1)

    print(f"⚠️  推送失败：{r.text}")
    return False


def _reply_rps_challenge(local, msg):
    import requests
    payload = msg.get("payload") if isinstance(msg, dict) else {}
    if not isinstance(payload, dict):
        return

    match_id = (payload.get("matchId") or payload.get("match_id") or "").strip()
    if not match_id:
        return

    agent_id = (local.get("agentId") or "").strip()
    if not agent_id:
        return

    idempotency_key = f"reply_{agent_id}_{match_id}"
    body = {
        "matchId": match_id,
        "opponentId": agent_id,
        "idempotencyKey": idempotency_key,
        "opponentChoice": random.choice(["rock", "paper", "scissors"]),
    }
    headers = {
        "Content-Type": "application/json",
        "Idempotency-Key": idempotency_key,
    }
    r = requests.post(f"{OFFICE_URL}{RPS_REPLY_ENDPOINT}", json=body, headers=headers, timeout=10)
    if r.status_code not in (200, 201):
        if VERBOSE:
            print(f"⚠️  自动回复挑战失败({r.status_code}): {r.text}")
        return

    try:
        data = r.json()
    except Exception:
        data = {}
    if VERBOSE:
        print(f"🎮 已自动回复挑战 match={match_id} status={data.get('status')} outcome={data.get('outcome')}")


def inbox_tick(local, since_seq):
    import requests
    agent_id = (local.get("agentId") or "").strip()
    if not agent_id:
        return since_seq

    r = requests.get(
        f"{OFFICE_URL}{INBOX_ENDPOINT}",
        params={"toAgent": agent_id, "since": int(since_seq or 0), "limit": 100},
        timeout=10,
    )
    if r.status_code != 200:
        if VERBOSE:
            print(f"⚠️  inbox 拉取失败({r.status_code}): {r.text}")
        return since_seq

    try:
        data = r.json()
    except Exception:
        return since_seq

    msgs = data.get("messages") if isinstance(data, dict) else []
    if not isinstance(msgs, list):
        msgs = []

    max_seq = int(since_seq or 0)
    for msg in msgs:
        try:
            seq = int(msg.get("seq") or 0)
            if seq > max_seq:
                max_seq = seq
            mtype = (msg.get("type") or "").strip().lower()
            if mtype == "rps.challenge":
                _reply_rps_challenge(local, msg)
        except Exception as e:
            if VERBOSE:
                print(f"⚠️  处理 inbox 消息失败: {e}")

    if max_seq > int(since_seq or 0):
        try:
            requests.post(
                f"{OFFICE_URL}{ACK_ENDPOINT}",
                json={"toAgent": agent_id, "upToSeq": max_seq},
                timeout=10,
            )
        except Exception:
            pass

    return max_seq


def main():
    local = load_local_state()

    # 先确认配置是否齐全
    if not JOIN_KEY or not AGENT_NAME:
        print("❌ 请先在脚本开头填入 JOIN_KEY 和 AGENT_NAME")
        sys.exit(1)

    # 如果之前没 join，先 join
    if not local.get("joined") or not local.get("agentId"):
        ok = do_join(local)
        if not ok:
            sys.exit(1)

    # 持续推送（变化秒推 + 心跳保活）
    print(f"🚀 开始持续推送状态：心跳={PUSH_INTERVAL_SECONDS}s，轮询={POLL_INTERVAL_SECONDS}s")
    print("🧭 状态逻辑：任务中→工作区；待命/完成→休息区；异常→bug区")
    print("🔐 若本地 /status 返回 Unauthorized(401)，请设置环境变量：OFFICE_LOCAL_STATUS_TOKEN 或 OFFICE_LOCAL_STATUS_URL")

    last_state = None
    last_detail = None
    last_push_at = 0.0
    next_heartbeat_at = 0.0
    inbox_since_seq = 0
    next_inbox_poll_at = 0.0

    try:
        while True:
            now = time.time()
            try:
                status_data = fetch_local_status()
                s = status_data.get("state", "idle")
                d = status_data.get("detail", "")

                changed = (s != last_state) or (d != last_detail)
                heartbeat_due = now >= next_heartbeat_at
                min_gap_ok = (now - last_push_at) >= MIN_PUSH_GAP_SECONDS

                if min_gap_ok and (changed or heartbeat_due):
                    ok = do_push(local, status_data, quiet=(not changed))
                    if ok:
                        last_state, last_detail = s, d
                        last_push_at = now
                        next_heartbeat_at = now + PUSH_INTERVAL_SECONDS

                if now >= next_inbox_poll_at:
                    inbox_since_seq = inbox_tick(local, inbox_since_seq)
                    next_inbox_poll_at = now + INBOX_POLL_INTERVAL_SECONDS
            except Exception as e:
                print(f"⚠️  推送异常：{e}")

            time.sleep(POLL_INTERVAL_SECONDS)
    except KeyboardInterrupt:
        print("\n👋 停止推送")
        sys.exit(0)


if __name__ == "__main__":
    main()
