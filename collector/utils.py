from typing import Optional
from .models import SystemConfig, Team
from django.core.cache import cache
import logging
from django.core.cache import cache
from .models import SystemConfig

logger = logging.getLogger(__name__)

from asgiref.sync import sync_to_async

async def get_system_config_async(key: str, team: Optional[str] = None, cache_timeout: int = 300) -> Optional[str]:
    """Async version of get_system_config"""
    cache_key = f"system_config:{key}:{team}" if team else f"system_config:{key}"
    
    # Try cache first
    value = cache.get(cache_key)
    if value is not None:
        return value
        
    # If not in cache, query from database
    try:
        query = SystemConfig.objects.filter(key=key, is_active=True)
        if team:
            query = query.filter(team=team)
        
        config = await sync_to_async(query.first)()
        if config:
            value = config.value.strip() if config.value else ''
            cache.set(cache_key, value, cache_timeout)
            return value
            
    except Exception as e:
        logger.error(f"Error getting system config {key}: {e}")
    
    return None

def get_system_config(key: str, team: Optional[str] = None, cache_timeout: int = 300) -> Optional[str]:
    """
    Lấy giá trị cấu hình từ SystemConfig model.
    Có cache để tránh query database quá nhiều.
    
    Args:
        key: Khóa cấu hình cần lấy
        team: Team cụ thể (nếu có)
        cache_timeout: Thời gian cache (giây)
    """
    cache_key = f"system_config:{key}:{team}" if team else f"system_config:{key}"
    
    # Thử lấy từ cache trước
    value = cache.get(cache_key)
    if value is not None:
        return value
        
    # Nếu không có trong cache, query từ database
    try:
        query = SystemConfig.objects.filter(key=key, is_active=True)
        if team:
            query = query.filter(team=team)
        
        config = query.first()
        if config:            # Strip whitespace from value to avoid auth issues
            value = config.value.strip() if config.value else ''
            cache.set(cache_key, value, cache_timeout)
            return value
            
    except Exception as e:
        logger.error(f"Error getting system config {key}: {e}")
    
    return None

def get_config_value(key: str, team: str = None) -> str:
    """
    Lấy giá trị cấu hình từ cache hoặc database
    """
    cache_key = f"system_config:{key}:{team}" if team else f"system_config:{key}"
    value = cache.get(cache_key)
    
    if value is None:
        try:
            query = SystemConfig.objects.filter(key=key, is_active=True)
            if team:
                query = query.filter(team=team)
            config = query.first()
            value = config.value if config else None
            # Cache giá trị trong 5 phút
            cache.set(cache_key, value, 300)
        except Exception as e:
            logger.error(f"Error getting config {key}: {e}")
            return None
            
    return value

def get_teams_webhook(team_code: str) -> str:
    """
    Lấy Teams webhook URL cho một team cụ thể
    """
    try:
        # Tìm team theo id thay vì code
        team = Team.objects.get(code=team_code, is_active=True)
        # Lấy webhook URL cho team đó
        config = SystemConfig.objects.filter(
            key='teams_webhook',
            team=team,
            is_active=True
        ).first()
        return config.value if config else None
    except Team.DoesNotExist:
        logger.error(f"Team with id {team_code} not found")
        return None
    except Exception as e:
        logger.error(f"Error getting teams webhook: {str(e)}")
        return None

async def get_teams_webhook_async(team_code: str) -> str:
    """
    Lấy Teams webhook URL cho một team cụ thể (async version)
    """
    try:
        # Tìm team theo id thay vì code
        team = await sync_to_async(Team.objects.get)(code=team_code, is_active=True)
        # Lấy webhook URL cho team đó
        # Sử dụng sync_to_async để chạy toàn bộ truy vấn đồng bộ trong async context
        config = await sync_to_async(lambda: SystemConfig.objects.filter(
            key='teams_webhook',
            team=team,
            is_active=True
        ).first())()
        return config.value if config else None
    except Team.DoesNotExist:
        logger.error(f"Team with code {team_code} not found") # Sửa lại log cho chính xác
        return None
    except Exception as e:
        logger.error(f"Error getting teams webhook: {str(e)}")
        return None

async def get_openrouter_api_key_async() -> str:
    """Get OpenRouter API key from system config (async version)"""
    key = await get_system_config_async('openrouter_api_key')
    if not key:
        logger.error("OpenRouter API key not configured")
        return ""
    
    key = key.strip()  # Remove any whitespace
    if not key.startswith('sk-or-'):
        logger.error(f"Invalid OpenRouter API key format: {key[:10]}...")
        return ""
        
    return key

def get_openrouter_api_key() -> str:
    """Get OpenRouter API key from system config (sync version)"""
    key = get_system_config('openrouter_api_key')
    if not key:
        logger.error("OpenRouter API key not configured")
        return ""
    
    key = key.strip()  # Remove any whitespace
    if not key.startswith('sk-or-'):
        logger.error(f"Invalid OpenRouter API key format: {key[:10]}...")
        return ""
        
    return key
