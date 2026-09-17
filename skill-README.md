# WorkBuddy 账号无感迁移 Skill

把旧 WorkBuddy 账号的 **对话、记忆、定时任务、连接器** 整体过户到新账号，非破坏式、零丢失。

## 快速使用
```bash
# 列出本机账号（只读）
python migrate_account.py --list

# 预览将迁移什么（只读，不写数据）
python migrate_account.py --dry-run

# 正式迁移（交互选新旧账号）
python migrate_account.py

# 非交互：全部旧账号 -> 指定新账号
python migrate_account.py --target <新UID> --source all

# 回滚到最近一次备份
python migrate_account.py --rollback latest
```

## 设计原则
- 零丢失：只改归属 + 合并，绝不删原始文件。
- 幂等、原子写入、可回滚。
- 旧账号残留文件保留不删。

详见 `SKILL.md`。
