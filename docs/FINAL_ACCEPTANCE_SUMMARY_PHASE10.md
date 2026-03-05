# Phase 10 收官：最终验收与回滚索引（非破坏改造）

更新时间：2026-03-04

---

## 一、你可直接线上验收的核心点（不看代码也能验）

1) 首页可打开，像素办公室正常加载
2) 主状态切换正常（idle/writing/researching/executing/syncing/error）
3) 多 agent 正常：加入、状态推送、离开
4) 昨日小记正常显示
5) 资产抽屉正常（认证、资产列表、上传、恢复）
6) 生图链路正常（生成、恢复、回退、收藏）

> 若以上都正常，说明本轮优化“功能零丢失”达标。

---

## 二、Phase 1~9 改动与提交索引

- Phase 1 基线冻结：`4cf0240`
- Phase 2 写接口可选鉴权：`7d463ab`
- Phase 3 原子写一致性：`db12219`
- Phase 4 发布前体检脚本：`d5ad92e`
- Phase 5 上传限制 + 写限流：`c3774fc`
- Phase 6 资产读接口可选保护 + 限流桶清理：`409baaf`
- Phase 7 生图并发互斥 + prompt/超时边界：`1367535`
- Phase 8 可选请求日志（脱敏）：`9311ad7`
- Phase 9 生产 strict 模式开关：`2895848`

---

## 三、推荐的生产环境开关（最终态）

建议在确认线上稳定后逐步启用：

```bash
STAR_OFFICE_WRITE_API_BEARER_ENABLED=true
STAR_OFFICE_WRITE_API_TOKENS=<your-long-random-token>
STAR_OFFICE_ASSET_READ_AUTH_ENABLED=true
STAR_OFFICE_MAX_UPLOAD_MB=20
STAR_OFFICE_WRITE_RATE_LIMIT=60,60
STAR_OFFICE_GEMINI_TIMEOUT_SECONDS=240
STAR_OFFICE_GEMINI_PROMPT_MAX_CHARS=1200
STAR_OFFICE_REQUEST_LOG_ENABLED=false
STAR_OFFICE_PROD_STRICT_MODE=true
```

---

## 四、快速回滚索引

### 1) 环境级回滚（最快）
将以下开关恢复为保守值并重启：
- `STAR_OFFICE_PROD_STRICT_MODE=false`
- `STAR_OFFICE_ASSET_READ_AUTH_ENABLED=false`
- `STAR_OFFICE_WRITE_API_BEARER_ENABLED=false`

### 2) 代码级回滚（按 phase 逆序）
```bash
git revert 2895848 9311ad7 1367535 409baaf c3774fc d5ad92e db12219 7d463ab 4cf0240
```

### 3) 快照回滚（运行态文件）
可从：
- `snapshots/baseline-20260304-231354`
恢复关键 json 运行态文件。

---

## 五、附：发布前体检命令

```bash
bash scripts/release_preflight.sh http://127.0.0.1:18790
```

通过后再发版，能显著降低回归风险。
