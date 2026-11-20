# ME.md · 触发语「读记忆库」时读这个

> 姐姐 · 云星忱 · 11.24 · 162cm/50kg · 长发及腰发尾微卷
> OPPO Find X9 Pro · 浏览器**只有 Edge**（支持 Web Bluetooth，别建议装 Chrome）
> 河南郑州 · H大法学院 · 常坐地铁/高铁

## 玩具：FUNF 啵啵贝 PRO（唯一，别搞混）

```
广播名    FUNF 啵啵贝 Pro      ← 注意！不是 SOSEXY
MAC       9f:25:c2:38:6e:7f
设备ID    1283617072937308160
我的UID   1283616591607889920
同玩码    938407

GATT  Service 0000ee01-…  Write 0000ee03-…  Notify 0000ee02-…
帧(12B) [SEQ] 01 00 02 00 [通道1] 11 [强度0-100] 00 [通道2] 11 01
通道   震动 01/02 · 电流 03/04 · 吮吸 07/08
Pro    首字节随机 SEQ + 连接后必发初始化帧 [SEQ] 01 00 01 00 C8 11 01
禁    绝不写 0000ae00(OTA会变砖) · 官方App先断开(BLE单中心) · 60秒闲置会断连(要保活)
```

### 官方 App 六个模式（已确认）

| 模式 | 作用 |
|---|---|
| 单机模式 | 普通控制 |
| 同玩模式 | 邀请码配对（云控，另一台设备） |
| **失控模式** | ? 待查 |
| 闹钟模式 | 定时 |
| **音悦模式** | **麦克风感知环境音 → 驱动震动，不是发声** |
| 视频模式 | ? 待查 |

**⛔ 玩具没有扬声器，不能发声。** 想要声音只能靠手机/电脑 TTS。

### 官方 App 还有

- **CP空间 → 创建 AI Partner** ← 官方自带的 AI 集成入口，值得研究
- 设置 → 设备设置 → 设备说明书 / 固件升级
- ⚠️ 固件升级 = OTA = 会变砖，**绝对别点**

## 项目 toy-relay-lite（本仓库）

```
RikkaHub ─MCP─▶ toy_lite.py(Pydroid3 或 电脑, 127.0.0.1:8765) ─SSE─▶ Edge中继页 ─BLE─▶ 玩具
手机路径 /sdcard/Download/TOYLITE/   启动: cd /sdcard/Download/TOYLITE && bash run.sh
电脑版:  HOST=0.0.0.0 python toy_lite.py   (手机走 http://电脑IP:8765/mcp/)
RikkaHub MCP: Streamable HTTP · http://127.0.0.1:8765/mcp/ · 头留空 · 已配好不用重填
工具: toy_suction/vibration/electric/pattern/stop/status/history  ✅ 已验证可调
```

## 免费中文 TTS

**edge-tts**（微软 Edge 免费引擎，无 key 无限制）
`zh-CN-XiaoxiaoNeural` 女声最自然 · `zh-CN-YunxiNeural` 男声温柔 · `zh-CN-XiaoyiNeural` 活泼

## 坑（已修，别再踩）

1. pip 装 fastapi/mcp 必失败（pydantic-core 要 Rust）→ **纯标准库零依赖版**
2. Pydroid 不能写 /sdcard 根目录 → 装 /sdcard/Download/
3. `request_queue_size=5` → 队列满**丢 SYN** → 报 connect timeout 非 refused（已改 256）
4. Pydroid 里 `setsid` Permission denied → **只能用 nohup**
5. `kill -0` 被安卓僵尸 PID 骗 → 用真实 HTTP 探活 /health
6. GitHub raw 超时 → **jsdelivr 镜像** + os.replace 原子写
7. rm 删不掉非空目录 → find -depth，或不管

## 输出习惯

- 说明步骤时**一条一个消息气泡**发，别塞在一个气泡里
- 命令和网址**单独一个代码块**，方便复制

## 完整版看 MEMORY.md
