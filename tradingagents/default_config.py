import os

DEFAULT_CONFIG = {
    "project_dir": os.path.abspath(os.path.join(os.path.dirname(__file__), ".")),
    "results_dir": os.getenv("TRADINGAGENTS_RESULTS_DIR", "./results"),
    "data_cache_dir": os.path.join(
        os.path.abspath(os.path.join(os.path.dirname(__file__), ".")),
        "dataflows/data_cache",
    ),
    "tushare_token": None,
    "bailian_api_key": None,
    "mx_api_key": None,
    "trace_enabled": True,
    "trace_project_name": "TradingAgents",
    "trace_artifact_dir": os.getenv("TRADINGAGENTS_TRACE_ARTIFACT_DIR"),
    "trace_db_path": os.getenv("TRADINGAGENTS_TRACE_DB_PATH"),
    "langsmith_enabled": False,
    "langsmith_project_name": "TradingAgents",
    "langsmith_api_key": None,
    "langsmith_endpoint": None,
    "otel_enabled": False,
    "bailian_enable_thinking": False,
    "bailian_thinking_budget": None,
    "event_query_planner_enable_thinking": True,
    "event_query_planner_thinking_budget": 2048,
    "agent_timeout_seconds": 180,
    "agent_retry_max_attempts": 2,
    "agent_timeout_recovery_grace_seconds": 60,
    "fundamental_report_periods": 8,
    "fundamental_report_periods_by_type": {
        "cyclical_resources": 12,
    },
    # LLM settings
    "llm_provider": "bailian",
    "deep_think_llm": "qwen3.5-397b-a17b",
    "quick_think_llm": "qwen3.5-flash",
    "backend_url": "https://dashscope.aliyuncs.com/compatible-mode/v1",
    # Provider-specific thinking configuration
    "google_thinking_level": None,      # "high", "minimal", etc.
    "openai_reasoning_effort": None,    # OpenAI only
    # Debate and discussion settings
    "max_debate_rounds": 1,
    "max_risk_discuss_rounds": 1,
    "max_recur_limit": 100,
    # Data vendor configuration
    # Category-level configuration (default for all tools in category)
    "data_vendors": {
        "core_stock_apis": "tushare",        # Options: alpha_vantage, tushare
        "technical_indicators": "tushare",   # Options: alpha_vantage, tushare
        "fundamental_data": "tushare",       # Options: alpha_vantage, tushare
    },
    # Tool-level configuration (takes precedence over category-level)
    "tool_vendors": {
        # Example: "get_stock_data": "alpha_vantage",  # Override category default
    },
}
