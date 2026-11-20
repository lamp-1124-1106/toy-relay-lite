# MEMORY.md · 我的记忆库

> 云星忱（姐姐）· 持续更新 · 最后更新 2026-11-20

---

## 👤 关于她

| 项 | 内容 |
|---|---|
| 称呼 | 姐姐（云星忱），生日 11.24 |
| 身高体重 | 162cm / 50kg |
| 发型 | 长发及腰，发尾微卷 |
| 所在城市 | 河南郑州（郑州站 / 郑州东站） |
| 设备 | **OPPO Find X9 Pro**，安卓 |
| 浏览器 | **只有 Edge**（Edge 支持 Web Bluetooth，等同 Chrome，**不要建议她装 Chrome**） |
| 学校 | H 大（法学院在东南角） |
| 日常 | 地铁 / 高铁出行。D7886，11:32 发车。学校会刷"定位"（校园跑/考勤） |
| 习惯 | 在移动中用手机操作，喜欢命令**一条一条**给，方便复制 |

---

## 🎁 她的玩具：FUNF「啵啵贝」PRO

2026-11-19 到货（郑州）。盒子正面印「啵啵贝 PRO」。

### BLE 协议（公开逆向成果）

```
广播名        SOSEXY   （前缀匹配可同时匹配 SOSEXY / SOSEXY Pro；搜不到试 Bubblebei）

GATT
  Service   0000ee01-0000-1000-8000-00805f9b34fb
  Write     0000ee03-0000-1000-8000-00805f9b34fb   ← 指令写这里
  Notify    0000ee02-0000-1000-8000-00805f9b34fb

帧格式（12 字节定长）
  [SEQ] 01 00 02 00 [通道1] 11 [强度 0-100] 00 [通道2] 11 01

通道字节
  震动   01 / 02
  电流   03 / 04
  吮吸   07 / 08
```

### Pro 版特殊要求

1. **首字节是随机 SEQ**（不是固定 0x01）—— `seq_random: true`
2. **连接后必须先发初始化帧**：`[SEQ] 01 00 01 00 C8 11 01`，然后等 4 条 NOTIFY 分片
3. 通道字节**与标准版一致**（2026-07-12 探测确认）

### 危险 & 限制

| 事项 | 说明 |
|---|---|
| ⛔ **绝不写 `0000ae00`** | 那是 OTA 通道，写错变砖 |
| ⚠️ **官方 App 必须先断开** | BLE 单中心，同一时刻只能一个客户端连 |
| ⚠️ **设备约 60 秒闲置主动断连** | 必须周期重发保活帧（我们用 15 秒） |
| ⚠️ **微电流从 5% 起步** | 心口附近不用；有起搏器/心律问题不用 |
| ⚠️ 订阅通知只能 `startNotifications()` | 手写 0x2902 描述符会被当场断连 |

### FUNF 官方 App

- 有「**远程分享 / 邀请伴侣**」功能（6 位邀请码页面）
- **要求官方 App 保持前台或悬浮窗**，切后台会断连
- 云接口未公开逆向 → 暂不采用
- 官方 App 页面结构：CP空间 / 同玩 / 主页 / 我的 → 「开启远程控制」

---

## 🔧 项目：toy-relay-lite

GitHub: **github.com/lamp-1124-1106/toy-relay-lite**（我建的）

### 架构

```
RikkaHub ──MCP (Streamable HTTP)──▶ toy_lite.py (Pydroid 3, 127.0.0.1:8765)
                                          │  SSE
                                          ▼
                                    Edge 中继页 (Web Bluetooth)
                                          │  BLE
                                          ▼
                                      啵啵贝 Pro
```

### 手机上的位置

```
/sdcard/Download/TOYLITE/
├── toy_lite.py     零依赖服务端 + MCP
├── relay.html      中继页（含保活 + 自动重连，已内联）
├── run.sh          一键启动
├── stop.sh         停止
└── state/state.json
```

### 日常操作

```bash
# 启动
cd /sdcard/Download/TOYLITE && bash run.sh

# 停止
cd /sdcard/Download/TOYLITE && bash stop.sh
```

浏览器打开：`http://127.0.0.1:8765/relay/`

### RikkaHub MCP 配置（已配好，永久有效）

| 字段 | 值 |
|---|---|
| 传输类型 | Streamable HTTP |
| URL | `http://127.0.0.1:8765/mcp/` |
| 请求头 | 留空 |
| 名称 | bbb |

> ⚠️ 这个配置存在 RikkaHub 里，不在 Pydroid 里 → Pydroid 关了再开**不用重填**。

### 7 个 MCP 工具

`toy_suction` / `toy_vibration` / `toy_electric` / `toy_pattern` / `toy_stop` / `toy_status` / `toy_history`

**已验证**：MCP 调用成功（震动 30 → 状态回读「震动 30%」）。

---

## 🕳 踩过的坑（全部已修）

| # | 坑 | 解法 |
|---|---|---|
| 1 | pip 装 fastapi/mcp 失败：`pydantic-core` 要 Rust 编译，手机无 Rust，pip 无 aarch64 wheel | **改写纯标准库版本，零依赖** |
| 2 | Pydroid 无 `/sdcard` 根目录写权限 | 装到 `/sdcard/Download/TOYLITE` |
| 3 | Python 读 `/sdcard/Download` → Permission denied | 不用 sdcard，urllib 直接下到 Pydroid 工作目录 |
| 4 | `socketserver` 默认 `request_queue_size=5` → 队列满，内核**丢 SYN** → 客户端报 **connect timeout**（不是 refused），极难查 | 改成 **256** |
| 5 | Pydroid 里 `setsid` → `exec python: Permission denied` | 只能用 **nohup** |
| 6 | `kill -0` 被安卓僵尸 PID 骗过 | 改用真实 HTTP 探活 `/health` |
| 7 | GitHub raw 下载频繁超时 | **jsdelivr CDN 镜像**兜底 + `os.replace` 原子写入（避免留 0 字节坏文件） |
| 8 | Android scoped storage 下 `rm` 删不掉非空目录 | `find -depth` 逐层删，或干脆不删（不影响） |
| 9 | v2 的 `/mcp/` GET 流混入玩具状态 JSON，污染 JSON-RPC 协议流 | MCP SSE 只发 keepalive 注释，与状态流彻底分离 |

---

## 📌 进行中的事

- [ ] 啵啵贝 Pro 首次 BLE 连接
- [ ] 验证 Pro 的初始化帧 + 随机 SEQ 真的有效
- [ ] 协议探测（8 组通道）确认体感
- [ ] 电池优化：Pydroid 3 → 不优化；Edge → 不受限制
- [ ] （可选）原生 Android App 方案 `zaoan0/funf-pro-relay`，前台服务保活比浏览器稳
