#!/bin/bash
# 简历 RAG v2 生产落地脚本（2026-08-16）
# 用途：真实环境一次性落地——迁移 → 技能回填 → Termbase 词条 → 全量重嵌（含确认）。
# 前置：MAXKB_* 环境变量已导出（见 HANDOFF §1.1）；DB/Redis 可达。
# 用法：bash installer/production_landing.sh [--workspace=ws_id] [--dry-run]
set -euo pipefail

WORKSPACE=""
DRY=""
for arg in "$@"; do
  case "$arg" in
    --workspace=*) WORKSPACE="${arg#*=}" ;;
    --dry-run) DRY="1" ;;
  esac
done

PY=".venv/bin/python"
WS_ARGS=""
[ -n "$WORKSPACE" ] && WS_ARGS="--workspace $WORKSPACE"

echo "==> [1/4] 应用数据库迁移（幂等）"
$PY manage.py migrate  # 标准路径；apps/manage.py 仍为兼容 shim
$PY manage.py makemigrations --check --dry-run || echo "警告：存在未生成的迁移"

echo "==> [2/4] candidate_skill 技能回填（幂等，可重复跑）"
$PY manage.py backfill_candidate_skills $WS_ARGS

echo "==> [3/4] Termbase 技能词条（幂等）"
$PY manage.py seed_resume_termbase $WS_ARGS

echo "==> [4/4] 全量重嵌（title 前缀 chunks + 词条分词一次生效）"
if [ -n "$DRY" ]; then
$PY manage.py reindex_resume_knowledge $WS_ARGS --dry-run
  echo "（--dry-run：仅预览文档数。确认后去掉该参数重跑）"
else
  echo "即将重嵌全部简历文档；重嵌窗口检索降级为 seq scan（不失败），建议低峰执行。3 秒后可 Ctrl-C 取消。"
  sleep 3
$PY manage.py reindex_resume_knowledge $WS_ARGS
fi

echo
echo "==> 落地完成。后续评测（需 SENSENOVA_API_KEY）："
echo "  SENSENOVA_API_KEY=... .venv/bin/python installer/resume_splitter_dataset30.py"
echo "  SENSENOVA_API_KEY=... .venv/bin/python installer/resume_search_eval.py --typed 30"
echo "  回填后 skills 字段有真实数据时，T5 结构化路与 T7 技能预筛才真正生效。"
