"""服務層模組"""

from .database import (
    init_connection_pool,
    get_db_connection,
    return_db_connection,
    ensure_database_initialized,
    init_database,
    get_all_articles,
    get_articles_paginated,
    get_article_by_id,
    delete_article,
    batch_delete_articles,
    insert_article
)

from .deepseek_client import call_deepseek, reset_rate_limiter

from .keyword_extractor import (
    normalize_source,
    get_source_dir,
    get_cached_keywords,
    store_keywords,
    compute_and_store_keywords,
    get_relevant_reference_blocks,
    keywords_cache,
    keywords_cache_lock
)

from .article_generator import (
    background_generate_articles,
    article_generation_progress,
    generated_prompts
)

__all__ = [
    'init_connection_pool',
    'get_db_connection',
    'return_db_connection',
    'ensure_database_initialized',
    'init_database',
    'get_all_articles',
    'get_articles_paginated',
    'get_article_by_id',
    'delete_article',
    'batch_delete_articles',
    'insert_article',
    'call_deepseek',
    'reset_rate_limiter',
    'normalize_source',
    'get_source_dir',
    'get_cached_keywords',
    'store_keywords',
    'compute_and_store_keywords',
    'get_relevant_reference_blocks',
    'keywords_cache',
    'keywords_cache_lock',
    'background_generate_articles',
    'article_generation_progress',
    'generated_prompts'
]
