"""Canonical KPI names for RunMetric rows, API payloads, and Langfuse scores.

Canonical names for observability KPIs (Langfuse scores + RunMetric rows).
"""

from __future__ import annotations

# --- RunMetric.metric_name (per_query or aggregate) ---

# Information retrieval (existing Recall@5 kept as-is for IR compatibility)
IR_RECALL_AT_5 = "Recall@5"

# Efficiency / cost / latency
EFF_INPUT_TOKENS = "efficiency/input_tokens"
EFF_OUTPUT_TOKENS = "efficiency/output_tokens"
EFF_TOTAL_TOKENS = "efficiency/total_tokens"
EFF_RAGAS_ESTIMATED_TOKENS = "efficiency/ragas_estimated_tokens"

COST_INPUT_USD = "cost/input_usd"
COST_OUTPUT_USD = "cost/output_usd"
COST_TOTAL_USD = "cost/total_usd"
COST_RAGAS_ESTIMATED_USD = "cost/ragas_estimated_usd"
COST_ANSWER_TOTAL_USD = "cost/answer_total_usd"

# Answer-generation token breakdown (phase 2)
EFF_ANSWER_INPUT_TOKENS = "efficiency/answer_input_tokens"
EFF_ANSWER_OUTPUT_TOKENS = "efficiency/answer_output_tokens"

LATENCY_SEARCH_MS = "latency/search_ms"
LATENCY_LLM_MS = "latency/llm_ms"

# Run-level rollups (aggregate scope)
SUMMARY_TOTAL_TOKENS = "summary/total_tokens"
SUMMARY_COST_TOTAL_USD = "summary/cost_total_usd"
SUMMARY_QUALITY_SCORE = "summary/quality_score"  # mean Recall@5 when present

# --- EvalRun.params_json keys for Langfuse ---
PJ_LANGFUSE_TRACE_ID = "langfuse_trace_id"
PJ_LANGFUSE_HOST = "langfuse_host"
PJ_LANGFUSE_TRACE_URL = "langfuse_trace_url"
PJ_LANGFUSE_SYNC_ERROR = "langfuse_sync_error"
PJ_LANGFUSE_POST_EVAL_ERROR = "langfuse_post_eval_error"

# --- Error taxonomy (params_json or details_json) ---
ERR_SEARCH_FAILED = "search_failed"
ERR_RAGAS_FAILED = "ragas_failed"
ERR_LLM_FAILED = "llm_failed"
ERR_LANGFUSE_SYNC_FAILED = "langfuse_sync_failed"
