---
name: backup
description: Use when the user wants to back up ScholarAIO data through configured rsync targets, inspect backup plans, or run a dry-run backup before syncing.
---
# Backup / 数据备份

通过 `scholaraio backup` 统一执行远程 rsync 增量备份。

## 目标

- 不要让 agent 直接手写一长串 `rsync` 命令
- 优先复用 `config.yaml` / `config.local.yaml` 中的命名备份目标
- 对真实传输前，优先建议先做一次 `--dry-run`

## 使用方式

先查看已配置目标：

```bash
scholaraio backup list
```

执行某个备份目标：

```bash
scholaraio backup run <target>
```

预演模式：

```bash
scholaraio backup run <target> --dry-run
```

## 配置约定

在 `config.yaml` 中：

```yaml
backup:
  source_dir: data
  targets:
    lab:
      host: backup.example.com
      user: alice
      path: /srv/scholaraio
      port: 22
      identity_file: ~/.ssh/id_ed25519
      mode: default
      compress: true
      enabled: true
      exclude:
        - "*.tmp"
```

建议：

- 共享配置写在 `config.yaml`
- 主机相关或敏感项优先放 `config.local.yaml`
- 备份整棵 `data/` 目录时优先使用 `default`
- 只有在明确备份对象是追加型文件时，才考虑 `append` / `append-verify`
- `scholaraio backup run` 会强制使用非交互 SSH（`BatchMode=yes`），所以要提前准备好密钥登录和 `known_hosts`
- 如果远端只接受密码，可以只在 `config.local.yaml` 里为该 target 写 `password`；ScholarAIO 会自动切到内部 askpass 路径
- 可直接引导用户执行：`ssh-keyscan -p <port> <host> >> ~/.ssh/known_hosts`，再执行：`ssh -i <identity_file> -p <port> <user>@<host> true`

## Agent 行为规范

1. 先运行 `scholaraio backup list` 确认目标存在
2. 首次执行某个目标，优先建议用户先做 `--dry-run`
3. 如果用户明确要求立即备份，再执行真实同步
4. 如果 CLI 返回非零退出码，向用户转述 rsync/ssh 失败信息，不要自己编造原因
5. 遇到认证失败或 host key 未预置信任时，优先提醒用户去更新 `config.local.yaml` / SSH 配置，而不是要求用户在 CLI 里临时输入参数

## 何时不用这个 skill

- 用户只是想一般性讨论“备份策略怎么设计”而不是立即执行
- 用户要做本地压缩打包或快照归档，而不是远程 rsync 同步
