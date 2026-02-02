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

from .poe_client import call_poe, filter_thinking_content, reset_poe_limiter

from .llm_client import (
    call_llm,
    get_current_model,
    get_available_models,
    set_model,
    accumulate_poe_points,
    get_poe_points,
    reset_poe_points
)

from .keyword_extractor import (
    normalize_source,
    get_source_dir,
    get_cached_keywords,
    store_keywords,
    compute_and_store_keywords,
    clear_article_cache,
    get_relevant_reference_blocks,
    keywords_cache,
    keywords_cache_lock
)

from .article_generator import (
    background_generate_articles,
    article_generation_progress,
    generated_prompts,
    generate_single_article_with_seo
)

from .dataforseo_client import (
    DataForSEOClient,
    dataforseo_client
)

from .serp_scraper import (
    scrape_url,
    scrape_serp_urls,
    extract_main_content,
    summarize_content
)

from .seo_orchestrator import (
    analyze_keyword_full,
    prepare_seo_context_for_prompt,
    get_seo_analysis_progress,
    seo_analysis_progress
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
    # Poe Client
    'call_poe',
    'filter_thinking_content',
    'reset_poe_limiter',
    # LLM Client
    'call_llm',
    'get_current_model',
    'get_available_models',
    'set_model',
    'accumulate_poe_points',
    'get_poe_points',
    'reset_poe_points',
    'normalize_source',
    'get_source_dir',
    'get_cached_keywords',
    'store_keywords',
    'compute_and_store_keywords',
    'clear_article_cache',
    'get_relevant_reference_blocks',
    'keywords_cache',
    'keywords_cache_lock',
    'background_generate_articles',
    'article_generation_progress',
    'generated_prompts',
    'generate_single_article_with_seo',
    # DataForSEO
    'DataForSEOClient',
    'dataforseo_client',
    # SERP Scraper
    'scrape_url',
    'scrape_serp_urls',
    'extract_main_content',
    'summarize_content',
    # SEO Orchestrator
    'analyze_keyword_full',
    'prepare_seo_context_for_prompt',
    'get_seo_analysis_progress',
    'seo_analysis_progress'
]
