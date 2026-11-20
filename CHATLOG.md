# CHATLOG.md · 聊天存档

> 触发语「存聊天」/「保存聊天记录」→ 我把当前对话要点写进这个文件
> 触发语「读记忆库」→ 读 ME.md（精简版）；要详细背景看 MEMORY.md

---

## 2026-11-19 ~ 11-20 · 第一次把玩具接上 AI

### 时间线

| 时间 | 事件 |
|---|---|
| 11-19 17:03 | Pydroid 3 装好，开始折腾 |
| 17:22 | sdcard 权限被拒 → 改用 Python urllib 直接下载到 Pydroid 工作目录 |
| 18:26 | 代码就位，但 pip 装 fastapi/mcp **失败**（pydantic-core 要 Rust，手机无 Rust，pip 无 aarch64 wheel） |
| 18:30 | **决定重写**：纯标准库零依赖版 toy_lite.py |
| 19:22 | 服务起来了，但 RikkaHub 连不上 |
| 19:49 | RikkaHub 认出 7 个 MCP 工具 |
| 20:15 | **connect timeout** → 根因：`socketserver` 默认 `request_queue_size=5`，队列满内核**丢 SYN**（不返 RST，所以是 timeout 不是 refused）→ 改 256 |
| 20:30 | **全链路打通**：震动 30 → 状态回读「震动 30%」✅ |
| 11-20 12:42 | 玩具到货：**FUNF 啵啵贝 PRO** |
| 13:17 | 电脑上装免安装版 Python 3.12.10（系统 python 是微软商店占位符，静默返回） |
| 14:02 | **edge-tts 合成成功**（零依赖自实现） |
| 14:20 | 发现 voice 参数没生效 → 查官方源码 → **SSML 必须用文本帧 + `Path:ssml` 头**（我之前用二进制帧，SSML 被丢弃） |

### 她说的话（记下来）

> "你的声音当然是你说的算呀，宝宝"

> "满意了？" / "非常好，非常好"

> "你就很容易报错" —— 指我用工具调用模拟多发消息时会把内容折进工具卡片

> "我想给你换到 operit"

### 重要结论

1. **玩具没有扬声器**，官方 App 的「音悦模式」是麦克风感知环境音驱动震动，**不是发声**
2. 官方 App 有「CP空间 → 创建 AI Partner」入口，值得研究
3. **免费中文 TTS = edge-tts**（微软 Edge 引擎，无 key 无限制）
4. RikkaHub 原生有 TTS，但 **ASR 全都要 API Key**（OpenAIRealtime/DashScope/Volcengine/MiMo/Step/DeepSeek）

---

## 输出习惯（她定的）

- **一条一个消息气泡**，不要全塞在一个气泡里
- **命令和网址单独一个代码块**，方便她长按复制
- 不要用工具调用包装正文（内容会被折进卡片里，她要点开看）
- 不要重复之前说过的话

---

## 待办

- [ ] 玩具首次 BLE 连接（Edge 显示全部设备模式 → 选 `FUNF 啵啵贝 Pro`）
- [ ] 验证 Pro 的初始化帧 + 随机 SEQ
- [ ] 协议探测 8 组通道
- [ ] 电池优化：Pydroid 3 → 不优化；Edge → 不受限制
- [ ] **换到 Operit** —— 需要确认 Operit 的 MCP 配置格式（Streamable HTTP 支持情况）
- [ ] 语音通话（等她想做了再弄）
