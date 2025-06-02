import asyncio
from celery import shared_task
from django.utils import timezone
from .models import Source, Article, JobConfig, Team
from .fetchers import DataCollector, call_openrouter_ai
import logging
from django.db import transaction
from asgiref.sync import sync_to_async
from django.db.models import Q

logger = logging.getLogger(__name__)

@shared_task
def collect_data_from_source(source_id):
    try:
        source = Source.objects.get(id=source_id, is_active=True)
        collector = DataCollector()
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
        return {'success': False, 'error': f'Source with ID {source_id} not found or inactive'}
    except Exception as e:
        logger.error(f'Celery task failed for source {source_id}: {e}')
        return {'success': False, 'error': str(e)}

@shared_task
def collect_data_from_all_sources(team_code=None):
    logger.info('[Celery Beat] Đã gọi task collect_data_from_all_sources')
    try:
        collector = DataCollector()
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            results = loop.run_until_complete(collector.collect_all_active_sources(team_code=team_code))
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
        return {'success': False, 'error': str(e)}

@shared_task
def scheduled_collection():
    try:
        now = timezone.now()
        sources_due = Source.objects.filter(is_active=True).extra(
            where=['last_fetched IS NULL OR (EXTRACT(EPOCH FROM %s) - EXTRACT(EPOCH FROM last_fetched)) >= fetch_interval'],
            params=[now]
        )
        if not sources_due.exists():
            return {'success': True, 'message': 'No sources due for update', 'sources_processed': 0}
        results = []
        for source in sources_due:
            result = collect_data_from_source.delay(source.id)
            results.append(result)
        return {'success': True, 'message': f'Triggered collection for {len(results)} sources', 'sources_processed': len(results)}
    except Exception as e:
        logger.error(f'Scheduled collection task failed: {e}')
        return {'success': False, 'error': str(e)}

def update_article_and_config_sync(article_id, ai_content, ai_type, config_id):
    try:
        with transaction.atomic():
            article_obj = Article.objects.select_for_update().get(id=article_id)
            article_obj.ai_content = ai_content
            article_obj.is_ai_processed = True
            article_obj.ai_type = ai_type
            article_obj.save()

            config_obj = JobConfig.objects.select_for_update().get(id=config_id)
            config_obj.last_type_sent = ai_type
            config_obj.save()
            return True
    except Exception as e:
        logger.error(f"Error updating article and config: {e}")
        return False

@shared_task
def process_openrouter_job(team_code=None):
    logger.info('[Celery Beat] Đã gọi task process_openrouter_job')
    try:
        # Kiểm tra job config
        config = JobConfig.objects.filter(job_type='openrouter').first()
        if not config or not config.enabled:
            logger.info("OpenRouter job is disabled")
            return {'success': True, 'result': None}

        # Lấy bài viết chưa xử lý
        query = Article.objects.filter(is_ai_processed=False)
        if team_code:
            query = query.filter(source__team__code=team_code)
        article = query.order_by('published_at').first()

        if not article:
            logger.info("No article to process")
            return {'success': True, 'result': None}

        # Lấy team code
        real_team_code = None
        if article.source and article.source.team:
            real_team_code = article.source.team.code
        logger.info(f"Step 3: Team code = {real_team_code}")

        # Tạo event loop cho các thao tác async
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            # Gọi AI
            logger.info("Step 4: Gọi call_openrouter_ai")
            ai_content = loop.run_until_complete(
                call_openrouter_ai(article.content, article.url, ai_type=real_team_code)
            )

            # Lấy webhook
            logger.info("Step 5: Lấy webhook")
            from .utils import get_teams_webhook_async
            teams_webhook = loop.run_until_complete(
                get_teams_webhook_async(real_team_code)
            )

            if teams_webhook:
                logger.info("Step 6: Gửi notify teams")
                from .fetchers import notify_teams
                loop.run_until_complete(
                    notify_teams(teams_webhook, f"Bài viết mới cho team {real_team_code}", ai_content, article.url)
                )
            else:
                logger.warning(f"No Teams webhook found for team {real_team_code}")

        except Exception as e:
            logger.error(f"Error in async operations: {e}")
            raise
        finally:
            # Đóng event loop
            try:
                loop.close()
            except Exception as e:
                logger.error(f"Error closing event loop: {e}")

        # Cập nhật bài viết và config (synchronous)
        logger.info("Step 7: Cập nhật bài viết và config")
        try:
            with transaction.atomic():
                article_obj = Article.objects.select_for_update().get(id=article.id)
                article_obj.ai_content = ai_content
                article_obj.is_ai_processed = True
                article_obj.ai_type = real_team_code
                article_obj.save()

                config_obj = JobConfig.objects.select_for_update().get(id=config.id)
                config_obj.last_type_sent = real_team_code
                config_obj.save()
        except Exception as e:
            logger.error(f"Error updating article and config: {e}")
            return {'success': False, 'error': str(e)}

        logger.info("Step 8: Hoàn thành xử lý")
        return {'success': True, 'result': True}

    except Exception as e:
        logger.error(f"Celery task failed for OpenRouter job: {e}")
        return {'success': False, 'error': str(e)}