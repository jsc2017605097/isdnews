import asyncio
from celery import shared_task
from django.utils import timezone
from .models import Source, Article, JobConfig, Team
from .fetchers import DataCollector, call_openrouter_ai
import logging
from django.db import transaction
from asgiref.sync import async_to_sync, sync_to_async

logger = logging.getLogger(__name__)

@shared_task
def collect_data_from_source(source_id):
    """Celery task to collect data from a specific source"""
    try:
        source = Source.objects.get(id=source_id, is_active=True)
        collector = DataCollector()
        
        # Run async function in sync context
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            result = loop.run_until_complete(collector.collect_from_source(source))
            return {
                'success': True,
                'source': source.source,
                'articles_count': result['articles_count'],
                'status': result['status']
            }
        finally:
            loop.close()
            
    except Source.DoesNotExist:
        return {
            'success': False,
            'error': f'Source with ID {source_id} not found or inactive'
        }
    except Exception as e:
        logger.error(f'Celery task failed for source {source_id}: {e}')
        return {
            'success': False,
            'error': str(e)
        }

@shared_task
def collect_data_from_all_sources():
    logger.info('[Celery Beat] Đã gọi task collect_data_from_all_sources')
    try:
        collector = DataCollector()
        
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            results = loop.run_until_complete(collector.collect_all_active_sources())
            
            success_count = sum(1 for r in results if isinstance(r, dict) and r.get('status') == 'success')
            total_articles = sum(r.get('articles_count', 0) for r in results if isinstance(r, dict))
            
            return {
                'success': True,
                'sources_processed': len(results),
                'successful_sources': success_count,
                'total_new_articles': total_articles
            }
        finally:
            loop.close()
            
    except Exception as e:
        logger.error(f'Celery task failed for all sources: {e}')
        return {
            'success': False,
            'error': str(e)
        }

@shared_task
def scheduled_collection():
    """Periodic task to collect data from sources that are due for update"""
    try:
        now = timezone.now()
        # Find sources that are due for update
        sources_due = Source.objects.filter(
            is_active=True
        ).extra(
            where=['last_fetched IS NULL OR (EXTRACT(EPOCH FROM %s) - EXTRACT(EPOCH FROM last_fetched)) >= fetch_interval'],
            params=[now]
        )
        
        if not sources_due.exists():
            return {
                'success': True,
                'message': 'No sources due for update',
                'sources_processed': 0
            }
        
        # Trigger collection for each due source
        results = []
        for source in sources_due:
            result = collect_data_from_source.delay(source.id)
            results.append(result)
        
        return {
            'success': True,
            'message': f'Triggered collection for {len(results)} sources',
            'sources_processed': len(results)
        }
        
    except Exception as e:
        logger.error(f'Scheduled collection task failed: {e}')
        return {
            'success': False,
            'error': str(e)
        }

# === Helper async function to process OpenRouter job ===
async def _process_openrouter_async():
    logger.info('[Celery Beat] Running _process_openrouter_async')
    config = await sync_to_async(JobConfig.objects.filter(job_type='openrouter').first)()
    if not config or not config.enabled:
        logger.info('OpenRouter job disabled or config not found.')
        return

    # Lấy danh sách team codes từ database thay vì fix cứng
    try:
        # Sử dụng sync_to_async để gọi ORM trong async context
        teams = await sync_to_async(list)(Team.objects.filter(is_active=True).values_list('code', flat=True))
    except Exception as e:
        logger.error(f"Error fetching active team codes from database: {e}")
        return # Hoặc xử lý lỗi theo cách khác phù hợp

    if not teams:
        logger.warning("No active teams found in database.")
        return

    types = teams

    # Áp dụng logic round-robin cho các team codes lấy từ database
    # last_type = await sync_to_async(lambda: config.last_type_sent or types[0])()
    last_type = config.last_type_sent if config.last_type_sent else types[0]

    idx = types.index(last_type) if last_type in types else 0
    next_idx = (idx + 1) % len(types)
    next_type = types[next_idx]

    article = await sync_to_async(Article.objects.filter(is_ai_processed=False).first)()
    if not article:
        logger.info('No articles to process for OpenRouter job.')
        return

    # Gọi OpenRouter AI (async)
    ai_content = await call_openrouter_ai(article.content, article.url, next_type)

    # Cập nhật bài viết và config (trong sync context)
    def update_article_and_config():
        with transaction.atomic():
            # Lấy lại article object trong transaction để đảm bảo tính nhất quán
            article_obj = Article.objects.get(id=article.id)
            article_obj.ai_content = ai_content
            article_obj.is_ai_processed = True
            article_obj.ai_type = next_type
            article_obj.save()

            # Lấy lại config object trong transaction
            config_obj = JobConfig.objects.get(id=config.id)
            config_obj.last_type_sent = next_type
            config_obj.save()

    await sync_to_async(update_article_and_config)()

# === Celery task ===
@shared_task
def process_openrouter_job():
    logger.info('[Celery Beat] Triggering async OpenRouter job')
    async_to_sync(_process_openrouter_async)()