# HERMES 状态屏 · Zectrix NOTE4 Agent 副屏

> 把 AI Agent 的真实工作状态放到桌边一块 4.2" 墨水屏上：模型、余额、记忆条数、定时任务倒计时、最近对话。
> 按键翻页，局域网点对点推送，**不经过云端**。

![preview](screenshots/preview.png)

## 为什么做这个

官方示例里已经有宠物、天气、待办 —— 但没有一个展示「**AI Agent 正在做什么**」。
这个项目把 Agent 的运行数据（Hermes 的本地状态库）变成一张随时可瞄一眼的副屏，
零配置即可跑（读不到 Hermes 时自动降级为示例数据）。

## 四页内容

| 页 | 内容 |
|---|---|
| 1 概览 | 运行状态（进行中/空闲）、今日消息数、最近活动、下一个定时任务 |
| 2 日程 | 今天日期 + 所有 cron 任务的倒计时与表达式 |
| 3 余额 | DeepSeek 余额 / 赠金 / 当前模型 / 记忆与技能数量 |
| 4 日志 | 最近 3 条对话摘要（自动跳过工具原始输出） |

## 特性

- **真实数据**：直接读 `~/.hermes/state.db`、`cron/jobs.json`、`memory_store.db`、DeepSeek 余额接口
- **按键翻页**：短按 ↑/↓ 切页；页码写在 `ui_state.txt`，渲染器与设备端解耦
- **保持画面**：推完不关闭连接（官方 `show` 示例会 `close()`，设备立刻回主页）
- **自动重连**：设备被占用/断线/租约未释放时每 2 秒重试
- **内容去重**：渲染结果没变化就不写文件 → 墨水屏不会每几秒闪一次
- **十六灰阶**：中文用 Hiragino Sans GB 渲染，400×300 满屏

## 架构

```
 agent_status.py  ──渲染──▶  status.png  ──监视变化──▶  watch.rs  ──LAN──▶  NOTE4
   （读本地状态）              （原子替换）        （保持连接 + 按键）      （屏幕）
        ▲                                                                    │
        └──────────────── ui_state.txt（页码） ◀──────────── 按键 ↑/↓ ──────┘
```

## 安装（3 步）

> 需要：macOS（Apple Silicon 已验证）、Python 3、Rust（脚本会自动装）。

```bash
# 1. 放入设备 IP（设备需与电脑同一 Wi-Fi，并开启「设置 → 网络同步 → 待机保持 Wi-Fi」）
./install.sh 192.168.1.100

# 2. 授权开机自启（脚本会引导）
# 3. 完成：屏幕应显示第 1 页
```

`install.sh` 会做：装 cmake（若缺）→ 拉取 Zectrix SDK → 编译 `watch` → 安装两个 LaunchAgent（渲染 daemon + 设备推送）。

## 使用

| 操作 | 效果 |
|---|---|
| 短按 ↑ / ↓ | 上一页 / 下一页 |
| 短按确认 | 无（渲染器每 3 秒自动刷新数据） |
| 修改 `agent_status.py` 的 `PAGES` | 增删页面 |

手动调试：

```bash
python3 agent_status.py --page 2          # 只渲染第 3 页到 status.png
cargo run --example watch -- <IP> status.png gray16
```

## 常见问题

| 现象 | 原因 / 解法 |
|---|---|
| `Error: NoDevice` | SDK 的 mDNS 自动发现不稳；**直接传 IP** 即可 |
| `Error: Busy` | 设备被上一个连接占着，等 2 秒（本项目的 watch 会自动重试） |
| 中文显示成方块 | 本机 Pillow 打不开 `PingFang.ttc`，已改用 `Hiragino Sans GB` |
| 屏幕回主页 | 说明推送进程退了：画面只在连接保持期间有效 |
| 设备离线 | 关掉「待机保持 Wi-Fi」或不在同一局域网时扫不到 |

## 已知限制

- 仅同一局域网（LAN v1 协议，端口 32342）
- 同一设备同时只能有一个客户端连接
- 余额查询每 10 分钟缓存一次，避免频繁调用 API

## License

MIT。SDK 与协议来自 [Zectrix 本地推送 SDK](https://github.com/itopinion/zectrix-local-push-sdk)，遵循其 MIT 许可。
