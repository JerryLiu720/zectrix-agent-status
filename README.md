# 个人 AI 助手状态屏 · Zectrix NOTE4

> 把「我的 AI 现在在不在干活、用哪个模型、今天花了多少、余额还剩多少」做成一张抬眼可见的
> 400×300 桌面卡片；墨水屏常驻显示，按键 **↑↓** 翻阅统计、日程与最近对话，**确认键**刷新数据；
> 页面不会自动切换，自动刷新的是屏幕上的数据。

![preview](screenshots/preview.png)

![四页演示](screenshots/demo.gif)

> 截图使用示例数据渲染，页脚会标注「示例数据」，不是真实账户余额。

## 解决什么问题

常用 AI 助手的人反复要确认三件事：它现在在不在干活、今天花了多少钱、余额还够不够。
每次切窗口或开网页去查都不值当。这块屏把这几项放在视线里，不发光、不弹通知、不打断手上的事。

## 和社区现有项目的区别

| 现有项目 | 它们做的 | 这个项目 |
|---|---|---|
| Codex 配额看板 / Claude Code HUD | **编程会话**的额度与上下文 | **通用个人助手**的日常开销与状态 |
| Codex 宠物 | 任务状态 + 像素动画 | 不绑定任何一家 agent，数据源可换 |
| AI 日报 / 天气 / 待办 | 单一内容 | 助手自身的运行画像 |

核心差异：**它不是某个工具的附属屏，而是"我的 AI"的状态屏** —— 换模型、换 agent、换供应商都能用。

## 四页内容

| 页 | 内容 |
|---|---|
| 1 概览 | 运行中/空闲 · 模型 · **今日花费** · **账户余额**（含赠金） |
| 2 统计 | 近 7 日消息柱状图 · 今日条数 · 记忆条数 · 技能个数 |
| 3 日程 | 今天日期 · 所有定时任务的倒计时与 cron 表达式 |
| 4 日志 | 最近 3 条对话摘要（自动去掉 Markdown 符号） |

## 特性

- **真实数据**：读 Hermes 本地状态库（消息量、token 与花费）、cron 配置、记忆库、DeepSeek 余额接口；余额标注缓存时间（如「刚刚」「8 分钟前」）
- **按键翻页（并发读取）**：独立协程持续消费设备事件；连按会等 1.2 秒安静期后合并成一次刷新（设备刷新约 2.5 秒，期间只能缓存约 2 个按键，过早推送会丢键）
- **保持画面**：推完不关闭连接（官方 `show` 示例会 `close()`，设备立刻回主页）
- **自动重连**：设备被占用 / 断线 / 租约未释放时每 2 秒重试
- **单实例保护**：渲染 daemon 带 pid 锁，重复启动会直接退出，避免两个进程抢设备
- **自适应刷新节奏**：单次按键 0.5 秒后刷新（反馈快）；连按则延长到 1.2 秒，等停手再刷，避免刷新期间丢键
- **日志轮转**：每日 04:00 自动把超过 1MB 的日志裁到最近 2000 行（`scripts/rotate_logs.sh`）
- **页数解耦**：页数由 `pages.txt` 传递，改 `PAGES` 不需要改 Rust 代码
- **护屏节流**：翻页立即刷新；数据类变化 5 分钟最多一次；内容不变绝不重绘
- **设备电量**：连接时与每 5 分钟读取一次，顶栏显示 24×11 圆角电池图标（按剩余电量填充）；≤20% 且未充电时图标前出现 `!`
- **版本标记**：页脚显示 `v0.1.0`，方便反馈时对齐版本
- **零配置可试**：读不到本机助手状态时自动进入示例数据模式（页脚标注"示例数据"）
- **十六灰阶**：中文用 Hiragino Sans GB 渲染，400×300 满屏
- **字号规避**：Hiragino 在 12/13px 会把数字 `4` 渲染成斜杠状，项目统一避开这两个字号（仅用 10/11/14px 及以上）

## 架构

```
 agent_status.py  ──渲染──▶  status.png  ──监视变化──▶  watch.rs  ──LAN──▶  NOTE4
   （读本地状态）              （原子替换）        （保持连接 + 按键）      （屏幕）
        ▲                                                                    │
        └──────────────── ui_state.txt（页码，与 PNG 同目录）◀── 按键 ↑/↓ ──┘
```

## 用 AI 安装（推荐）

把仓库地址交给电脑上的 AI（Codex / Claude Code / Cursor / Hermes），它会读 README、装依赖、编译并注册开机自启：

```
帮我在这台 macOS 上安装 GitHub 仓库 JerryLiu720/zectrix-agent-status：
先读 README，缺 cmake 用 pip 装（不要用 brew），缺 Rust 用 rustup；
git clone 后执行 ./install.sh <设备IP>；完成后确认 NOTE4 显示第 1 页。
排错：NoDevice 改用 IP 直连；Busy 等 2 秒自动重试。
```

## 安装耗时（实测）

在干净的 HOME（无 Rust、无 cargo 缓存）下完整跑通安装流程：

| 阶段 | 耗时 |
|---|---|
| 下载 Rust 工具链（rsproxy 镜像，约 470MB） | ~10 秒 |
| 拉取依赖（阿里云镜像，170MB） | ~10 秒 |
| release 编译（含 Opus） | ~12 秒 |
| 自检 + 注册 3 个 LaunchAgent | ~2 秒 |
| **合计** | **约 30–40 秒**（干净 HOME 实测 31.7 秒，取决于网速） |

若镜像不可用会回退官方源，耗时可能变成几分钟到几十分钟 —— 脚本会依次尝试 阿里云 → rsproxy → tuna。

## 安装（手动 3 步）

**1. 拿到设备 IP**：小程序「设备信息」页可看，也可在路由器设备列表里找 `zectrix-` 开头的设备。设备需与电脑同一 Wi-Fi，并开启「待机保持 Wi-Fi」。

**2. 克隆仓库**

```bash
git clone https://github.com/JerryLiu720/zectrix-agent-status
cd zectrix-agent-status
```

**3. 运行安装脚本**（IP 换成你自己的）

```bash
./install.sh 192.168.1.100
```

`install.sh` 会：装 cmake（pip，不走 brew）→ 拉取 Zectrix SDK（codeload 绕过 github.com）→ 编译 `watch` → 安装三个 LaunchAgent（渲染 daemon、设备推送、日志轮转）。

编译 Rust 依赖时，脚本会依次尝试 **阿里云 → rsproxy → tuna** 三个镜像（用 `--config` 临时传入，不改你的全局 cargo 配置）；都不可用时回退官方源。设 `ZECTRIX_NO_MIRROR=1` 可强制走官方源。

## 按键语义（重要）

两个键做的是**两件不同的事**：

| 键 | 作用 | 是否会刷新 |
|---|---|---|
| **↑ / ↓** | 翻页 | **会** —— 翻页本身就会把新页面刷到屏上，不需要额外刷新 |
| **中间确认键** | **强制刷新数据** | **会** —— 清掉余额缓存、重新拉接口、重绘并推送，约 1 秒出图 + 2.5 秒上屏 |

所以：

- **想换页** → 按 ↑/↓，不用再按确认
- **页面没变但想看最新数据**（余额/花费/进度）→ 按**中间键**
- 不需要"为了刷新而翻页"

刷新节奏：对话进行中每 60 秒自动刷一次；空闲每 5 分钟一次（保护墨水屏）；按键时另有自适应节奏（单次 0.5 秒、连按停手后 1.2 秒）。

## 使用

| 操作 | 效果 |
|---|---|
| 短按 ↑ / ↓ | 上一页 / 下一页 |
| 长按 ↑ / ↓ | 无动作（长按会产生 Long 事件，为避免误跳页已禁用） |
| 短按或长按确认 | **强制刷新**：清余额缓存、重新渲染并推送（约 1 秒） |
| 改 `agent_status.py` 的 `PAGES` | 增删页面 |

手动调试：

```bash
python3 agent_status.py --page 1          # 只渲染第 2 页到 status.png
python3 agent_status.py --selftest        # 渲染四页并校验尺寸（安装后自检）
python3 agent_status.py --demo            # 用示例数据渲染
~/zectrix-agent-status/bin/zectrix-watch <IP> status.png gray16
```

## 接入其他助手（配置化，无需改代码）

复制 `config.example.json` 为 `config.json`：

| 字段 | 取值 | 说明 |
|---|---|---|
| `source` | `hermes` / `json` | `hermes`＝读本机 Hermes 数据；`json`＝读任意助手写的统计文件 |
| `assistant_name` | 字符串 | 顶栏显示的名字，默认 `HERMES` |
| `stats_file` | 路径 | `source=json` 时读取的文件（支持 `~`） |

当 `source=json` 时，**任何助手**（Codex、Claude Code、自研 Bot…）只要定期写一个 JSON 即可，格式见 `stats.example.json`：

| 字段 | 含义 |
|---|---|
| `model` | 当前模型名 |
| `balance` / `granted` | 账户余额 / 赠金 |
| `spend_today` | 今日花费 |
| `messages_today` | 今日消息数 |
| `memory_count` / `skill_count` | 记忆条数 / 技能个数 |
| `week` | 近 7 天消息数（7 个整数） |
| `cron` | `[{name, next, schedule}]` 定时任务 |
| `active` / `elapsed` | 是否正在处理 / 本轮已运行秒数 |
| `battery` / `charging` | 设备电量等（可选，通常由 watch 自动填） |
| `last_reply` / `recent` | `{role, content, ts}` 最近回复 / 最近几条 |

文件修改后会自动重新加载（按 mtime 判断），不需要重启进程。

## 停止 / 启动 / 卸载

脚本只负责**进程**和**设备连接**；要不要开机自启，请在 **系统设置 → 通用 → 登录项** 里管理。

| 需求 | 命令 | 结果 |
|---|---|---|
| 断开屏幕（人还在） | `./scripts/zectrix pause` | 断开设备；终端里会问「要同时关进程吗」 |
| 断开并直接关进程（AI 用） | `./scripts/zectrix off` | 断开设备 + 结束进程 |
| 只关进程 | `./scripts/stop.sh` | 结束进程，设备回主页 |
| 重新打开 | `./scripts/start.sh` | 启动并连接设备 |
| 改完代码重启 | `./restart.sh` | 重启渲染 daemon 与推送进程 |
| 看状态 | `./scripts/zectrix status` | 屏幕 / 进程 / 心跳 / 最近日志 |
| 彻底卸载 | `./scripts/uninstall.sh` | 停止并删除 LaunchAgent |

`stop.sh` 不改动登录项设置；下次登录是否自动启动，取决于系统设置里的开关。

## 常见问题

| 现象 | 原因 / 解法 |
|---|---|
| `Error: NoDevice` | SDK 的 mDNS 自动发现不稳；**直接传 IP** |
| `Error: Busy` | 设备被上一个连接占着，等 2 秒（本项目会自动重试） |
| 中文显示成方块 | 本机 Pillow 打不开 `PingFang.ttc`，已改用 `Hiragino Sans GB`；12/13px 数字有字形缺陷，统一用 10/11/14px |
| 按键没反应 | 页码文件必须与 PNG **同目录**；本版已内置 |
| 屏幕回主页 | 推送进程退出后设备会回主页；用 install.sh 装成 LaunchAgent 可常驻 |
| 改了 `agent_status.py` 但屏幕没变 | Python 不热加载，重启 daemon：`./restart.sh` |
| 连按只翻一页 | 自适应安静期：单次 0.5s、连按停手 1.2s 后才推 |

## 已知限制

- 仅同一局域网（LAN v1 协议，端口 32342）
- 同一设备同时只能有一个客户端连接
- 设备刷新一次约 2.5 秒，刷新期间的按键由设备缓存（约 2 个），连按会合并刷新
- **电脑需持续运行**：渲染与推送都在本机，电脑休眠或关机后画面停在最后一帧，不会继续更新
- 仅在 Apple Silicon macOS 实测通过；Windows / Linux 未验证

## License

MIT。SDK 与协议来自 [Zectrix 本地推送 SDK](https://github.com/itopinion/zectrix-local-push-sdk)，遵循其 MIT 许可。

---

- **源码**：https://github.com/JerryLiu720/zectrix-agent-status
- **社区页**：https://zectrix.com/developer/projects/zectrix-agent-status.html
