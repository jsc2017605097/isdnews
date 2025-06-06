import asyncio
import aiohttp
import feedparser
import time
from datetime import datetime, timezone, timedelta
from typing import List, Dict, Any, Optional
from email.utils import parsedate_to_datetime

import ssl
import certifi

from .utils import get_agentql_api_key_async

from django.utils import timezone as django_timezone
from django.db import models  # Thêm import này
from asgiref.sync import sync_to_async

from .models import Source, Article, FetchLog, AILog
import logging

# Thêm import cho BeautifulSoup
from bs4 import BeautifulSoup

# Thêm import cho gọi API AI
import json
import os
from django.db.models import Q
from django.db import transaction

# Thêm import cho Playwright
from playwright.async_api import async_playwright

logger = logging.getLogger(__name__)

# Thiết lập logger lưu file riêng cho AI/thumbnail
ai_log_path = os.path.join(os.path.dirname(__file__), '../logs/collector_ai.log')
ai_log_path = os.path.abspath(ai_log_path)
os.makedirs(os.path.dirname(ai_log_path), exist_ok=True)
ai_logger = logging.getLogger('collector_ai')
ai_logger.setLevel(logging.INFO)
if not ai_logger.handlers:
    file_handler = logging.FileHandler(ai_log_path, encoding='utf-8')
    formatter = logging.Formatter('%(asctime)s %(levelname)s %(message)s')
    file_handler.setFormatter(formatter)
    ai_logger.addHandler(file_handler)

# SSL context chuẩn dùng certifi
ssl_context = ssl.create_default_context(cafile=certifi.where())

# Wrappers để gọi ORM an toàn trong async
create_article = sync_to_async(Article.objects.get_or_create, thread_sensitive=True)
update_source_last_fetched = sync_to_async(Source.save, thread_sensitive=True)
create_fetch_log = sync_to_async(FetchLog.objects.create, thread_sensitive=True)
create_ailog = sync_to_async(AILog.objects.create, thread_sensitive=True)


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
            async with aiohttp.ClientSession(connector=aiohttp.TCPConnector(ssl=ssl_context)) as session:
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
            async with aiohttp.ClientSession(connector=aiohttp.TCPConnector(ssl=ssl_context)) as session:
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
                'summary': item.get('summary', item.get('description', ''))
            }
            articles.append(article_data)

        return articles


class AgentQLFetcher(BaseFetcher):
    """Fetcher for static websites using AgentQL"""
    
    async def fetch(self) -> List[Dict[str, Any]]:
        articles = []
        params = self.source.params or {}

        if 'prompt' not in params:
            raise ValueError("AgentQL fetcher requires 'prompt' in params")

        try:
            api_key = await get_agentql_api_key_async()
            payload = {
                "url": self.source.url,
                "prompt": params['prompt']
            }
            headers = {
                "Content-Type": "application/json",
                "X-API-Key": api_key
            }

            async with aiohttp.ClientSession(connector=aiohttp.TCPConnector(ssl=ssl_context)) as session:
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


# Hàm gọi OpenRouter AI để dịch và tóm tắt nội dung sang tiếng Việt
async def call_openrouter_ai(content: str, url: str, ai_type: str = "dev") -> str:
    from .utils import get_openrouter_api_key_async, get_teams_webhook_async

    OPENROUTER_API_KEY = await get_openrouter_api_key_async()
    if not OPENROUTER_API_KEY:
        logger.error("OpenRouter API key not found in configuration")
        raise Exception("OpenRouter API key not found in configuration")

    OPENROUTER_ENDPOINT = "https://openrouter.ai/api/v1/chat/completions"
    logger.info(f"Using OpenRouter endpoint with key: {OPENROUTER_API_KEY[:10]}...")

    # Webhook URL cho team tương ứng
    teams_webhook = await get_teams_webhook_async(ai_type)

    # Tuỳ theo ai_type mà prompt có thể khác nhau
    if ai_type == "dev":
        system_prompt = "Bạn là trợ lý AI cho developer."
    elif ai_type == "ba":
        system_prompt = "Bạn là trợ lý AI cho business analyst."
    elif ai_type == "system":
        system_prompt = "Bạn là trợ lý AI cho system admin."
    else:
        system_prompt = "Bạn là trợ lý AI."

    prompt = f"Dưới đây là nội dung thô tôi cào từ trang web, Hãy phân tích và đưa ra ý kiến về nội dung này và nói lại cho tôi một cách dễ hiểu bằng tiếng việt,ví dụ nếu có, nhớ đặt tiêu đề và kết luận (có dẫn nguồn từ {url}) cho câu trả lời của bạn (tôi yêu cầu nếu nội dung tôi gửi cho bạn mà trống thì hãy gửi lại cho tôi với nội dung, Tôi không thể phân tích nội dung từ nguồn: {url}, cái này bắt buộc): {content}"

    payload = {
        "model": "deepseek/deepseek-r1:free",
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": prompt}
        ]
    }

    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {OPENROUTER_API_KEY}",
        "HTTP-Referer": "https://github.com/isdnews",
        "User-Agent": "ISDNews/1.0.0"
    }

    try:
        logger.info(f"[OpenRouter] Gửi prompt cho {url}: {prompt[:500]}...")
        async with aiohttp.ClientSession(connector=aiohttp.TCPConnector(ssl=ssl_context)) as session:
            async with session.post(OPENROUTER_ENDPOINT, headers=headers, json=payload, timeout=60) as resp:
                if resp.status != 200:
                    error_text = await resp.text()
                    logger.error(f"[OpenRouter] Error response {resp.status}: {error_text}")
                    raise Exception(f"OpenRouter API error: {resp.status} - {error_text}")

                data = await resp.json()
                logger.info(f"[OpenRouter] Nhận response cho {url}: {str(data)[:500]}...")

                if data.get("choices") and data["choices"][0]["message"].get("content"):
                    result = data["choices"][0]["message"]["content"].strip()
                    logger.info(f"[OpenRouter] Nội dung dịch cho {url}: {result[:500]}...")
                    
                    # Tạo hàm đồng bộ để gọi create_ailog
                    def create_log_sync():
                        return AILog.objects.create(
                            url=url,
                            prompt=prompt,
                            response=str(data),
                            result=result,
                            status='success',
                            error_message=''
                        )
                    
                    # Gọi hàm đồng bộ trong thread riêng
                    await asyncio.to_thread(create_log_sync)

                    if teams_webhook:
                        logger.info(f"[OpenRouter] Sending notification to team {ai_type} for URL: {url}")
                        await notify_teams(teams_webhook, f"Bài viết mới cho team {ai_type}", result, url)
                    else:
                        logger.warning(f"[OpenRouter] No Teams webhook found for team {ai_type}, skipping notification")

                    return result
                else:
                    logger.warning(f"[OpenRouter] Không nhận được nội dung dịch cho {url}, trả về content gốc.")
                    
                    # Tạo hàm đồng bộ để gọi create_ailog
                    def create_error_log_sync():
                        return AILog.objects.create(
                            url=url,
                            prompt=prompt,
                            response=str(data),
                            result=content,
                            status='error',
                            error_message='No content from AI'
                        )
                    
                    # Gọi hàm đồng bộ trong thread riêng
                    await asyncio.to_thread(create_error_log_sync)
                    
                    return content

    except Exception as e:
        logger.warning(f"Lỗi gọi OpenRouter AI: {e}")
        try:
            error_response = await resp.text() if 'resp' in locals() else ''
        except Exception:
            error_response = ''
            
        # Tạo hàm đồng bộ để gọi create_ailog
        def create_exception_log_sync():
            return AILog.objects.create(
                url=url,
                prompt=prompt,
                response=error_response,
                result=content,
                status='error',
                error_message=str(e)
            )
        
        # Gọi hàm đồng bộ trong thread riêng
        await asyncio.to_thread(create_exception_log_sync)
        
        return content


async def fetch_article_detail(url: str) -> Dict[str, str]:
    """
    Dùng Playwright để render trang có JavaScript, đợi load hết nội dung rồi lấy HTML,
    sau đó dùng BeautifulSoup để xử lý trích xuất nội dung và ảnh thumbnail.
    """
    try:
        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=True)
            page = await browser.new_page()
            logger.info(f"[fetch_article_detail] Đang truy cập URL: {url}")
            
            # Truy cập trang
            await page.goto(url)
            
            # Đợi trạng thái networkidle (không request mới)
            await page.wait_for_load_state("networkidle")
            
            # Đợi phần tử chính xuất hiện (thay 'article' bằng selector phù hợp nếu cần)
            try:
                await page.wait_for_selector('article', timeout=7000)
                logger.info(f"[fetch_article_detail] Selector 'article' đã xuất hiện")
            except Exception:
                logger.warning(f"[fetch_article_detail] Không tìm thấy selector 'article' trong trang")
            
            # Đợi thêm 2 giây cho chắc chắn mọi JS đã chạy xong
            await page.wait_for_timeout(2000)
            
            # Lấy HTML sau khi render xong
            html = await page.content()
            await browser.close()

        # Xử lý HTML với BeautifulSoup
        soup = BeautifulSoup(html, "html.parser")
        
        # Loại bỏ tag không cần thiết
        for sel in ["script", "style", "footer", ".ads", ".comments", ".related"]:
            for tag in soup.select(sel):
                tag.decompose()

        # Tìm phần nội dung chính (có thể mở rộng thêm selector nếu cần)
        selectors = ["main", "article", "#content", ".post", ".entry", ".article-body", ".content"]
        root = None
        for sel in selectors:
            root = soup.select_one(sel)
            if root:
                logger.info(f"[fetch_article_detail] Tìm thấy selector nội dung chính: {sel}")
                break
        if not root:
            logger.warning("[fetch_article_detail] Không tìm thấy selector nội dung chính, dùng toàn bộ trang")
            root = soup

        # Lấy title và meta description
        title = soup.title.string.strip() if soup.title else ""
        meta_tag = soup.find("meta", attrs={"name": "description"})
        meta = meta_tag["content"].strip() if meta_tag and meta_tag.get("content") else ""

        # Lấy text các đoạn <p>
        paragraphs = [p.get_text(strip=True) for p in root.find_all("p")]
        raw_content = f"{title}\n\n{meta}\n\n" + "\n".join(paragraphs)
        raw_content = raw_content[:4000]

        logger.info(f"[fetch_article_detail] Độ dài nội dung thô: {len(raw_content)}")
        logger.debug(f"[fetch_article_detail] Đoạn nội dung thô: {raw_content[:500]}")

        if len(raw_content.strip()) < 300:
            logger.warning(f"[fetch_article_detail] Nội dung quá ngắn ({len(raw_content)}) bỏ qua url {url}")
            return {"content": "", "thumbnail": ""}

        # Gọi AI tóm tắt
        ai_content = await call_openrouter_ai(raw_content, url)
        ai_logger.info(f"AI tóm tắt cho {url}: {ai_content[:200]}...")

        # Lấy thumbnail ưu tiên meta og:image, sau đó ảnh đầu tiên trong nội dung
        thumbnail = ""
        ogimg = soup.find("meta", property="og:image")
        if ogimg and ogimg.get("content"):
            thumbnail = ogimg["content"]
            ai_logger.info(f"Thumbnail og:image cho {url}: {thumbnail}")
        else:
            img_tag = root.find("img") if root else None
            if img_tag and img_tag.get("src"):
                thumbnail = img_tag["src"]
                ai_logger.info(f"Thumbnail ảnh đầu tiên trong nội dung cho {url}: {thumbnail}")
            else:
                img_tag2 = soup.find("img")
                if img_tag2 and img_tag2.get("src"):
                    thumbnail = img_tag2["src"]
                    ai_logger.info(f"Thumbnail ảnh đầu tiên trong trang cho {url}: {thumbnail}")

        return {"content": ai_content, "thumbnail": thumbnail}

    except Exception as e:
        logger.error(f"Lỗi fetch_article_detail cho {url}: {e}")
        ai_logger.error(f"Lỗi fetch_article_detail cho {url}: {e}")
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

            # Lọc lấy tối đa 5 bài viết mới (chưa có trong Article)
            existing_urls = set(await sync_to_async(list)(Article.objects.filter(url__in=[a['url'] for a in articles_data]).values_list('url', flat=True)))
            new_articles = [a for a in articles_data if a['url'] not in existing_urls][:5]

            saved_count = 0
            for data in new_articles:
                try:
                    article_obj, created = await create_article(
                        url=data['url'],
                        defaults={
                            'title': data['title'],
                            'source': source,
                            'published_at': data['published_at'],
                            'summary': data.get('summary', ''),
                            'content': '',  # Chưa cào chi tiết, để rỗng hoặc cào thô nếu muốn
                            'thumbnail': '',
                            'is_ai_processed': False,
                            'ai_type': '',
                            'ai_content': '',
                        }
                    )
                    saved_count += 1
                    await asyncio.sleep(2)
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

    async def collect_all_active_sources(self, team_code: Optional[str] = None):
        now = django_timezone.now()
        queryset = Source.objects.filter(is_active=True)

        if team_code:
            queryset = queryset.filter(team__code=team_code)

        # Lọc các nguồn có force_collect=True hoặc đã đến thời gian thu thập
        queryset = queryset.filter(
            models.Q(force_collect=True) |
            models.Q(last_fetched__isnull=True) |
            models.Q(last_fetched__lte=now - models.F('fetch_interval') * timedelta(seconds=1))
        )

        active_sources = await sync_to_async(list)(queryset)

        if active_sources:
            tasks = [self.collect_from_source(src) for src in active_sources]
            results = await asyncio.gather(*tasks, return_exceptions=True)
            success_count = sum(1 for r in results if isinstance(r, dict) and r.get('status') == 'success')
            total_articles = sum(r.get('articles_count', 0) for r in results if isinstance(r, dict))
            logger.info(f"Collection completed: {success_count}/{len(tasks)} sources successful, {total_articles} new articles")
            return results
        return []


async def notify_teams(webhook_url: str, title: str, content: str, url: str = None):
    """Gửi thông báo đến Microsoft Teams thông qua webhook"""
    logger.info(f"[Teams] Preparing to send notification...")
    logger.info(f"[Teams] Webhook URL: {webhook_url[:30]}...")
    logger.info(f"[Teams] Title: {title}")
    logger.info(f"[Teams] URL: {url}")
    logger.info(f"[Teams] Content length: {len(content)} characters")

    if not webhook_url:
        logger.warning("[Teams] No webhook URL provided, skipping notification")
        return

    try:
        card = {
            "@type": "MessageCard",
            "@context": "http://schema.org/extensions",
            "summary": title,
            "themeColor": "0076D7",
            "sections": [{
                "activityTitle": title,
                "activitySubtitle": f"Source: {url}" if url else None,
                "text": content  # Gửi toàn bộ nội dung không cắt ngắn
            }]
        }

        logger.info("[Teams] Sending request to Teams webhook...")
        async with aiohttp.ClientSession(connector=aiohttp.TCPConnector(ssl=ssl_context)) as session:
            async with session.post(webhook_url, json=card) as resp:
                response_text = await resp.text()
                if resp.status == 200:
                    logger.info("[Teams] Successfully sent notification to Teams")
                    logger.debug(f"[Teams] Response: {response_text}")
                else:
                    logger.error(f"[Teams] Error sending notification. Status: {resp.status}")
                    logger.error(f"[Teams] Error response: {response_text}")

    except Exception as e:
        logger.error(f"[Teams] Failed to send notification: {str(e)}")
        logger.exception("[Teams] Full exception:")
