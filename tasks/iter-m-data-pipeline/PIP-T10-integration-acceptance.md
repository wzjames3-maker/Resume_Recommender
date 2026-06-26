# PIP-T10: 集成验收 + Spec 基线冻结

## 基本信息
- **依赖**: PIP-T01 ~ T09
- **预计工时**: 0.5 天
- **优先级**: P0

## 集成验收流程

### 1. 端到端上传→索引→搜索验证
```bash
# 1. 上传一份测试简历
curl -X POST http://localhost:8000/api/v1/resumes/upload \
  -H "Authorization: Bearer $TOKEN" \
  -F "file=@test_resumes/zhangsan.json"

# 2. 确认向量写入日志
# 日志应包含: "向量索引写入完成" "chunks=N"

# 3. 执行搜索
curl -X POST http://localhost:8000/api/v1/chat \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"message": "帮我找Java开发"}'

# 4. 确认返回候选人结果（非空！）
```

### 2. 验证项清单
| # | 验证项 | 方法 |
|---|--------|------|
| 1 | API 上传后 Milvus 有数据 | `python -c "from src.vector_index import get_vector_index; ..."` |
| 2 | 搜索返回候选人结果 | Chat API 响应含 candidates 列表 |
| 3 | Small→Big 返回完整 Section | 搜索结果 content 长度 > 200 字符 |
| 4 | Session TTL 30min 过期 | 构造过期 session 调用 chat → 返回新 session_id |
| 5 | last_intent 在上下文传递 | 日志含 "对话上下文：轮次=X, 上次意图=recruitment.search" |
| 6 | refine NARROW 生效 | 连续两次 refine → 日志含 "在上次结果中检索" |
| 7 | project_list 入库 | 获取简历详情 → response 含 project_list |
| 8 | llm_extractor regex 正常 | 用带换行的 LLM 响应测试 JSON 提取 |
| 9 | 无 IntentRouter Handler 残留 | `rg "SearchHandler\|RefineHandler\|LookupHandler" src/` 仅返回 chat.py 的映射表 |
| 10 | 全量测试通过 | `python -m pytest tests/ -x -q` |

### 3. Spec 基线冻结
更新各模块 `06-acceptance.md` 文件，将本次修复的验收标准写入:
- `specs/resume-parser/06-acceptance.md` 追加 AC-REQ-012
- `specs/vector-index/06-acceptance.md` 更新 AC-002/AC-006/AC-007
- `specs/conversation-memory/06-acceptance.md` 追加 AC-REQ-008/009
- `specs/recommendation-engine/06-acceptance.md` 更新 AC-010/AC-011

### 4. Git 归档
```bash
git checkout -b iter/m-data-pipeline
git add -A
git commit -m "iter/m-data-pipeline: fix upload-index chain, session TTL, Small→Big, dead code"
```

## 验收检查点
- [ ] 端到端上传→搜索返回非空结果
- [ ] 10 项验证清单全部通过
- [ ] `CHANGELOG.md` 更新本次迭代记录
- [ ] 所有 06-acceptance.md 已更新
- [ ] 分支 `iter/m-data-pipeline` 已创建并提交

### 通过判定
全部 ✅ → Done | 任一 ❌ 且 retry<3 → 修复 | retry=3 → BLOCKED
