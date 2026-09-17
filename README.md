# WorkBuddy 账号无感迁移 / WorkBuddy Account Migrator

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)

一个**非破坏式、零丢失**的 WorkBuddy 换账号迁移工具：把旧账号的
**对话历史、长期记忆、定时任务（自动化）、连接器** 整体"过户"到新账号，实现无感切换。

> 数据不会因换账号而删除——所有数据都在本地 `~/.workbuddy/`。本工具只做
> 「改归属 + 合并」，绝不删除原始文件。旧账号残留的记忆文件 / 连接器目录一律保留。

---

## 为什么需要它

- WorkBuddy 按账号 `user_id` 隔离数据，换到新号后旧号的对话 / 记忆 / 定时任务会"看不见"。
- 当前版本 `automations` 表带 `owner_user_id` 字段，**定时任务绑定账号**（旧版"全局共享"说法已不成立），光换号不会自动带过去。
- 本工具把旧账号数据整体过户到新账号，重启客户端即可"无感"接管。

## 安装 / 使用

无需安装第三方依赖，仅需要 Python 3.8+。

```bash
# 1) 列出本机账号（只读）
python migrate_account.py --list

# 2) 预览将迁移什么（只读，不改任何数据）
python migrate_account.py --dry-run

# 3) 正式迁移（交互选新旧账号）
python migrate_account.py

# 3b) 非交互：全部旧账号 -> 指定新账号
python migrate_account.py --target <新UID> --source all

# 4) 回滚到最近一次备份
python migrate_account.py --rollback latest
```

迁移后**完全退出并重启 WorkBuddy**，缓存刷新即可看到全部旧数据。

## 命令参考

| 命令 | 作用 |
|------|------|
| `--list` | 只读列出所有账号（对话数 / 定时任务数 / 记忆大小） |
| `--dry-run` | 预览迁移影响，不写任何数据 |
| `--target <UID> --source all` | 非交互：把全部旧账号过户到新号 |
| `--rollback latest` | 回滚到最近一次备份（回滚前会再快照当前态） |
| `--rollback <时间戳>` | 回滚到指定备份 |

## 设计原则

- **零丢失红线**：任何操作不删、不覆盖原始数据；只做改归属 + 追加合并 + 复制。
- **幂等**：记忆已合并过则跳过；连接器深度合并。
- **原子写入**：记忆 / 连接器合并用临时文件 + `os.replace`，客户端永不见半写入。
- **可回滚**：迁移前自动备份；`--rollback` 一键还原且回滚前再快照。
- **保留残留文件**：迁移后旧账号 `memory/*.md`、`connectors/<uid>/` 死文件保留不删，可还原。

## 已验证的数据库事实（当前版本）

- 带账号字段：`sessions.user_id`（对话）、`automations.owner_user_id`（定时任务）、`automation_delivery_outbox.owner_user_id`（待投递消息，若存在）。
- 无账号字段（无需过户）：`workspaces` / `automation_runs` / `automation_runtime_state` / `buddy_snapshots` / `session_usage`。
- 本机无 `storage.json`，当前账号由「DB 中 session 数最多 / 最近活跃」推断。

## 文件说明

| 文件 | 说明 |
|------|------|
| `migrate_account.py` | 迁移脚本（V2，非破坏式） |
| `SKILL.md` | WorkBuddy 技能定义（可放入 `~/.workbuddy/skills/`） |
| `操作手册.md` | 中文傻瓜式操作手册（含 dry-run / rollback / 云端同步提示） |
| `LICENSE` | MIT 许可证 |

## 设计借鉴（同类开源工具）

- `workbuddy-account-migrate`：交互向导、追加去重记忆、自动备份 + 回滚。
- `claude-session-migrator`：非破坏性（只拷贝绝不删改）、幂等。
- `claude-account-switch-migration`：`dry-run` 预览 → 执行；重启交回人类。
- `claude-desktop-session-sync`：原子写入、健康副本优先时间戳。
- `claude-transplant`：undo 反向整个移动。

## 安全提示

- 迁移不需要联网，完全本地运行。
- 项目文件（磁盘目录）、技能、MCP 配置为全局共享，不随账号隔离，换号后照常存在。
- 建议在迁移前对 `~/.workbuddy/` 做整目录备份。

## License

[MIT](LICENSE)
