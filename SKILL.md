---
name: workbuddy-account-migrate
description: WorkBuddy 换账号「无感迁移」工具。当用户要切换/更换 WorkBuddy 登录账号、担心对话/记忆/定时任务(自动化)/连接器丢失时触发。非破坏式把旧账号全部数据（sessions、automations.owner_user_id、memory、connectors）整体过户到新账号。触发词：换账号、切换账号、换号、迁移账号、账号合并、无感换号、数据丢失、合并账号、账户迁移。
---

# WorkBuddy 账号无感迁移（非破坏式 / 零丢失红线）

## 何时使用本技能
- 用户想登录另一个 WorkBuddy 账号，又不想丢掉当前账号的：对话历史、长期记忆、定时任务（自动化）、连接器配置。
- 用户问"换号数据会不会丢""怎么无感切换账号""多账号数据怎么合并"。

## 核心结论（先讲给用户）
1. **换账号不会删除任何数据**——所有数据都在本地 `C:\Users\<user>\.workbuddy\`。
2. 但 WorkBuddy 按账号 `user_id` 隔离数据；换到新号后旧号数据"看不见"。
3. 当前版本 `automations`（定时任务）表带 `owner_user_id` 字段，**定时任务绑定账号**（旧版"全局共享"说法已不成立），光换号不会自动带过去，必须过户。
4. 本工具只做「改归属 + 合并」，绝不删除原始文件；旧账号残留的记忆文件/连接器目录一律保留，以"数据零丢失"为第一红线。

## 操作前必做（安全网）
- 迁移前先对 `C:\Users\<user>\.workbuddy\` 做整目录备份（或用脚本自带 `migrate_backups/<时间戳>` 自动快照）。
- 只读核对当前环境：
  ```bash
  python <skill_dir>/migrate_account.py --list      # 列出账号与数据量
  python <skill_dir>/migrate_account.py --dry-run   # 预览将迁移什么，不改任何数据
  ```

## 标准流程（4 步）
1. WorkBuddy 设置里退出旧账号 → 登录新账号。
2. 跑 `--dry-run` 确认目标=新号、源=旧号。
3. 正式迁移（交互选新旧账号，或 `--target <新UID> --source all` 非交互）：
   ```bash
   python <skill_dir>/migrate_account.py
   ```
4. 完全退出并重启 WorkBuddy，缓存刷新后新账号即可见全部旧数据。

## 关键命令
| 命令 | 作用 |
|------|------|
| `--list` | 只读列出所有账号（对话数/定时任务数/记忆大小） |
| `--dry-run` | 预览迁移影响，不写任何数据 |
| `--target <UID> --source all` | 非交互：把全部旧账号过户到新号 |
| `--rollback latest` | 回滚到最近一次备份（回滚前会再快照当前态） |
| `--rollback <时间戳>` | 回滚到指定备份 |

## 设计原则（来自用户要求，不可违背）
- **零丢失红线**：任何操作不删、不覆盖原始数据；只做改归属 + 追加合并 + 复制。
- **幂等**：记忆合并已合并过则跳过；连接器深度合并。
- **原子写入**：记忆/连接器合并用临时文件 + `os.replace`，客户端永不见半写入。
- **可回滚**：迁移前自动备份；`--rollback` 一键还原且回滚前再快照。
- **保留残留文件**：迁移后旧账号 `memory/*.md`、`connectors/<uid>/` 死文件保留不删，可还原。

## 已验证的数据库事实（当前版本）
- `sessions.user_id` 对话归属；`automations.owner_user_id` 定时任务归属；`automation_delivery_outbox.owner_user_id` 待投递消息归属（若存在）。
- `workspaces` / `automation_runs` / `automation_runtime_state` / `buddy_snapshots` / `session_usage` **无账号字段**，靠 `automation_id` 或全局共享关联，无需过户。
- 本机**无 `storage.json`**（社区 `workbuddy-account-migrate` 用 storage.json 识别当前账号的做法不适用）；当前账号改由「DB 中 session 数最多 / 最近活跃」推断。

## GitHub 同类工具借鉴（设计参考）
- `workbuddy-account-migrate`：交互向导、追加去重记忆、JSON 深度合并、自动备份+回滚、WAL checkpoint、迁移后校验。
- `claude-session-migrator`：非破坏性（只拷贝绝不删改）、幂等、多模式 `--list/--old/--new`。
- `claude-account-switch-migration`：`dry-run` 必跑预览 → `-Apply` 才执行；重启交回人类（勿 kill 自身进程）。
- `claude-desktop-session-sync`：原子写入、健康副本优先时间戳。
- `claude-transplant`：undo 反向整个移动。

## 兜底（出问题怎么办）
- 列表找不到旧账号（旧数据消失）：别动，用 `.workbuddy_backup_*` 或 `migrate_backups/` 恢复。
- 想反悔：`--rollback latest`。
- 开过云端同步：换号重登触发同步，本地迁移以本地磁盘为准；若云端覆盖，用 `--rollback` 以本地恢复。

## 注意事项
- 脚本零第三方依赖，仅 Python 3.8+。
- 迁移不需要联网，完全本地运行。
- 项目文件（磁盘目录）、技能、MCP 配置为全局共享，不随账号隔离，换号后照常存在。
