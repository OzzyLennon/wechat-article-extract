#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
fetch_wx.py — 微信公众号文章本地抓取工具（wechat-article-extract）

策略：requests + BeautifulSoup + 微信客户端 UA 伪装
绕过点：mp.weixin.qq.com 对未登录 IP 的 verify 墙主要是 User-Agent 维度，
      IP 风控维度的硬墙这套方案绕不过。

零登录、零浏览器：不需要微信公众平台后台 session、不需要扫码、不需要已登录的
Chrome 调试端口。运行期依赖只有 requests + beautifulsoup4。

Usage:
  # 单个 URL（默认输出到当前目录 wx_<时间戳>_<hash>.txt）
  python fetch_wx.py --url "https://mp.weixin.qq.com/s/xxx"

  # 自定义输出
  python fetch_wx.py --url "https://mp.weixin.qq.com/s/xxx" --out article.txt

  # Markdown 输出（内联图片）
  python fetch_wx.py --url "URL" --format md --out article.md

  # Markdown + 下载配图（图片引用改写为本地相对路径，产物自包含）
  python fetch_wx.py --url "URL" --format md --download-images \
      --images-dir ./imgs --out_dir ./out

  # 批量：从 stdin
  echo "https://mp.weixin.qq.com/s/xxx1" | python fetch_wx.py --stdin --out_dir ./out

  # 批量：多 --url
  python fetch_wx.py --url URL1 --url URL2 --out_dir ./out

  # JSON 输出（到 stdout，不写文件）
  python fetch_wx.py --url "URL" --json

  # 顺带下载图片（带 Referer 过防盗链，下到 <images_dir>/<url_hash>/）
  python fetch_wx.py --url "URL" --download-images --images-dir ./imgs

退出码：
  0 = 全部成功
  1 = 部分成功
  2 = 全部失败

依赖：
  pip install -r requirements.txt
"""
import argparse
import hashlib
import json
import os
import re
import sys
import time
from datetime import datetime
from pathlib import Path

try:
    import requests
    from bs4 import BeautifulSoup, NavigableString
except ImportError:
    print("[err] 缺少依赖: pip install -r requirements.txt", file=sys.stderr)
    sys.exit(2)


# 多个备选 UA 提高过墙率（按推荐度排序：Android 微信 → iOS 微信 → Windows 微信 → Safari 兜底）
USER_AGENTS = [
    "Mozilla/5.0 (Linux; Android 11; M2012K11AC Build/RKQ1.200826.002; wv) AppleWebKit/537.36 (KHTML, like Gecko) Version/4.0 Chrome/86.0.4240.99 XWEB/3164 MMWEBSDK/20211001 Mobile Safari/537.36 MMWEBID/4357 MicroMessenger/8.0.15.2020(0x28000F3D) Process/toolsmp WeChat/arm64 Weixin NetType/WIFI Language/zh_CN ABI/arm64",
    "Mozilla/5.0 (iPhone; CPU iPhone OS 14_0 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Mobile/15E148 MicroMessenger/8.0.16(0x28001030) NetType/WIFI Language/zh_CN",
    "Mozilla/5.0 (Windows NT 10.0; WOW64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/53.0.2785.116 Safari/537.36 QBCore/4.0.1301.400 QQBrowser/9.0.2524.400 Mozilla/5.0 (Windows; U; Windows NT 6.1; en-us) AppleWebKit/534.50 (KHTML, like Gecko) Version/5.1 Safari/534.50 MicroMessenger/7.0.5.1401(0x27000539) NetType/WIFI WindowsWechat",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/14.0.3 Safari/605.1.15",
]

# 验证码墙特征
VERIFY_MARKERS = [
    "环境异常",
    "js_verify",
    "完成验证后即可继续访问",
    "secitptpage/verify",
    "weui-msg__title",  # 验证页的 class
]

# 「文章本身没了」的特征。微信的报错页同样带 js_verify，
# 所以必须和 IP 风控区分开，否则会把用户引向「换 IP」的错误方向。
CONTENT_UNAVAILABLE_MARKERS = [
    "该内容已被发布者删除",
    "此内容因违规无法查看",
    "该公众号已迁移",
    "该内容已被删除",
    "内容已被删除",
    "链接已过期",
    "参数错误",
]

# 微信正文里常见的非内容节点（Markdown 输出时剔除）
JUNK_TAGS = {
    "script",
    "style",
    "noscript",
    "mp-common-videosnap",  # 视频卡片
    "mpprofile",  # 公众号名片
    "mp-common-profile",
    "qqmusic",  # 音乐卡片
    "mp-like",  # 点赞/赞赏条
    "mp-common-like",
}

# 微信正文尾部的推广话术（Markdown 输出时剔除，可用 --keep-promos 保留）
PROMO_PATTERNS = [
    r"点击上方蓝字",
    r"预览时标签不可点",
    r"长按识别二维码",
    r"识别图中二维码",
]

# 行内元素（不进块级结构）
INLINE_TAGS = {"strong", "b", "em", "i", "a", "code", "tt", "span", "label", "u", "sup", "sub", "font"}


# --------------------------------------------------------------------------
# 基础抓取
# --------------------------------------------------------------------------

def is_blocked(html: str) -> bool:
    return any(m in html for m in VERIFY_MARKERS)


def is_content_unavailable(html: str) -> bool:
    """文章本身不存在（被删 / 违规 / 迁移 / 链接过期），不是 IP 风控。"""
    return any(m in html for m in CONTENT_UNAVAILABLE_MARKERS)


def _meta(soup, *keys) -> str:
    """按 property/name 两种写法取 meta content。"""
    for k in keys:
        node = soup.find("meta", attrs={"property": k}) or soup.find("meta", attrs={"name": k})
        if node and node.get("content"):
            return node["content"].strip()
    return ""


def extract_article(html: str) -> dict:
    soup = BeautifulSoup(html, "html.parser")

    # 标题
    title_node = soup.find(id="activity-name") or soup.find("title")
    title = title_node.get_text(strip=True) if title_node else ""

    # 作者 / 公众号名
    author_node = soup.find(id="js_name")
    author = author_node.get_text(strip=True) if author_node else ""

    # 发布时间
    pt_node = soup.find(id="publish_time")
    publish_time = pt_node.get_text(strip=True) if pt_node else ""
    # meta description
    desc = _meta(soup, "description", "og:description")

    # OG 兜底（页面结构被改版时用）
    og_title = _meta(soup, "og:title")
    og_image = _meta(soup, "og:image")
    og_site = _meta(soup, "og:site_name")
    og_time = _meta(soup, "article:published_time", "og:release_date")

    if not title:
        title = og_title
    if not author:
        author = og_site
    if not publish_time:
        publish_time = og_time
    if not publish_time:
        # 微信发布时间戳兜底：<script>var ct = "1758912000";</script>
        m = re.search(r"var\s+ct\s*=\s*[\"'](\d{10})[\"']", html)
        if m:
            publish_time = datetime.fromtimestamp(int(m.group(1))).strftime("%Y-%m-%d %H:%M")

    # 正文
    content_node = soup.find(id="js_content")
    if not content_node:
        if is_content_unavailable(html):
            err = "文章不可用：已被发布者删除 / 因违规下架 / 公众号已迁移（不是 IP 问题）"
        else:
            err = "no js_content node (可能被风控或文章已删除)"
        return {
            "title": title,
            "author": author,
            "publish_time": publish_time,
            "description": desc,
            "cover": og_image,
            "body": "",
            "body_chars": 0,
            "image_urls": [],
            "image_count": 0,
            "error": err,
        }

    # 提取图片 URL（微信懒加载真图在 data-src，data-src 优先）
    image_urls = []
    for img in content_node.find_all("img"):
        src = img.get("data-src") or img.get("src") or ""
        if src:
            image_urls.append(src)

    # 文本
    text = content_node.get_text(separator="\n", strip=True)
    text = re.sub(r"\n{2,}", "\n", text)

    return {
        "title": title,
        "author": author,
        "publish_time": publish_time,
        "description": desc,
        "cover": og_image,
        "body": text,
        "body_chars": len(text),
        "image_urls": image_urls,
        "image_count": len(image_urls),
    }


def fetch(url: str, ua_index: int = 0, timeout: int = 15, _last_html: str = None) -> dict:
    """抓取一篇公众号文章。UA 被墙自动换下一个 UA 重试。"""
    if "mp.weixin.qq.com" not in url:
        return {
            "url": url,
            "ok": False,
            "error": "不是微信公众号文章链接（需要 mp.weixin.qq.com）",
        }

    if ua_index >= len(USER_AGENTS):
        # 全部 UA 试完仍失败：区分「文章没了」和「IP 被墙」，两者的解法完全不同
        if _last_html and is_content_unavailable(_last_html):
            return {
                "url": url,
                "ok": False,
                "error": "文章不可用：已被发布者删除 / 因违规下架 / 公众号已迁移（不是 IP 问题）",
            }
        return {
            "url": url,
            "ok": False,
            "error": f"all {len(USER_AGENTS)} UAs blocked (IP 维度硬墙，换 IP/proxy 才解)",
        }

    headers = {
        "User-Agent": USER_AGENTS[ua_index],
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,image/apng,*/*;q=0.8",
        "Accept-Language": "zh-CN,zh;q=0.9,en-US;q=0.8,en;q=0.7",
        "Connection": "keep-alive",
    }

    try:
        r = requests.get(url, headers=headers, timeout=timeout, allow_redirects=True)
    except Exception as e:
        return {"url": url, "ok": False, "error": f"request failed: {e}"}

    if r.status_code != 200:
        return {"url": url, "ok": False, "error": f"http {r.status_code}"}

    if is_blocked(r.text):
        # 自动换 UA 重试
        return fetch(url, ua_index=ua_index + 1, timeout=timeout, _last_html=r.text)

    article = extract_article(r.text)
    article["url"] = url
    article["url_final"] = r.url
    article["ua_index"] = ua_index
    article["ok"] = bool(article.get("body_chars", 0) > 50)
    # 原始 HTML 留作 Markdown 转换复用，避免二次请求把风控暴露面翻倍
    article["_html"] = r.text

    if not article["ok"] and not article.get("error"):
        article["error"] = f"body too short ({article.get('body_chars', 0)} chars)"

    return article


# --------------------------------------------------------------------------
# Markdown 转换
# --------------------------------------------------------------------------

def _clean_text(s: str) -> str:
    """折叠所有空白（含换行）为单空格；块边界由标签结构决定。"""
    s = s.replace("\u00a0", " ").replace("\u200b", "").replace("\ufeff", "")
    return re.sub(r"\s+", " ", s)


def _is_placeholder_img(src: str) -> bool:
    if not src:
        return True
    if src.startswith("data:"):
        return True
    low = src.lower()
    if "wx_fmt=svg" in low or low.endswith(".svg"):
        return True
    return False


def _img_md(img, local_map: dict = None) -> str:
    src = img.get("data-src") or img.get("src") or ""
    if _is_placeholder_img(src):
        return ""
    if local_map and src in local_map:
        src = local_map[src]
    alt = (img.get("alt") or "").strip()
    return f"![{alt}]({src})"


def _is_promo(el) -> bool:
    """微信尾部推广块判定。"""
    try:
        txt = el.get_text(" ", strip=True)
    except Exception:
        return False
    if not txt or len(txt) > 60:
        return False
    return any(re.search(p, txt) for p in PROMO_PATTERNS)


def _inline_md(node, local_map: dict = None) -> str:
    buf = []
    _inline_walk(node, buf, local_map)
    return "".join(buf)


def _inline_walk(node, buf: list, local_map: dict = None) -> None:
    for child in node.children:
        if isinstance(child, NavigableString):
            buf.append(_clean_text(str(child)))
            continue
        nm = child.name
        if nm in JUNK_TAGS:
            continue
        if nm == "br":
            buf.append("\n")
            continue
        if nm == "img":
            md = _img_md(child, local_map)
            if md:
                # 微信正文里图片基本是独立块，跟前后文字断开，避免粘连成一行
                buf.append(md + "\n\n")
            continue
        if nm in ("strong", "b"):
            inner = _inline_md(child, local_map).strip()
            if inner:
                buf.append(f"**{inner}**")
            continue
        if nm in ("em", "i"):
            inner = _inline_md(child, local_map).strip()
            if inner:
                buf.append(f"*{inner}*")
            continue
        if nm == "a":
            inner = _inline_md(child, local_map).strip()
            href = (child.get("href") or "").strip()
            if inner and href:
                buf.append(f"[{inner}]({href})")
            elif inner:
                buf.append(inner)
            continue
        if nm in ("code", "tt"):
            inner = child.get_text(strip=True)
            if inner:
                buf.append(f"`{inner}`")
            continue
        if nm in INLINE_TAGS:
            _inline_walk(child, buf, local_map)
            continue
        # 块级元素嵌在行内上下文里：退化为纯文本
        t = _clean_text(child.get_text(" "))
        if t:
            buf.append(t)


def _flush(buf: list, out: list) -> None:
    if buf:
        text = "".join(buf).strip()
        buf.clear()
        if text:
            out.append(text)


def _list_md(node, depth: int = 0, local_map: dict = None) -> list:
    out = []
    ordered = node.name == "ol"
    idx = 1
    for li in node.find_all("li", recursive=False):
        text = _inline_md(li, local_map).strip()
        if text:
            marker = f"{idx}." if ordered else "-"
            out.append("  " * depth + f"{marker} {text}")
        idx += 1
    return out


def _table_md(node) -> str:
    rows = []
    for tr in node.find_all("tr"):
        cells = [c.get_text(" ", strip=True) for c in tr.find_all(["td", "th"])]
        if cells:
            rows.append(cells)
    if not rows:
        return ""
    width = max(len(r) for r in rows)
    lines = ["| " + " | ".join(rows[0] + [""] * (width - len(rows[0]))) + " |"]
    lines.append("|" + "|".join([" --- "] * width) + "|")
    for r in rows[1:]:
        lines.append("| " + " | ".join(r + [""] * (width - len(r))) + " |")
    return "\n".join(lines)


def _blocks(node, buf: list, out: list, local_map: dict, strip_promos: bool) -> None:
    for child in node.children:
        if isinstance(child, NavigableString):
            t = _clean_text(str(child))
            if t:
                buf.append(t)
            continue
        nm = child.name
        if nm in JUNK_TAGS:
            continue
        if nm == "br":
            buf.append("\n")
            continue
        if nm == "img":
            md = _img_md(child, local_map)
            if md:
                # 独立成块，避免和前后文字粘连
                _flush(buf, out)
                out.append(md)
            continue
        if nm in ("h1", "h2", "h3", "h4", "h5", "h6"):
            if strip_promos and _is_promo(child):
                continue
            _flush(buf, out)
            text = _inline_md(child, local_map).strip()
            if text:
                out.append("#" * (int(nm[1]) + 1) + " " + text)
            continue
        if nm == "p":
            if strip_promos and _is_promo(child):
                continue
            _flush(buf, out)
            text = _inline_md(child, local_map).strip()
            if text:
                out.append(text)
            continue
        if nm == "blockquote":
            if strip_promos and _is_promo(child):
                continue
            _flush(buf, out)
            text = _inline_md(child, local_map).strip()
            if text:
                out.append("\n".join("> " + ln for ln in text.split("\n")))
            continue
        if nm in ("ul", "ol"):
            _flush(buf, out)
            out.extend(_list_md(child, 0, local_map))
            continue
        if nm == "pre":
            _flush(buf, out)
            code = child.get_text()
            if code.strip():
                out.append("```\n" + code.rstrip() + "\n```")
            continue
        if nm == "hr":
            _flush(buf, out)
            out.append("---")
            continue
        if nm == "table":
            _flush(buf, out)
            t = _table_md(child)
            if t:
                out.append(t)
            continue
        if nm in INLINE_TAGS:
            _inline_walk(child, buf, local_map)
            continue
        # section / div / 其它容器：递归
        _blocks(child, buf, out, local_map, strip_promos)
    _flush(buf, out)


def html_to_markdown(content_node, local_map: dict = None, strip_promos: bool = True) -> str:
    buf = []
    out = []
    _blocks(content_node, buf, out, local_map or {}, strip_promos)
    text = "\n\n".join(x for x in out if x.strip())
    return re.sub(r"\n{3,}", "\n\n", text).strip()


def _yaml_str(s: str) -> str:
    """用 JSON 双引号风格转义，YAML 双引号标量兼容。"""
    return json.dumps(s or "", ensure_ascii=False)


def build_markdown(article: dict) -> str:
    """把一篇文章渲染成 Markdown（YAML frontmatter + 正文）。"""
    lines = [
        "---",
        f"title: {_yaml_str(article.get('title', ''))}",
        f"author: {_yaml_str(article.get('author', ''))}",
        f"publish_time: {_yaml_str(article.get('publish_time', ''))}",
        f"source_url: {_yaml_str(article.get('url_final') or article.get('url', ''))}",
        f"description: {_yaml_str(article.get('description', ''))}",
    ]
    if article.get("cover"):
        lines.append(f"cover: {_yaml_str(article['cover'])}")
    lines.append("---")
    lines.append("")

    title = article.get("title", "")
    if title:
        lines.append(f"# {title}")
        lines.append("")

    byline = " · ".join(
        x for x in (article.get("author", ""), article.get("publish_time", "")) if x
    )
    if byline:
        lines.append(f"> {byline}")
        lines.append("")

    body = article.get("markdown_body", "")
    if body:
        lines.append(body)
        lines.append("")

    return "\n".join(lines).rstrip() + "\n"


# --------------------------------------------------------------------------
# 输出
# --------------------------------------------------------------------------

def make_outpath(article: dict, out: str = None, out_dir: str = None, ext: str = ".txt") -> Path:
    if out:
        return Path(out)
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    url_hash = hashlib.md5(article["url"].encode()).hexdigest()[:6]
    fname = f"wx_{ts}_{url_hash}{ext}"
    if out_dir:
        return Path(out_dir) / fname
    return Path(fname)


def img_ext(url: str) -> str:
    """从 URL 推断图片扩展名，兜底 .jpg。"""
    path = url.split("?", 1)[0]
    last = path.rsplit("/", 1)[-1].lower()
    for ext in (".jpg", ".jpeg", ".png", ".gif", ".webp"):
        if last.endswith(ext):
            return ".jpg" if ext == ".jpeg" else ext
    # 看 wx_fmt 兜底
    if "wx_fmt=gif" in url:
        return ".gif"
    if "wx_fmt=webp" in url:
        return ".webp"
    if "wx_fmt=png" in url:
        return ".png"
    return ".jpg"


def download_images(
    image_urls: list,
    out_dir: str,
    referer: str = "https://mp.weixin.qq.com/",
    delay: float = 0.3,
) -> list:
    """下载文章图片到 <out_dir>/，带 Referer 头过微信 CDN 防盗链。

    Returns: list of (saved_path, size_bytes, error_or_None)
    """
    out_path = Path(out_dir)
    out_path.mkdir(parents=True, exist_ok=True)
    headers = {
        "User-Agent": USER_AGENTS[0],
        "Referer": referer,
        "Accept": "image/avif,image/webp,image/apng,image/svg+xml,image/*,*/*;q=0.8",
    }
    results = []
    for i, url in enumerate(image_urls):
        ext = img_ext(url)
        fname = f"img_{i+1:03d}{ext}"
        target = out_path / fname
        try:
            r = requests.get(url, headers=headers, timeout=20)
            if r.status_code == 200 and r.content:
                target.write_bytes(r.content)
                results.append((str(target), len(r.content), None))
            else:
                results.append((str(target), 0, f"http {r.status_code}"))
        except Exception as e:
            results.append((str(target), 0, str(e)))
        if i < len(image_urls) - 1:
            time.sleep(delay)
    return results


def write_txt(article: dict, out_path: Path) -> str:
    """结构化纯文本输出（给 Agent 直接消费，字段用 === XXX === 分隔）。"""
    with open(out_path, "w", encoding="utf-8") as f:
        f.write("=== TITLE ===\n")
        f.write(article.get("title", "") + "\n\n")
        f.write("=== URL ===\n")
        f.write(article.get("url_final", article.get("url", "")) + "\n\n")
        f.write("=== AUTHOR ===\n")
        f.write(article.get("author", "") + "\n\n")
        f.write("=== PUBLISH_TIME ===\n")
        f.write(article.get("publish_time", "") + "\n\n")
        f.write("=== DESCRIPTION ===\n")
        f.write(article.get("description", "") + "\n\n")
        f.write("=== META ===\n")
        f.write(f"body_chars: {article.get('body_chars', 0)}\n")
        f.write(f"image_count: {article.get('image_count', 0)}\n")
        f.write(f"ok: {article.get('ok', False)}\n")
        if article.get("ua_index") is not None:
            f.write(f"ua_index: {article['ua_index']}\n")
        if article.get("images_dir"):
            f.write(f"images_dir: {article['images_dir']}\n")
            f.write(f"images_downloaded: {article.get('images_downloaded', 0)}/{article.get('image_count', 0)}\n")
        if article.get("error"):
            f.write(f"error: {article['error']}\n")
        f.write("\n=== BODY ===\n")
        f.write(article.get("body", "") + "\n")
        if article.get("image_urls"):
            f.write("\n=== IMAGE_URLS ===\n")
            for img in article["image_urls"]:
                f.write(img + "\n")
    return str(out_path)


def make_local_map(article: dict, out_path: Path = None) -> dict:
    """构造「图片 URL -> 本地路径」映射。

    给了 out_path 就转成相对该文件所在目录的相对路径（正斜杠），
    保证 Markdown 产物拷走后依然可读。
    """
    if not article.get("images_dir"):
        return {}
    mapping = {}
    for idx, url in enumerate(article.get("image_urls", [])):
        local = Path(article["images_dir"]) / f"img_{idx+1:03d}{img_ext(url)}"
        if not local.exists():
            continue
        p = str(local)
        if out_path is not None:
            try:
                p = os.path.relpath(p, start=str(out_path.parent))
            except ValueError:
                pass
            p = p.replace("\\", "/")
        mapping[url] = p
    return mapping


def render_markdown_body(article: dict, local_map: dict, keep_promos: bool = False) -> str:
    """用 article['_html'] 做结构化 Markdown 转换。"""
    html = article.get("_html")
    if not html:
        return ""
    soup = BeautifulSoup(html, "html.parser")
    content_node = soup.find(id="js_content")
    if not content_node:
        return ""
    return html_to_markdown(
        content_node,
        local_map=local_map,
        strip_promos=not keep_promos,
    )


def write_output(
    article: dict,
    out: str = None,
    out_dir: str = None,
    fmt: str = "txt",
    keep_promos: bool = False,
) -> str:
    ext = ".md" if fmt == "md" else ".txt"
    out_path = make_outpath(article, out=out, out_dir=out_dir, ext=ext)
    out_path.parent.mkdir(parents=True, exist_ok=True)

    if fmt == "md":
        # Markdown 正文在这里才生成——因为本地图片引用需要相对 out 文件的路径
        local_map = make_local_map(article, out_path=out_path)
        article["markdown_body"] = render_markdown_body(
            article, local_map, keep_promos=keep_promos
        )
        with open(out_path, "w", encoding="utf-8") as f:
            f.write(build_markdown(article))
    else:
        write_txt(article, out_path)

    return str(out_path)


# --------------------------------------------------------------------------
# CLI
# --------------------------------------------------------------------------

def main():
    # Windows GBK 兜底（强制 stdout utf-8）
    try:
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    except Exception:
        pass

    parser = argparse.ArgumentParser(
        description="微信公众号文章本地抓取工具 (requests + bs4 + UA 伪装)",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument("--url", action="append", help="mp.weixin.qq.com 链接（可多次传）")
    parser.add_argument("--stdin", action="store_true", help="从 stdin 读 URL 列表（每行一个）")
    parser.add_argument("--out", help="单 URL 输出文件路径")
    parser.add_argument("--out_dir", help="多 URL 输出目录（自动生成 wx_<ts>_<hash>.<ext>）")
    parser.add_argument(
        "--format",
        choices=["txt", "md"],
        default="txt",
        help="输出格式：txt=结构化纯文本（默认，给 Agent 消费）；md=Markdown（内联图片）",
    )
    parser.add_argument("--json", action="store_true", help="以 JSON 格式输出到 stdout（不写文件）")
    parser.add_argument("--quiet", action="store_true", help="只输出最终结果路径，不输出进度")
    parser.add_argument("--timeout", type=int, default=15, help="HTTP 超时秒数")
    parser.add_argument(
        "--download-images",
        action="store_true",
        help="下载文章配图到本地（带 Referer 过防盗链）",
    )
    parser.add_argument(
        "--images-dir",
        default="./wx_images",
        help="图片下载根目录（每篇文章一个子目录，<images_dir>/<url_hash>/）",
    )
    parser.add_argument(
        "--keep-promos",
        action="store_true",
        help="Markdown 输出时保留微信尾部推广块（默认剔除）",
    )
    args = parser.parse_args()

    urls = []
    if args.url:
        urls.extend(args.url)
    if args.stdin:
        for line in sys.stdin:
            line = line.strip()
            if line and not line.startswith("#"):
                urls.append(line)

    if not urls:
        parser.print_help(sys.stderr)
        sys.exit(1)

    results = []
    for i, url in enumerate(urls):
        if not args.quiet and not args.json:
            print(f"[{i+1}/{len(urls)}] fetching: {url}", file=sys.stderr)
        article = fetch(url, timeout=args.timeout)

        # 下载图片（如果开启）
        if args.download_images and article.get("image_urls"):
            url_hash = hashlib.md5(url.encode()).hexdigest()[:6]
            img_dir = Path(args.images_dir) / url_hash
            if not args.quiet and not args.json:
                print(f"  downloading {len(article['image_urls'])} images -> {img_dir}", file=sys.stderr)
            dl_results = download_images(article["image_urls"], str(img_dir))
            ok_count = sum(1 for _, _, err in dl_results if err is None)
            article["images_dir"] = str(img_dir)
            article["images_downloaded"] = ok_count
            article["image_download_results"] = [
                {"path": p, "size": s, "error": e} for p, s, e in dl_results
            ]
        else:
            article["images_downloaded"] = 0

        results.append(article)

        if args.json:
            # JSON 模式没有输出文件，Markdown 正文用绝对路径即可
            if args.format == "md":
                article["markdown_body"] = render_markdown_body(
                    article, make_local_map(article), keep_promos=args.keep_promos
                )
            article.pop("_html", None)
            print(json.dumps(article, ensure_ascii=False, indent=2))
        else:
            out_path = write_output(
                article,
                out=args.out if len(urls) == 1 else None,
                out_dir=args.out_dir,
                fmt=args.format,
                keep_promos=args.keep_promos,
            )
            article.pop("_html", None)
            if not args.quiet:
                if article.get("ok"):
                    extra = ""
                    if args.download_images:
                        extra = f", {article.get('images_downloaded', 0)}/{article.get('image_count', 0)} imgs downloaded"
                    print(
                        f"  -> {out_path} | {article.get('body_chars', 0)} chars, "
                        f"{article.get('image_count', 0)} images{extra}",
                        file=sys.stderr,
                    )
                else:
                    print(f"  -> {out_path} | FAIL: {article.get('error', 'unknown')}", file=sys.stderr)

        if i < len(urls) - 1:
            time.sleep(1.5)  # 防风控

    # 退出码
    ok_count = sum(1 for r in results if r.get("ok"))
    if ok_count == len(results):
        sys.exit(0)
    elif ok_count == 0:
        sys.exit(2)
    else:
        sys.exit(1)


if __name__ == "__main__":
    main()
