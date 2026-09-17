#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
WorkBuddy 账号「无感迁移」脚本 V2（非破坏式 / 零丢失红线）
=========================================================
适用：当前 WorkBuddy 版本（automations 表带 owner_user_id 字段，定时任务绑定账号）。

设计原则（用户定）：
  * 任何操作都不删除、不覆盖原始数据；只做「改归属 + 追加合并 + 复制」。
  * 迁移前自动备份；提供 --rollback 一键还原到迁移前状态（回滚前再次快照当前态）。
  * 旧账号残留的记忆文件 / 连接器目录一律保留，可随时手动还原，不主动清理。

场景：你已「退出旧账号 -> 登录新账号」，旧账号的对话 / 记忆 / 定时任务 /
      连接器仍留在本地磁盘，只是归属旧的 user_id，新账号看不到。本脚本
      把它们整体「过户」（改归属）到当前登录的新账号，实现无感接管。

用法：
  1) WorkBuddy 设置里退出旧账号，登录新账号。
  2) 先看预览（只读，不改任何数据）：
       python migrate_account.py --dry-run
  3) 确认无误后正式迁移（交互选新旧账号）：
       python migrate_account.py
     # 或脚本化（非交互）：
       python migrate_account.py --target <新UID> --source all
  4) 完全退出并重启 WorkBuddy 客户端，缓存刷新后新账号即可见全部旧数据。

其他：
  python migrate_account.py --list               # 仅列出账号（只读）
  python migrate_account.py --rollback latest     # 回滚到最近一次备份
  python migrate_account.py --rollback 20260917_153000

零第三方依赖，仅需 Python 3.8+。
"""
import os
import sys
import json
import shutil
import sqlite3
import glob
import datetime
import argparse

WB = os.path.expanduser("~/.workbuddy")
DB = os.path.join(WB, "workbuddy.db")
BACKUP_ROOT = os.path.join(WB, "migrate_backups")


def log(*a):
    print("[migrate]", *a)


def backup(tag=None):
    """迁移前（或回滚前）安全快照：WAL 合并后复制 db + memory + connectors。"""
    ts = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    if tag:
        ts = f"{ts}_{tag}"
    dest = os.path.join(BACKUP_ROOT, ts)
    os.makedirs(dest, exist_ok=True)
    try:
        con = sqlite3.connect(DB)
        con.execute("PRAGMA wal_checkpoint(TRUNCATE)")
        con.close()
    except Exception as e:
        log("checkpoint 跳过:", e)
    for f in ["workbuddy.db", "workbuddy.db-wal", "workbuddy.db-shm"]:
        p = os.path.join(WB, f)
        if os.path.exists(p):
            shutil.copy2(p, os.path.join(dest, f))
    for d in ["memory", "connectors"]:
        s = os.path.join(WB, d)
        if os.path.isdir(s):
            shutil.copytree(s, os.path.join(dest, d), dirs_exist_ok=True)
    log(f"安全快照已生成: {dest}")
    return dest


def get_account_activity():
    """返回 {uid: (会话数, 最近活跃时间)}，用于推断当前账号。"""
    con = sqlite3.connect(f"file:{DB}?mode=ro", uri=True)
    cur = con.cursor()
    cur.execute("PRAGMA table_info(sessions)")
    cols = [r[1] for r in cur.fetchall()]
    time_col = next((c for c in ("updated_at", "created_at", "last_active_at") if c in cols), None)
    if time_col:
        cur.execute(f"SELECT user_id, COUNT(*), MAX({time_col}) FROM sessions GROUP BY user_id")
    else:
        cur.execute("SELECT user_id, COUNT(*), NULL FROM sessions GROUP BY user_id")
    rows = cur.fetchall()
    con.close()
    return {r[0]: (r[1], r[2]) for r in rows}, time_col


def list_accounts():
    act, time_col = get_account_activity()
    con = sqlite3.connect(f"file:{DB}?mode=ro", uri=True)
    cur = con.cursor()
    cur.execute(
        "SELECT owner_user_id, COUNT(*) FROM automations WHERE deleted_at IS NULL GROUP BY owner_user_id"
    )
    auto = dict(cur.fetchall())
    con.close()
    mem = {}
    mdir = os.path.join(WB, "memory")
    if os.path.isdir(mdir):
        for f in os.listdir(mdir):
            if f.endswith("_memory.md"):
                uid = f[: -len("_memory.md")]
                mem[uid] = os.path.getsize(os.path.join(mdir, f))
    accounts = sorted(set(list(act) + list(auto) + list(mem)))
    return accounts, act, auto, mem, time_col


def current_hint_uid():
    """按最近活跃时间（其次会话数）推断最可能的当前账号。"""
    act, _ = get_account_activity()
    if not act:
        return None
    return max(act, key=lambda u: (act[u][1] or "", act[u][0]))


def print_accounts(current_hint=None):
    accounts, act, auto, mem, _ = list_accounts()
    print("\n检测到以下账号：")
    for i, a in enumerate(accounts, 1):
        cnt, last = act.get(a, (0, None))
        mark = "  <-- 可能当前(活跃度最高)" if a == current_hint else ""
        last_s = f"  最近活跃 {last}" if last else ""
        print(
            f"  [{i}] {a}{mark}\n       对话 {cnt}{last_s} | 定时任务 {auto.get(a,0)} | 记忆 {mem.get(a,'无')}"
        )
    return accounts


def deep_merge(base, add):
    for k, v in add.items():
        if k in base and isinstance(base[k], dict) and isinstance(v, dict):
            deep_merge(base[k], v)
        else:
            base[k] = v


def merge_memory(src_uid, dst_uid):
    """把源账号长期记忆以「来源章节」方式原子追加合并进目标（不删源、幂等、去重）。"""
    s = os.path.join(WB, "memory", f"{src_uid}_memory.md")
    d = os.path.join(WB, "memory", f"{dst_uid}_memory.md")
    if not os.path.exists(s):
        return 0
    with open(s, encoding="utf-8") as f:
        src_lines = [l.rstrip("\n") for l in f.read().splitlines()]
    header = f"## 来自旧账号 {src_uid} 的记忆"
    dst_existing = ""
    if os.path.exists(d):
        with open(d, encoding="utf-8") as f:
            dst_existing = f.read()
    if header in dst_existing:
        return 0  # 已合并过，幂等跳过
    dst_lines = dst_existing.rstrip("\n").splitlines() if dst_existing.strip() else []
    existing_set = set(l.strip() for l in dst_lines)
    to_add = [l for l in src_lines if l.strip() not in existing_set]
    block = []
    if dst_lines:
        block.append("")
    block.append(header)
    block.append("")
    block.extend(to_add)
    new_text = "\n".join(dst_lines + block).rstrip("\n") + "\n"
    tmp = d + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        f.write(new_text)
    os.replace(tmp, d)  # 原子写入，客户端永不见半写入
    return len(to_add)


def merge_connectors(src_uid, dst_uid):
    """把源账号连接器配置深度合并进目标（不删源目录）。"""
    s = os.path.join(WB, "connectors", src_uid)
    d = os.path.join(WB, "connectors", dst_uid)
    if not os.path.isdir(s):
        return 0
    os.makedirs(d, exist_ok=True)
    cnt = 0
    for f in os.listdir(s):
        sp = os.path.join(s, f)
        dp = os.path.join(d, f)
        if f.endswith(".json") and os.path.exists(dp):
            try:
                a = json.load(open(sp, encoding="utf-8"))
                b = json.load(open(dp, encoding="utf-8"))
                deep_merge(b, a)
                json.dump(b, open(dp, "w", encoding="utf-8"), ensure_ascii=False, indent=2)
            except Exception:
                shutil.copy2(sp, dp)
        else:
            shutil.copy2(sp, dp)
        cnt += 1
    return cnt


def count_rows(uid):
    con = sqlite3.connect(f"file:{DB}?mode=ro", uri=True)
    cur = con.cursor()
    cur.execute("SELECT COUNT(*) FROM sessions WHERE user_id=?", (uid,))
    s = cur.fetchone()[0]
    cur.execute(
        "SELECT COUNT(*) FROM automations WHERE deleted_at IS NULL AND owner_user_id=?", (uid,)
    )
    a = cur.fetchone()[0]
    n_out = 0
    cur.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name='automation_delivery_outbox'"
    )
    if cur.fetchone():
        cur.execute("PRAGMA table_info(automation_delivery_outbox)")
        if any(r[1] == "owner_user_id" for r in cur.fetchall()):
            cur.execute(
                "SELECT COUNT(*) FROM automation_delivery_outbox WHERE owner_user_id=?", (uid,)
            )
            n_out = cur.fetchone()[0]
    con.close()
    return s, a, n_out


def migrate(src_uid, dst_uid, dry_run=False):
    """执行单个源账号 -> 目标账号过户。dry_run 仅统计不写。返回 (对话, 定时, 待投递, 记忆行, 连接器)。"""
    s_sess, s_auto, s_out = count_rows(src_uid)
    if dry_run:
        log(
            f"[dry-run] {src_uid} -> {dst_uid}: 对话 {s_sess} 条, 定时任务 {s_auto} 条, 待投递 {s_out} 条"
        )
        return s_sess, s_auto, s_out, 0, 0
    con = sqlite3.connect(DB)
    cur = con.cursor()
    cur.execute("UPDATE sessions SET user_id=? WHERE user_id=?", (dst_uid, src_uid))
    cur.execute(
        "UPDATE automations SET owner_user_id=? WHERE owner_user_id=?", (dst_uid, src_uid)
    )
    if s_out:
        cur.execute(
            "UPDATE automation_delivery_outbox SET owner_user_id=? WHERE owner_user_id=?",
            (dst_uid, src_uid),
        )
    con.commit()
    cur.execute("PRAGMA wal_checkpoint(TRUNCATE)")
    con.close()
    nm = merge_memory(src_uid, dst_uid)
    nc = merge_connectors(src_uid, dst_uid)
    return s_sess, s_auto, s_out, nm, nc


def validate(src_uid, dst_uid):
    s_left, a_left, _ = count_rows(src_uid)
    d_sess, d_auto, _ = count_rows(dst_uid)
    ok = s_left == 0 and a_left == 0
    log(
        f"校验 {src_uid}-> {dst_uid}: 源剩余 对话={s_left} 定时={a_left} | 目标当前 对话={d_sess} 定时={d_auto} | {'✅通过' if ok else '⚠️源未完全归零，请检查'}"
    )
    return ok


def rollback(ts):
    if ts in ("latest", "last", "newest"):
        dirs = sorted(glob.glob(os.path.join(BACKUP_ROOT, "*")))
        if not dirs:
            log("无可用备份"); sys.exit(1)
        ts = os.path.basename(dirs[-1])
    src = os.path.join(BACKUP_ROOT, ts)
    if not os.path.isdir(src):
        log("备份不存在:", src); sys.exit(1)
    # 回滚前先对当前态做安全快照（保证可再回滚）
    safe = backup(tag="pre_rollback")
    log(f"已对当前状态做安全快照: {safe}")
    for f in ["workbuddy.db", "workbuddy.db-wal", "workbuddy.db-shm"]:
        sp = os.path.join(src, f)
        if os.path.exists(sp):
            shutil.copy2(sp, os.path.join(WB, f))
    for d in ["memory", "connectors"]:
        sp = os.path.join(src, d)
        dp = os.path.join(WB, d)
        if os.path.isdir(sp):
            if os.path.isdir(dp):
                shutil.rmtree(dp)
            shutil.copytree(sp, dp)
    log(f"回滚完成（已恢复到备份 {ts}）。如需反悔可用刚生成的安全快照 {os.path.basename(safe)}。")


def main():
    ap = argparse.ArgumentParser(description="WorkBuddy 账号无感迁移 V2（非破坏式）")
    ap.add_argument("--list", action="store_true", help="仅列出账号（只读）")
    ap.add_argument("--dry-run", action="store_true", help="预览将迁移什么，不写任何数据")
    ap.add_argument("--rollback", metavar="TIMESTAMP|latest", help="回滚到指定备份或 latest")
    ap.add_argument("--target", help="目标=新账号 UID（非交互模式）")
    ap.add_argument("--source", help="源=旧账号 UID，可逗号分隔或多个，或 all（非交互模式）")
    args = ap.parse_args()

    if not os.path.exists(DB):
        log("未找到 workbuddy.db，请确认路径:", DB)
        sys.exit(1)

    if args.rollback:
        rollback(args.rollback)
        return

    hint = current_hint_uid()
    accounts, act, auto, mem, _ = list_accounts()
    if not accounts:
        log("未发现任何账号数据")
        sys.exit(0)

    if args.list:
        print_accounts(hint)
        return

    # 选择 target / sources
    if args.target and args.source:
        target = args.target
        if args.source.lower() == "all":
            sources = [a for a in accounts if a != target]
        else:
            sources = [x.strip() for x in args.source.split(",") if x.strip() and x.strip() != target]
    else:
        print_accounts(hint)
        try:
            t = int(input("\n请输入【目标=新账号】的序号: ").strip())
            target = accounts[t - 1]
        except Exception:
            log("输入无效"); sys.exit(1)
        sel = input(
            "请输入要合并到新账号的【旧账号序号】(可多个用逗号, 或 all, 或 q 取消): "
        ).strip()
        if sel.lower() == "q":
            sys.exit(0)
        if sel.lower() == "all":
            sources = [a for a in accounts if a != target]
        else:
            idx = [int(x) - 1 for x in sel.split(",")]
            sources = [
                accounts[i]
                for i in idx
                if 0 <= i < len(accounts) and accounts[i] != target
            ]

    if not sources:
        log("未选择任何源账号，退出")
        sys.exit(0)

    if args.dry_run:
        log("=== 预览模式（不会修改任何数据）===")
        for s in sources:
            migrate(s, target, dry_run=True)
        log("以上为预览。去掉 --dry-run 重新运行以正式执行迁移。")
        return

    # 正式迁移
    backup()
    all_ok = True
    for s in sources:
        try:
            ns, na, no, nm, nc = migrate(s, target)
            log(
                f"✓ {s} -> {target}: 对话 {ns} 条, 定时任务 {na} 条, 待投递 {no} 条, 记忆新增 {nm} 行, 连接器 {nc} 个"
            )
            if not validate(s, target):
                all_ok = False
        except Exception as e:
            all_ok = False
            log(f"✗ 迁移 {s} 失败: {e}")
    if all_ok:
        log("全部完成且校验通过！请完全退出并重启 WorkBuddy 客户端，使缓存刷新。")
    else:
        log("部分步骤异常，请查看上方校验/错误信息；可用 --rollback latest 还原。")


if __name__ == "__main__":
    main()
