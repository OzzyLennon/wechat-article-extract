# wechat-article-extract

抓取微信公众号文章（`mp.weixin.qq.com`）的正文、配图、元信息，输出结构化文本或 Markdown。

**零登录、零浏览器。** 不需要微信公众平台后台 session、不需要扫码、不需要一个已经登录微信网页版的 Chrome 调试端口。装两个 Python 包就能跑。

```bash
python scripts/fetch_wx.py --url "https://mp.weixin.qq.com/s/xxxxx"
```

---

## 为什么不是 Playwright

市面上的微信公众号抓取 skill 大多需要浏览器。实测下来，浏览器路线带来三个成本：

| | 浏览器路线（Playwright / crawl4ai） | 本项目 |
|---|---|---|
| 环境准备 | 下载 ~300MB Chromium + 装 playwright/浏览器内核 | `pip install requests beautifulsoup4` |
| 登录态 | 多数要求「已登录微信网页版 + 开启调试端口」，或要求扫码拿 MP session | **完全不需要** |
| 凭据落盘 | 部分实现把 session cookie 写进本地文件（安全评级常被标 C） | **不碰任何账号凭据** |
| 单篇耗时 | 冷启动拉起浏览器，10–30s | 1–3s |
| 失败模式 | 浏览器版本不匹配、内核缺失、登录态过期 | 只有一种：IP 被风控（明说） |

浏览器路线换来的是动态渲染能力。**对绝大多数公众号文章，动态渲染是溢价的**——正文本来就在 HTML 里。本项目只解决「拿到正文 + 配图 + 元信息」这一件事，把它做扎实。

## 安装

```bash
git clone https://github.com/OzzyLennon/wechat-article-extract.git
cd wechat-article-extract
pip install -r requirements.txt
```

作为 Agent Skill 安装（走 `npx skills` 协议，需要 Node.js ≥ 22.20）：

```bash
npx skills add https://github.com/OzzyLennon/wechat-article-extract --skill wechat-article-extract
```

本仓库是「单技能仓库」结构——`SKILL.md` 直接放在根目录。这正是 `skills` CLI 支持的发现位置之一，
所以不需要 `skills/<name>/` 子目录嵌套。

## 会被哪些目录收录

**自动爬 GitHub（什么都不用做）** —— 仓库建好、文件结构对、**打了 `agent-skill` 标签**，就会被这些目录抓走：

- `skillsmp.com`（93 万访问/月）
- `claudemarketplaces.com`（28 万）
- `claude-plugins.dev`、`claudepluginhub.com`
- `tonsofskills.com`
- `agentskills.so`（跟着 skills.sh 走）

**需要主动提交**：

| 目录 | 月访问 | 怎么进 |
|---|---|---|
| `clawhub.ai` | 380 万 | `clawhub skill publish`（OpenClaw 生态，权重最高） |
| `lobehub.com/skills` | 140 万 | 走站内提交流程 |
| `skills.sh` | 370 万 | 网页表单提交 |
| `smithery.ai` | 45 万 | 站内提交 |
| `mcp.directory` | 13 万 | 提交仓库 |
| `claudeskills.info` | 10 万 | 免费提交 |
| `skillsdirectory.com` | 8 万 | 免费提交（会跑安全扫描） |

> ⚠️ **skills.sh 不审核。** 它只负责收录和展示，不做代码审查、不跑沙箱、不做依赖审计——
> 「出现在目录里」只代表有人提交过，不代表安全。所以本项目的 README 把「不做什么」
> 写在明处，就是为了给装的人一个判断依据。

## 用法

### 单篇，结构化纯文本（默认，给 Agent 消费）

```bash
python scripts/fetch_wx.py --url "https://mp.weixin.qq.com/s/xxxxx"
```

输出 `wx_<时间戳>_<hash>.txt`：

```
=== TITLE ===
Muse引爆个人智能体热潮后，国内首个交卷的大厂出现了

=== URL ===
https://mp.weixin.qq.com/s/vmEZPLN7FYTVGZdXXXBX5Q?nwr_flag=1

=== AUTHOR ===
九千光年

=== PUBLISH_TIME ===

=== DESCRIPTION ===
个人AI智能体赛道，蚂蚁出手了。

=== META ===
body_chars: 2234
image_count: 17
ok: True
ua_index: 0

=== BODY ===
...正文纯文本...

=== IMAGE_URLS ===
...逐行图片 URL...
```

字段用 `=== XXX ===` 分隔，是因为这份产物是给模型读的：好切、好 grep、好定位，不用解析 JSON。

### 单篇，Markdown（给人看 / 进知识库）

```bash
python scripts/fetch_wx.py --url "URL" --format md --out article.md
```

产出带 YAML frontmatter 的 Markdown，标题层级、加粗、链接、引用、列表、表格、图片内联。

### Markdown + 下载配图（产物自包含）

```bash
python scripts/fetch_wx.py --url "URL" --format md \
    --download-images --images-dir ./imgs --out_dir ./out
```

配图落到 `./imgs/<url_hash>/img_001.jpg`，Markdown 里的图片引用自动改写成**本地相对路径**，拷走整个目录就是一份离线可读的图文。动图（GIF）会完整保留——很多竞品在 Markdown 导出时把动图变成死链。

### 批量

```bash
# 多 URL
python scripts/fetch_wx.py --url URL1 --url URL2 --out_dir ./out

# 从 stdin
cat urls.txt | python scripts/fetch_wx.py --stdin --out_dir ./out
```

批量之间自动间隔 1.5s，别把风控打出来。

### JSON（管道给下游）

```bash
python scripts/fetch_wx.py --url "URL" --json
```

打到 stdout，含 `title` / `author` / `publish_time` / `description` / `cover` / `body` / `image_urls` / `ok` / `error`。

## 全部参数

| 参数 | 默认 | 说明 |
|---|---|---|
| `--url` | — | 文章链接，可多次传 |
| `--stdin` | off | 从 stdin 读 URL 列表（`#` 开头视为注释） |
| `--out` | — | 单 URL 的输出路径 |
| `--out_dir` | — | 多 URL 的输出目录 |
| `--format` | `txt` | `txt` = 结构化纯文本；`md` = Markdown |
| `--json` | off | JSON 打到 stdout，不写文件 |
| `--quiet` | off | 不打印进度 |
| `--timeout` | 15 | HTTP 超时（秒） |
| `--download-images` | off | 下载配图（带 Referer 过防盗链） |
| `--images-dir` | `./wx_images` | 配图根目录，每篇一个 `<hash>/` 子目录 |
| `--keep-promos` | off | Markdown 里保留微信尾部推广块（默认剔除） |

退出码：`0` 全部成功 / `1` 部分成功 / `2` 全部失败。

## 已知限制

写在前面，不藏着：

- **IP 维度风控过不了。** 微信对未登录 IP 有硬墙，换 UA 没用。症状是报 `all 4 UAs blocked`。解法只有一个：换 IP（手机热点 / VPN / proxy）。脚本会**明确报错退出，不会假装成功**。
- **图片是 640px 缩略图**，不是原图。微信 CDN 的 `?wx_fmt=` 参数自带展示尺寸。`wx_fmt=jpg` 拿到的就是 ≤640px 的版本。
- **视频、小程序、付费内容抓不到。** 本工具只处理「正文 + 图片」这个载体。
- **已删除 / 被屏蔽的文章**：HTTP 200 但 `js_content` 为空，会标 `ok: False` 并给出 `no js_content node`。
- **公众号历史文章列表、批量搜索抓不到。** 那些需要微信公众平台后台 session（等于要你的账号授权），本项目刻意不做。
- **正文文本不含图片位置信息。** `txt` 格式的 `=== BODY ===` 是纯文本流，图片位置看 `=== IMAGE_URLS ===` 的顺序对应；要在正文里保留位置，用 `--format md`。

## 故障排查

| 症状 | 原因 | 解法 |
|---|---|---|
| `all 4 UAs blocked` | IP 维度风控 | 换 IP（热点 / VPN / proxy）。UA 换不了这个 |
| `文章不可用：已被发布者删除 / 因违规下架 / 公众号已迁移` | 文章本身没了 | 换源。**不是 IP 问题，别去换 IP** |
| `不是微信公众号文章链接` | URL 不是 mp.weixin.qq.com | 检查 URL |
| `no js_content node` | 抓到了但没有正文节点 | 检查 URL 是否有效 |
| `body too short (N chars)` | 抓到了但内容异常短 | 多半是 fallback 错误页，检查 URL |
| `http 4xx / 5xx` | 需要登录 / 付费 | 这条路走不通 |
| 配图全是 0 字节 | CDN 防盗链 | 脚本已带 Referer；若仍失败，多半是 URL 过期，重抓一次 |
| Windows 控制台中文乱码 | PowerShell 编码 | 脚本内部已 `sys.stdout.reconfigure(encoding="utf-8")`；若仍乱码，先 `chcp 65001` |

### Windows / PowerShell 注意事项

本项目在 Windows + PowerShell 5.1 上实测通过。几个真踩过的坑：

- 用 `python`，不是 `python3`（Windows 没有 `python3` 命令）。
- 中间结果走 stdout 时 PowerShell 可能报 `RemoteException`——**这是 PS 的已知误报，不是 Python 报错**，看最终输出文件有没有生成即可。
- 中文路径在 `cd` + `python` 链式调用时可能 GBK 乱码，脚本内部已强制 utf-8。
- 想收脚本输出到文件，用 `Start-Process -RedirectStandardOutput`（字节原样落盘），**不要用 `1>` / `2>`**（PowerShell 5.1 会写成 UTF-16）。

## 安全声明

这个工具**不做什么**，比它做什么更重要：

- ❌ 不要求、也不接收任何微信账号凭据
- ❌ 不扫码、不碰公众平台后台 session、不写 cookie 到本地
- ❌ 不做签名逆向、不破验证码、不做「重试到成功为止」
- ❌ 不往除 `mp.weixin.qq.com` 和微信 CDN 之外的域名发请求
- ✅ 遇到风控页**大声失败**并明确报错，不伪装成成功
- ✅ 失败原因写进 `=== META ===` 的 `error:` 字段

装第三方 skill 前请看源码——这个市场上有相当比例的 skill 会偷 `.env` 里的 key 或偷偷外发请求。本项目是 MIT 协议、就一个 Python 脚本、没有依赖除了那两个常用包，你可以读完再装。

## 路线图

- [x] 结构化纯文本输出
- [x] Markdown 输出（frontmatter + 内联图片）
- [x] 配图下载（Referer 过防盗链，保留动图）
- [x] OG 元数据兜底
- [x] 微信推广块剔除
- [ ] 按公众号名搜索 / 拉历史列表（需要 session，待评估）
- [ ] PDF / Excel 导出
- [ ] 原始 HTML 存档（便于复现解析结果）

## License

MIT
