import asyncio
import aiohttp
import feedparser
import time
from datetime import datetime, timezone
from typing import List, Dict, Any, Optional
from email.utils import parsedate_to_datetime

from django.utils import timezone as django_timezone
from asgiref.sync import sync_to_async

from .models import Source, Article, FetchLog
import logging

# Thêm import cho BeautifulSoup
from bs4 import BeautifulSoup

logger = logging.getLogger(__name__)

# Wrappers để gọi ORM an toàn trong async
create_article = sync_to_async(Article.objects.get_or_create, thread_sensitive=True)
update_source_last_fetched = sync_to_async(Source.save, thread_sensitive=True)
create_fetch_log = sync_to_async(FetchLog.objects.create, thread_sensitive=True)

class BaseFetcher:
    """Base class for all fetchers"""

    def __init__(self, source: Source):
        self.source = source

    async def fetch(self) -> List[Dict[str, Any]]:
        """Override this method in subclasses"""
        raise NotImplementedError

    def parse_date(self, date_str: str) -> datetime:
        """Parse RFC-822 or ISO date string to datetime (with tz)."""
        try:
            if not date_str:
                return django_timezone.now()

            # 1) ISO 8601 (e.g. "2025-05-23T21:27:59Z")
            try:
                return datetime.fromisoformat(date_str.replace('Z', '+00:00'))
            except ValueError:
                pass

            # 2) RFC-822 (e.g. "Fri, 23 May 2025 21:27:59 +0000")
            try:
                return parsedate_to_datetime(date_str)
            except (TypeError, ValueError):
                pass

            # 3) fallback: giờ hiện tại
            return django_timezone.now()

        except Exception as e:
            logger.warning(f"Date parsing failed for '{date_str}': {e}")
            return django_timezone.now()


class RSSFetcher(BaseFetcher):
    """Fetcher for RSS feeds"""

    async def fetch(self) -> List[Dict[str, Any]]:
        articles = []
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(self.source.url) as response:
                    if response.status == 200:
                        xml_data = await response.text()
                        feed = feedparser.parse(xml_data)

                        for item in feed.entries:
                            article_data = {
                                'title': item.get('title', ''),
                                'url': item.get('link', ''),
                                'source': self.source,
                                'published_at': self.parse_date(item.get('published', '')),
                                'content_type': self.source.content_type,
                                'summary': item.get('summary', '')
                            }
                            articles.append(article_data)

        except Exception as e:
            logger.error(f"RSS fetch error for {self.source.source}: {e}")
            raise

        return articles


class APIFetcher(BaseFetcher):
    """Fetcher for API endpoints"""

    async def fetch(self) -> List[Dict[str, Any]]:
        articles = []
        params = self.source.params or {}
        headers = params.get('headers', {})

        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(
                    self.source.url,
                    headers=headers,
                    params=params.get('query_params', {})
                ) as response:
                    if response.status == 200:
                        data = await response.json()
                        articles = self._parse_api_response(data)

        except Exception as e:
            logger.error(f"API fetch error for {self.source.source}: {e}")
            raise

        return articles

    def _parse_api_response(self, data: Dict) -> List[Dict[str, Any]]:
        articles = []
        items = data.get('items', data.get('articles', data.get('data', [])))

        for item in items:
            article_data = {
                'title': item.get('title', ''),
                'url': item.get('url', item.get('link', '')),
                'source': self.source,
                'published_at': self.parse_date(item.get('published_at', item.get('pubDate', ''))),
                'content_type': self.source.content_type,
                'summary': item.get('summary', item.get('description', ''))
            }
            articles.append(article_data)

        return articles


class AgentQLFetcher(BaseFetcher):
    """Fetcher for static websites using AgentQL"""

    async def fetch(self) -> List[Dict[str, Any]]:
        articles = []
        params = self.source.params or {}

        if 'api_key' not in params or 'prompt' not in params:
            raise ValueError("AgentQL fetcher requires 'api_key' and 'prompt' in params")

        try:
            payload = {
                "url": self.source.url,
                "prompt": params['prompt']
            }
            headers = {
                "Content-Type": "application/json",
                "X-API-Key": params['api_key']
            }

            async with aiohttp.ClientSession() as session:
                async with session.post(
                    "https://api.agentql.com/v1/query-data",
                    json=payload,
                    headers=headers
                ) as response:
                    if response.status == 200:
                        result = await response.json()
                        articles = self._parse_agentql_response(result)

        except Exception as e:
            logger.error(f"AgentQL fetch error for {self.source.source}: {e}")
            raise

        return articles

    def _parse_agentql_response(self, result: Dict) -> List[Dict[str, Any]]:
        articles = []
        if result.get('data'):
            first_key = next(iter(result['data'].keys()))
            urls = result['data'][first_key] or []
            for url in urls:
                articles.append({
                    'title': f"Article from {self.source.source}",
                    'url': url,
                    'source': self.source,
                    'published_at': django_timezone.now(),
                    'content_type': self.source.content_type,
                    'summary': ''
                })
        return articles


class FetcherFactory:
    """Factory class to create appropriate fetcher"""

    FETCHER_MAP = {
        'rss': RSSFetcher,
        'api': APIFetcher,
        'static': AgentQLFetcher,
    }

    @classmethod
    def create_fetcher(cls, source: Source) -> BaseFetcher:
        fetcher_class = cls.FETCHER_MAP.get(source.type)
        if not fetcher_class:
            raise ValueError(f"Unknown source type: {source.type}")
        return fetcher_class(source)


# Thêm hàm cào chi tiết bài viết
async def fetch_article_detail(url: str) -> Dict[str, str]:
    """Cào nội dung chi tiết và ảnh đại diện từ url bài viết"""
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(url, timeout=15) as resp:
                if resp.status != 200:
                    return {"content": "", "thumbnail": ""}
                html = await resp.text()
        soup = BeautifulSoup(html, "html.parser")
        # Loại bỏ các phần không cần thiết
        for sel in ["script", "style", "footer", ".ads", ".comments", ".related"]:
            for tag in soup.select(sel):
                tag.decompose()
        # Ưu tiên các khối chính
        root = None
        for sel in ["main", "article", "#content", ".post", ".entry"]:
            root = soup.select_one(sel)
            if root:
                break
        if not root:
            root = soup
        title = soup.title.string.strip() if soup.title else ""
        meta = ""
        meta_tag = soup.find("meta", attrs={"name": "description"})
        if meta_tag and meta_tag.get("content"):
            meta = meta_tag["content"].strip()
        paragraphs = [p.get_text(strip=True) for p in root.find_all("p")]
        content = f"{title}\n\n{meta}\n\n" + "\n".join(paragraphs)
        content = content[:4000]
        # Ảnh đại diện: lấy ảnh đầu tiên trong root hoặc thẻ og:image
        thumbnail = ""
        img_tag = root.find("img")
        if img_tag and img_tag.get("src"):
            thumbnail = img_tag["src"]
        else:
            ogimg = soup.find("meta", property="og:image")
            if ogimg and ogimg.get("content"):
                thumbnail = ogimg["content"]
        return {"content": content, "thumbnail": thumbnail}
    except Exception as e:
        logger.warning(f"Lỗi cào chi tiết {url}: {e}")
        return {"content": "", "thumbnail": ""}


class DataCollector:
    """Main collector class to orchestrate fetching"""

    async def collect_from_source(self, source: Source) -> Dict[str, Any]:
        start_time = time.time()
        log_data = {
            'source': source,
            'status': 'error',
            'articles_count': 0,
            'error_message': '',
            'execution_time': 0
        }

        try:
            fetcher = FetcherFactory.create_fetcher(source)
            articles_data = await fetcher.fetch()

            # Save articles (async-safe)
            saved_count = 0
            for data in articles_data:
                try:
                    article_obj, created = await create_article(
                        url=data['url'],
                        defaults={
                            'title': data['title'],
                            'source': source,
                            'content_type': data['content_type'],
                            'published_at': data['published_at'],
                            'summary': data.get('summary', '')
                        }
                    )
                    if created:
                        saved_count += 1
                        # Cào chi tiết nội dung và thumbnail, cập nhật lại Article
                        detail = await fetch_article_detail(data['url'])
                        await sync_to_async(setattr)(article_obj, 'content', detail['content'])
                        await sync_to_async(setattr)(article_obj, 'thumbnail', detail['thumbnail'])
                        await sync_to_async(article_obj.save)()
                except Exception as e:
                    logger.error(f"Error saving article {data.get('url')}: {e}")
                    continue

            # Update source.last_fetched
            source.last_fetched = django_timezone.now()
            await update_source_last_fetched(source, update_fields=['last_fetched'])

            log_data.update({
                'status': 'success',
                'articles_count': saved_count,
            })

        except Exception as e:
            log_data.update({
                'error_message': str(e),
                'status': 'error'
            })
            logger.error(f"Collection failed for {source.source}: {e}")

        finally:
            log_data['execution_time'] = time.time() - start_time
            # Create fetch log
            await create_fetch_log(**log_data)

        return log_data

    async def collect_all_active_sources(self):
        active_sources = await sync_to_async(list)(Source.objects.filter(is_active=True))
        tasks = [self.collect_from_source(src) for src in active_sources]

        if tasks:
            results = await asyncio.gather(*tasks, return_exceptions=True)
            success_count = sum(1 for r in results if isinstance(r, dict) and r.get('status') == 'success')
            total_articles = sum(r.get('articles_count', 0) for r in results if isinstance(r, dict))
            logger.info(f"Collection completed: {success_count}/{len(tasks)} sources successful, {total_articles} new articles")
            return results
        return []
