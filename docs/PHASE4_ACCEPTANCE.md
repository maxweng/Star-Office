# Phase 4 验收单（可维护性整理：发布回归入口）

本阶段目标：
- 不改线上功能
- 提升后续每次发布前/发布后的自检效率

## 已交付
1) 新增 `scripts/release_preflight.sh`
- 一条命令串联：
  - Python 语法检查
  - 安全检查（scripts/security_check.py）
  - 冒烟测试（scripts/smoke_test.py）

## 用法
```bash
cd /root/.openclaw/workspace/Star-Office-UI
bash scripts/release_preflight.sh http://127.0.0.1:18790
```

## 验收标准
- 线上功能无变化（主页、状态、多 agent、资产抽屉）
- 新脚本可执行，输出 PASS

## 回滚
- `git revert <phase4_commit>`
