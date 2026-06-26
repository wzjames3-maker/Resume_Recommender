# Task Board — iter/m-data-pipeline-v2

| ID | Task | Priority | Status | Files |
|----|------|----------|--------|-------|
| PIP2-T01 | full_pipeline.py: 修复 ind_by_filename() + hybrid_search() 调用 | P0 | ✅ done | scripts/pipeline/full_pipeline.py, src/resume_store/repository.py |
| PIP2-T02 | index_manager.py: 修复 _get_collection_name() 调用 | P0 | ✅ done | src/vector_index/index_manager.py |
| PIP2-T03 | SkillEntry 字段映射修复（years→years_of_experience, level→proficiency） | P0 | ✅ done | src/resume_parser/llm_extractor.py |
| PIP2-T04 | MetadataFilter: 将 MongoDB enrichment 移到 filter 之前 | P0 | ✅ done | src/conversation_memory/workflow.py |
| PIP2-T05 | text_extractor.py + models.py: 修复 default_factory=datetime.now 不可调用 bug | P0 | ✅ done | src/resume_parser/text_extractor.py, src/resume_store/models.py |
| PIP2-T06 | _dense_to_sparse 标注（已从 v0.2.1 继承） | P1 | ✅ done | src/vector_index/embedding_generator.py |
| PIP2-T07 | segmenter 双匹配彻底修复（外层 break + 移除多余 break） | P1 | ✅ done | src/resume_parser/segmenter.py |
| PIP2-T08 | refine() NARROW 分支优化：resume_id 过滤推入 Milvus 表达式 | P1 | ✅ done | src/conversation_memory/workflow.py |
| PIP2-T09 | classifier 不可达代码：保留为安全网（不删除） | P2 | ✅ done | src/intent_router/classifier.py |
