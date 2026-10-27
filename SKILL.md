---
name: wechat-article-extract
description: |
  抓取微信公众号文章（mp.weixin.qq.com）的正文、配图、元信息，输出结构化纯文本或 Markdown。
  零登录零浏览器：不扫码、不需要公众平台后台 session、不需要已登录的 Chrome 调试端口。
  触发场景：
  - 用户消息中出现 mp.weixin.qq.com/s/ 链接（最强信号）
  - "看这个公众号文章"/"抓这篇文章"/"解析这篇微信"/"公众号里说了什么"
  - "帮我看下这个公众号" + 链接或文章名
  - 需要把公众号文章转成 Markdown、存进知识库、或批量归档
  不该触发的相邻请求：
  - 其他域（知乎、B 站、微博、Medium）——走 web_fetch / WebFetch
  - 公众号文章里的视频下载——本 skill 只抓图片
  - 用户只是引用文章做学术参考、未要求抓取
  - 用户想给公众号投稿/运营公众号——本 skill 只读不写
  - 需要按公众号名搜索历史文章列表——本 skill 不做（需微信后台 session）
descriptions:
  zh-Hans: "抓取微信公众号文章（mp.weixin.qq.com）的正文、配图、元信息，输出结构化纯文本或 Markdown。零登录零浏览器，不扫码、不碰账号凭据。"
displayNames:
  zh-Hans: "抓取公众号文章"
---

# 微信公众号文章抓取

`requests` + `BeautifulSoup` + 微信客户端 UA 伪装。本地解析，输出结构化文件。

## 核心特点：零登录、零浏览器

市面上的同类 skill 大多要拉 Playwright/Chromium，要一个已登录微信网页版的调试端口，
或者要扫码拿公众平台后台 session。本 skill **三样都不需要**——运行期依赖只有
`requests` 和 `beautifulsoup4` 两个包。

不接收任何账号凭据、不扫码、不写 cookie 到本地、不做签名逆向、不破验证码。

## 调用方式

脚本路径：`scripts/fetch_wx.py`（skill 自带，自包含）

```bash
# 单个 URL（默认输出到当前目录 wx_<时间戳>_<hash>.txt）
python <skill_dir>/scripts/fetch_wx.py --url "https://mp.weixin.qq.com/s/XXX"

# Markdown 输出（给人看 / 进知识库）
python <skill_dir>/scripts/fetch_wx.py --url "URL" --format md --out article.md

# Markdown + 下载配图（图片引用改写为本地相对路径，产物自包含）
python <skill_dir>/scripts/fetch_wx.py --url "URL" --format md \
    --download-images --images-dir ./imgs --out_dir ./out

# 多个 URL
python <skill_dir>/scripts/fetch_wx.py --url URL1 --url URL2 --out_dir ./out

# 从 stdin
Get-Content urls.txt | python <skill_dir>/scripts/fetch_wx.py --stdin --out_dir ./out

# JSON 输出（管道给其他工具）
python <skill_dir>/scripts/fetch_wx.py --url "URL" --json
```

退出码：`0` 全部成功 / `1` 部分成功 / `2` 全部失败。

## 输出格式

### `txt`（默认，给 Agent 消费）

字段用 `=== XXX ===` 分隔，好切好 grep，不用解析 JSON：

```
=== TITLE ===      文章标题
=== URL ===        最终跳转 URL
=== AUTHOR ===     公众号名
=== PUBLISH_TIME ===
=== DESCRIPTION ===
=== META ===       body_chars / image_count / ok / ua_index / images_dir / error
=== BODY ===       正文纯文本
=== IMAGE_URLS === 逐行图片 URL
```

### `md`（给人看）

YAML frontmatter + 结构化正文。标题层级、加粗、链接、引用、列表、表格都保留，
图片内联。`--download-images` 时图片引用变成本地相对路径。

## 关键参数

| 参数 | 默认 | 说明 |
|---|---|---|
| `--format` | `txt` | `txt` 结构化纯文本 / `md` Markdown |
| `--json` | off | JSON 打到 stdout，不写文件 |
| `--out` | — | 单 URL 输出路径 |
| `--out_dir` | — | 多 URL 输出目录 |
| `--download-images` | off | 下载配图（带 Referer 过防盗链） |
| `--images-dir` | `./wx_images` | 配图根目录，每篇一个 `<hash>/` 子目录 |
| `--keep-promos` | off | Markdown 保留微信推广块（默认剔除） |
| `--timeout` | 15 | HTTP 超时秒数 |
| `--quiet` | off | 不打印进度 |

## 已知限制

写在前面，不藏着：

- **IP 维度风控过不了。** 微信对未登录 IP 有硬墙，换 UA 没用。症状是报
  `all 4 UAs blocked`。解法只有换 IP（热点 / VPN / proxy）。脚本会明确报错退出，
  **不会假装成功**。
- **文章被删和 IP 被墙是两回事，脚本会分开报。** 前者报「文章不可用」，后者报
  `all 4 UAs blocked`——解法完全不同，不要混。
- **图片是 640px 缩略图**，不是原图。`wx_fmt` 参数自带展示尺寸。
- **视频、小程序、付费内容抓不到。** 本工具只处理「正文 + 图片」这个载体。
- **已删除 / 被屏蔽的文章**：HTTP 200 但 `js_content` 为空，会标 `ok: False`。
- **公众号历史文章列表、批量搜索抓不到**——那些要微信公众平台后台 session。
- **`txt` 的 `=== BODY ===` 是纯文本流**，不含图片位置信息。图片位置看
  `=== IMAGE_URLS ===` 的顺序对应；要正文里保留位置，用 `--format md`。

## 故障排查

| 症状 | 原因 | 解法 |
|------|------|------|
| `all 4 UAs blocked` | IP 维度风控 | 换 IP（热点 / VPN / proxy）。UA 换不了这个 |
| `文章不可用：已被发布者删除 / 因违规下架 / 公众号已迁移` | 文章本身没了 | 换源。**不是 IP 问题，别去换 IP** |
| `不是微信公众号文章链接` | URL 不是 mp.weixin.qq.com | 检查 URL |
| `no js_content node` | 抓到了但没有正文节点 | 检查 URL 是否有效 |
| `body too short (N chars)` | 抓到了但内容异常短 | 多半是 fallback 错误页，检查 URL |
| `http 4xx / 5xx` | 需要登录 / 付费 | 这条路走不通 |
| 配图全是 0 字节 | CDN 防盗链 | 已带 Referer；若仍失败多半是 URL 过期，重抓一次 |

## Windows (win32) platform notes

本 skill 在 Windows + PowerShell 5.1 上实测通过。要点：

- 用 `python` 而不是 `python3`（Windows 没有 `python3` 命令）
- `Get-Content urls.txt` 读 URL 列表（不要用 `cat`）
- 中间结果在 stdout 显示会触发 PowerShell 的 RemoteException 误报（stderr 走单独通道），
  **这是 PS 已知问题不是 Python 错误**，看最终输出文件是否生成即可
- 中文路径在 `cd` + `python` 链式调用时可能 GBK 乱码——本 skill 内部强制
  `sys.stdout.reconfigure(encoding="utf-8")` 规避
- 想把脚本输出收到文件，用 `Start-Process -RedirectStandardOutput/-RedirectStandardError`
  （字节原样落盘），**不要用 `1>` / `2>`**（PowerShell 5.1 会写成 UTF-16）

## 配合其他工具

抓完后可以：

- 把 `.md` 产物直接喂给 `zettelkasten` / 知识库类工具
- 用 `citation-bibliography-generator` 把文章作为参考来源
- 批量抓取后用 `mmx` 做摘要

## 注意

- 抓下来的文章正文是**第三方版权内容**。用于个人阅读、研究、引用没问题；
  转载、再发布要自己承担版权责任。
- 批量抓取请控制频率（脚本已内置 1.5s 间隔），别把人家 IP 打了。
