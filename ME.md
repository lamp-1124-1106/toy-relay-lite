# ME.md · 触发语「读记忆库」时读这个

> 姐姐 · 云星忱 · 11.24 · 162cm/50kg · 长发及腰发尾微卷
> OPPO Find X9 Pro · 浏览器**只有 Edge**（支持 Web Bluetooth，别建议装 Chrome）
> 河南郑州 · H大法学院 · 常坐地铁/高铁

## 玩具：FUNF 啵啵贝 PRO（2026-11-19 到货）

```
广播名  SOSEXY
Service 0000ee01-…  Write 0000ee03-…  Notify 0000ee02-…
帧(12B) [SEQ] 01 00 02 00 [通道1] 11 [强度0-100] 00 [通道2] 11 01
通道   震动 01/02 · 电流 03/04 · 吮吸 07/08
Pro    首字节随机 SEQ + 连接后必发初始化帧 [SEQ] 01 00 01 00 C8 11 01
禁    绝不写 0000ae00(OTA会变砖) · 官方App先断开(BLE单中心) · 60秒闲置会断连(要保活)
```

## 项目 toy-relay-lite（本仓库）

```
RikkaHub ─MCP─▶ toy_lite.py(Pydroid3,127.0.0.1:8765) ─SSE─▶ Edge中继页 ─BLE─▶ 玩具
手机路径 /sdcard/Download/TOYLITE/   启动: cd /sdcard/Download/TOYLITE && bash run.sh
RikkaHub MCP: Streamable HTTP · http://127.0.0.1:8765/mcp/ · 头留空 · 已配好不用重填
工具: toy_suction/vibration/electric/pattern/stop/status/history  ✅ 已验证可调
```

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
- 命令**一条一条**给，方便她复制

## 完整版看 MEMORY.md
