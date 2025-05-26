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
                    _, created = await create_article(
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
