# Changelog

本项目从 `fetch-wechat-article` 独立而来。改名原因：同名的 `fetch-wechat-article`
已由 `cat-xierluo/legal-skills` 注册并铺到 skills.sh / LobeHub 等多个目录，
撞名会让安装和检索都出问题。

## 1.0.0 — 2026-10-27

首个独立版本。

### 新增

- **`--format md`**：Markdown 输出。YAML frontmatter（title / author / publish_time /
  source_url / description / cover）+ 结构化正文，保留标题层级、加粗、链接、引用、
  列表、表格，图片内联。
- **OG 元数据兜底**：`og:title` / `og:description` / `og:image` / `og:site_name` /
  `article:published_time`，页面结构改版导致 `#activity-name` / `#js_name` 取不到时兜底。
- **发布时间戳兜底**：`<script>var ct = "1758912000";</script>` 解析成人读时间，
  解决「`#publish_time` 节点为空导致发布时间丢失」。
- **Markdown 本地图片引用**：`--download-images` 时把图片引用改写成**相对输出文件的
  相对路径**（正斜杠），整目录拷走即自包含。动图（GIF）完整保留。
- **微信推广块剔除**：Markdown 输出默认去掉视频卡片 / 公众号名片 / 音乐卡片 /
  「点击上方蓝字」类推广，`--keep-promos` 可保留。
- **README / LICENSE / requirements.txt / CHANGELOG / .gitignore**，补齐可发布件。

### 保持

- `txt` 输出格式与旧版**结构一致**（已用同一 URL 逐行对比验证，唯一差异是
  `=== PUBLISH_TIME ===` 从空变成有值——即上面新增的时间戳兜底生效）。
- 4 个 UA 伪装池 + 自动重试逻辑不变。
- 配图下载带 `Referer` 过微信 CDN 防盗链，行为不变。

### 已知未做

- 按公众号名搜索 / 拉历史文章列表（需要微信公众平台后台 session）
- PDF / Excel 导出
- 原始 HTML 存档
