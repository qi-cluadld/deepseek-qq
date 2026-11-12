# deepseek-qq：把 DeepSeek 接进 QQ 的单文件机器人

一个 `deepseek-qq.exe`，双击运行就能把 DeepSeek 挂到 QQ 上聊天。
不需要 Python 环境、不需要服务器、不需要公网 IP。

- **两条都支持，改配置切换**：
  - `onebot` —— 通过 NapCat / Lagrange（普通 QQ 号，功能最全）
  - `qqofficial` —— 通过 QQ 开放平台官方机器人（appid + secret）
- **多轮对话**：每个人/每个群独立上下文，闲置 30 分钟自动清空
- **限流保护**：单会话冷却、全局并发上限，人多也不会把 API 打爆
- **长文自动分条**：超过单条上限自动拆成多条发送
- **异常兜底**：Key 失效、余额不足、被限流、超时，都会回一句人话而不是崩掉

---

## 一、准备两样东西

1. **DeepSeek API Key**：<https://platform.deepseek.com/api_keys>，形如 `sk-xxxxxxxx`
2. **一个用来挂机器人的 QQ 号**：强烈建议用小号（下面两种方式都有风险，见「注意事项」）

---

## 二、快速开始（方式 A：NapCat，推荐）

> 程序有两份，功能完全一样，任选其一：
> - `deepseek-qq.exe` —— 单文件，双击即用（推荐）
> - `deepseek-qq-portable.zip` —— 解压后是一整个文件夹，启动更快、不写临时目录，单文件版万一被拦截就用它

### 1. 装 NapCat 并登录 QQ

到 NapCat 官网/GitHub 下载安装包（`NapCat.Shell` 一键包最省事），按它的引导扫码登录你要挂机器人的那个 QQ 号。

> NapCat 是第三方 QQ 协议端，**用这个号登录后不要在手机上同时挂常用账号**，用小号最稳。

### 2. 在 NapCat 里开一个「反向 WebSocket 服务器」

打开 NapCat 的 WebUI → **网络配置** → 新建 → 选 **WebSocket 服务器**：

| 配置项 | 填什么 |
| --- | --- |
| 名称 | 随便，比如 `deepseek` |
| 主机 | `0.0.0.0`（只本机用就填 `127.0.0.1`） |
| 端口 | `6700`（程序默认监听的端口） |
| 消息格式 | **array**（重要，必须选数组） |
| Token | 自己定个随机串，比如 `my-secret-123`（可留空，但不建议） |
| 上报自身消息 | 关闭 |

### 3. 配置并启动机器人

把 `deepseek-qq.exe` 放到一个**可写的普通文件夹**（不要放 `C:\Program Files`），双击运行。
第一次运行会在旁边生成 `config.yaml` 并提示你去填。用记事本打开它，最少改两处：

```yaml
deepseek:
  api_key: "sk-你的Key"

onebot:
  access_token: "my-secret-123"   # 和 NapCat 里填的保持一致
```

保存后再双击 `deepseek-qq.exe`，看到类似输出就成功了：

```
OneBot 反向 WS 已启动：ws://0.0.0.0:6700/onebot
QQ 端已连接（self_id=123456789 ...）
```

### 4. 测试

- 私聊那个 QQ 号，发「你好」
- 在群里 **@它** 说话，或者发 `#你好`

群里默认必须 @ 才回复；不 @ 用 `#` 开头也能触发（可在配置里改）。

---

## 三、方式 B：QQ 官方机器人

1. 到 <https://q.qq.com> 注册开发者，创建机器人，在「开发设置」拿到 **AppID** 和 **AppSecret**
2. 在后台配置好**事件订阅**（群 @ 消息、私聊消息）和 **IP 白名单**（把运行机器的公网 IP 填上）
3. 改 `config.yaml`：

```yaml
backend: qqofficial

qqofficial:
  app_id: "你的AppID"
  client_secret: "你的AppSecret"
  sandbox: false      # 联调阶段可以先 true
  intents: 1107296256 # 1<<25 群/C2C | 1<<30 频道@
```

4. 运行 exe。群里 @ 机器人，或私聊它（私聊需要在后台单独申请权限）。

---

## 四、配置项说明

| 配置 | 默认值 | 说明 |
| --- | --- | --- |
| `backend` | `onebot` | `onebot` 或 `qqofficial` |
| `deepseek.api_key` | 空 | DeepSeek Key，也可用环境变量 `DEEPSEEK_API_KEY` |
| `deepseek.base_url` | `https://api.deepseek.com` | 换成别的 OpenAI 兼容接口也能用（如中转站） |
| `deepseek.model` | `deepseek-chat` | 也可用 `deepseek-reasoner`（推理模型，较慢） |
| `deepseek.system_prompt` | 简洁口语化 | 决定它的说话风格 |
| `chat.history_turns` | 10 | 记住多少轮对话 |
| `chat.session_ttl_minutes` | 30 | 闲置多久清空上下文 |
| `chat.cooldown_seconds` | 1.5 | 同一个人两次提问的最小间隔 |
| `chat.max_concurrent` | 4 | 同时请求 DeepSeek 的上限，满了回「排队中」 |
| `chat.max_reply_chars` | 1500 | 单条消息字数上限，超出自动分条 |
| `onebot.host` / `port` / `path` | `0.0.0.0` / `6700` / `/onebot` | 反向 WS 监听地址 |
| `onebot.access_token` | 空 | 连接令牌，防别人连你的机器人 |
| `onebot.group_need_at` | `true` | 群里是否必须 @ |
| `onebot.group_prefix` | `#` | 不 @ 时的触发前缀，填空关闭 |
| `onebot.private_enabled` | `true` | 是否响应私聊 |
| `qqofficial.sandbox` | `false` | 沙箱环境 |

改完配置**重启 exe** 生效。

---

## 五、内置命令

| 命令 | 作用 |
| --- | --- |
| `/reset`、`/clear` | 清空当前会话上下文，重新开始 |
| `/help` | 查看帮助 |

---

## 六、常见问题

**双击闪退 / 黑窗口一闪而过**
用 `cmd` 进到 exe 目录运行 `deepseek-qq.exe`，就能看到报错。详细日志在 `logs\bot.log`。

**提示 `端口 6700 监听失败`**
端口被占用（常见于上次没退干净或别的程序占着）。改 `onebot.port`，并同步改 NapCat 里的端口。

**NapCat 显示连不上 / 程序里没有「QQ 端已连接」**
- 确认 NapCat 里是「WebSocket **服务器**」（反向 WS），地址 `ws://127.0.0.1:6700/onebot`
- 消息格式必须是 **array**
- 两边的 Token 必须一致；不一致会返回 401

**群里 @ 了不回复**
- 检查 `onebot.group_need_at` 与 `group_prefix`
- 群里是否有其他机器人抢答
- 看 `logs\bot.log` 里有没有「收到[group]」这行；有收到但没回复就是触发条件没满足

**回复 `API Key 无效` / `账户余额不足`**
去 DeepSeek 后台检查 Key 和余额，`401` 是 Key 错了，`402` 是没钱了。

**回复 `连不上 DeepSeek`**
公司网络/代理问题。给系统设 `HTTP_PROXY`/`HTTPS_PROXY` 环境变量，或把 `base_url` 换成可用的中转地址。

**exe 旁边多出 `_rt` 文件夹**
正常。单文件 exe 运行时要把内置库解压出来，`_rt` 就是解压目录，退出时里面的 `_MEIxxxx` 会自动删掉。之所以不用系统临时目录，是因为部分安全软件/企业策略会拦截向 Temp 写 DLL，放自己目录下更稳。

**装了杀毒软件后打不开**
确认不是把 exe 当病毒隔离了（PyInstaller 打包的程序偶尔会误报），加白名单或换 onedir 版本。

**想让它长期后台运行**
用 `nssm` 之类把它注册成服务，或把 `deepseek-qq.exe` 的快捷方式放进「启动」文件夹。

---

## 七、注意事项（请务必看）

- **封号风险**：NapCat 属于非官方协议端，违反 QQ 用户协议，存在封号可能。**一定用小号**，别用主号。
- **别暴露到公网**：`onebot.host` 保持 `127.0.0.1`（只本机），并设一个够随机的 `access_token`。
- **官方机器人限制**：群聊必须 @，私聊需单独申请权限，主动推送消息有严格配额。
- **费用**：DeepSeek 按 token 计费，人多的时候留意用量；程序里已做冷却和并发限制。
- 机器人只做文本对话，不支持图片、语音、文件。

---

## 八、源码结构与二次开发

```
deepseek-qq/
├─ main.py               入口（参数、启动、优雅退出）
├─ app/
│  ├─ config.py          YAML 配置 + 环境变量覆盖 + 校验
│  ├─ deepseek.py        DeepSeek /chat/completions 客户端（重试、错误翻译）
│  ├─ chat.py            会话上下文、限流、并发、命令、长文分条
│  ├─ onebot.py          OneBot v11 反向 WS（NapCat/Lagrange）
│  ├─ qqofficial.py      QQ 官方机器人（token、网关、心跳、被动回复）
│  └─ log.py             控制台 + 文件日志
├─ tests/
│  ├─ e2e.py             端到端测试（假 DeepSeek + 假 OneBot + 假 QQ 网关）
│  └─ onefile_check.py   单文件 exe 的启动与收发验证
├─ config.example.yaml   带注释的完整配置
├─ build.bat / build.ps1 一键打包
└─ requirements.txt      aiohttp、PyYAML
```

**自己打包**（已装 Python 3.10+ 和依赖）：

```bat
build.bat
```

产物是 `dist\deepseek-qq.exe`。PowerShell 里执行脚本如果被策略拦了，用：

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\build.ps1
```

**跑自测**（不需要真实 QQ、不需要 Key、不需要联网）：

```bat
python tests\e2e.py dist\deepseek-qq.exe
python tests\onefile_check.py
```

`e2e.py` 会拉起假 DeepSeek 接口、假 OneBot 客户端和假 QQ 网关，验证私聊、群 @、多轮上下文、长文分条、错误兜底、官方机器人鉴权与心跳等 23 项。

---

## 九、验证情况说明

- 两条后端的**收发链路**已用本地假服务端到端跑通（23/23 全过），包括消息解析、上下文、分条、异常兜底、官方网关鉴权与心跳。
- 打包出的 `deepseek-qq.exe` 已实际启动并完成一次「收消息 → 调接口 → 回消息」。
- **未验证**：真实 DeepSeek 接口调用与真实 QQ 收发（开发环境无外网、无 QQ 账号）。首次使用请按上面步骤实测；出问题看 `logs\bot.log`，里面记录了每次请求和错误原因。

---

## 十、宣传片

`promo/` 下是 9:16 竖屏宣传片的生成脚本，画面和配乐全部程序化生成，不含任何第三方素材：

```bat
python promo\make_promo.py    :: 1080x1920 / 30fps / 30s 画面 + 封面
python promo\make_music.py    :: 30s 配乐（Am-F-C-G 环境垫）
python promo\make_cover.py    :: 封面图（两个版式）
:: 合成带音轨的成片
ffmpeg -i promo\deepseek-qq-promo-9x16-silent.mp4 -i promo\bgm.wav ^
       -c:v copy -c:a aac -b:a 160k -shortest promo\deepseek-qq-promo-9x16.mp4
```

改文案、换配色直接改 `make_promo.py` 里的常量重跑即可。

---

## 十一、许可证

本项目基于 [MIT License](LICENSE) 开源，© 2026 qi-cluadld。

你可以自由使用、修改、分发，甚至商用，保留版权声明即可。

