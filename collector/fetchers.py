import asyncio
import aiohttp
import feedparser
import time
from datetime import datetime, timezone
from typing import List, Dict, Any
from django.utils import timezone as django_timezone
from .models import Source, Article, FetchLog
import logging

logger = logging.getLogger(__name__)

class BaseFetcher:
    """Base class for all fetchers"""
    
    def __init__(self, source: Source):
        self.source = source
        
    async def fetch(self) -> List[Dict[str, Any]]:
        """Override this method in subclasses"""
        raise NotImplementedError
        
    def parse_date(self, date_str: str) -> datetime:
        """Parse date string to datetime object"""
        try:
            if date_str:
                # Try parsing common formats
                try:
                    return datetime.fromisoformat(date_str.replace('Z', '+00:00'))
                except:
                    # Fallback to feedparser's date parsing
                    parsed_time = feedparser._parse_date(date_str)
                    if parsed_time:
                        return datetime(*parsed_time[:6], tzinfo=timezone.utc)
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
                                'source': self.source.source,
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
                        
                        # Custom parsing based on API structure
                        articles = self._parse_api_response(data)
                        
        except Exception as e:
            logger.error(f"API fetch error for {self.source.source}: {e}")
            raise
            
        return articles
    
    def _parse_api_response(self, data: Dict) -> List[Dict[str, Any]]:
        """Parse API response - customize based on your API structure"""
        articles = []
        
        # Example parsing - adjust based on your API response format
        items = data.get('items', data.get('articles', data.get('data', [])))
        
        for item in items:
            article_data = {
                'title': item.get('title', ''),
                'url': item.get('url', item.get('link', '')),
                'source': self.source.source,
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
        """Parse AgentQL response"""
        articles = []
        
        if result.get('data'):
            # Get the first key's data (AgentQL returns nested structure)
            first_key = next(iter(result['data'].keys()))
            urls = result['data'][first_key] or []
            
            for url in urls:
                article_data = {
                    'title': f"Article from {self.source.source}",
                    'url': url,
                    'source': self.source.source,
                    'published_at': django_timezone.now(),
                    'content_type': self.source.content_type,
                    'summary': ''
                }
                articles.append(article_data)
                
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
        """Collect data from a single source"""
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
            
            # Save articles to database
            saved_count = 0
            for article_data in articles_data:
                try:
                    article, created = Article.objects.get_or_create(
                        url=article_data['url'],
                        defaults={
                            'title': article_data['title'],
                            'source': source,
                            'content_type': article_data['content_type'],
                            'published_at': article_data['published_at'],
                            'summary': article_data.get('summary', '')
                        }
                    )
                    if created:
                        saved_count += 1
                except Exception as e:
                    logger.error(f"Error saving article {article_data.get('url')}: {e}")
                    continue
            
            # Update source last_fetched
            source.last_fetched = django_timezone.now()
            source.save(update_fields=['last_fetched'])
            
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
            FetchLog.objects.create(**log_data)
            
        return log_data
    
    async def collect_all_active_sources(self):
        """Collect data from all active sources"""
        active_sources = Source.objects.filter(is_active=True)
        tasks = []
        
        for source in active_sources:
            tasks.append(self.collect_from_source(source))
        
        if tasks:
            results = await asyncio.gather(*tasks, return_exceptions=True)
            
            success_count = sum(1 for r in results if isinstance(r, dict) and r.get('status') == 'success')
            total_articles = sum(r.get('articles_count', 0) for r in results if isinstance(r, dict))
            
            logger.info(f"Collection completed: {success_count}/{len(tasks)} sources successful, {total_articles} new articles")
        
        return results if tasks else []