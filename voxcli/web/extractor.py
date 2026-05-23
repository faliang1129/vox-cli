"""HTML 提取器 - 将 HTML 转换为 Markdown"""

import logging
from typing import Dict, Optional
from urllib.parse import urljoin

from bs4 import BeautifulSoup, Tag

logger = logging.getLogger(__name__)


class HtmlExtractor:
    def extract(self, html: str, base_url: str) -> Dict[str, str]:
        soup = BeautifulSoup(html, "lxml")
        title = self._extract_title(soup)
        self._remove_noise(soup)
        markdown = self._to_markdown(soup, base_url)
        return {"title": title, "markdown": markdown}

    @staticmethod
    def _extract_title(soup: BeautifulSoup) -> str:
        title_tag = soup.find("title")
        return title_tag.get_text(strip=True) if title_tag else ""

    @staticmethod
    def _remove_noise(soup: BeautifulSoup):
        for selector in ["script", "style", "nav", "footer", "header",
                         ".sidebar", ".menu", ".ad", ".advertisement",
                         ".social-share", ".comments", "[role=complementary]"]:
            for elem in soup.select(selector):
                elem.decompose()

    @staticmethod
    def _to_markdown(soup: BeautifulSoup, base_url: str) -> str:
        parts = []
        body = soup.find("body") or soup
        for elem in body.children:
            if not isinstance(elem, Tag):
                continue
            tag = elem.name.lower() if elem.name else ""
            if tag in ("h1", "h2", "h3", "h4", "h5", "h6"):
                level = int(tag[1])
                parts.append(f"\n{'#' * level} {elem.get_text(strip=True)}\n")
            elif tag == "p":
                text = elem.get_text(strip=True)
                if text:
                    parts.append(f"\n{text}\n")
            elif tag in ("ul", "ol"):
                for li in elem.find_all("li"):
                    prefix = "- " if tag == "ul" else "1. "
                    parts.append(f"{prefix}{li.get_text(strip=True)}\n")
                parts.append("\n")
            elif tag == "pre":
                code = elem.get_text()
                parts.append(f"\n```\n{code}\n```\n")
            elif tag == "code":
                parts.append(f"`{elem.get_text(strip=True)}`")
            elif tag == "a":
                href = elem.get("href", "")
                if href and base_url:
                    href = urljoin(base_url, href)
                text = elem.get_text(strip=True)
                if text and href:
                    parts.append(f"[{text}]({href})")
            elif tag == "img":
                src = elem.get("src", "")
                if src and base_url:
                    src = urljoin(base_url, src)
                alt = elem.get("alt", "")
                parts.append(f"![{alt}]({src})")
            elif tag == "blockquote":
                text = elem.get_text(strip=True)
                if text:
                    parts.append(f"\n> {text}\n")
            elif tag in ("table", "div", "section", "article", "main"):
                parts.append(HtmlExtractor._to_markdown(elem, base_url))
        return "\n".join(parts).strip()
