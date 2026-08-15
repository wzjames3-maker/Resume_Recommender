# 外部模型接入与简历语义检索试点设计（C 阶段试点）

- 日期：2026-08-15
- 状态：已执行（审计见 audits/2026-08-15-external-model-pilot.md）
- 关联：PRD §6（AI 边界）、§9.2（C 阶段）、models_provider 模型注册

## 1. 目标

利用测试材料（飞桨「简历信息抽取数据」+ SenseNova LLM + SiliconFlow Embedding/Reranker），
在本机部署式环境验证外部模型全链路：模型接入 → 简历语料向量化 → 语义召回 → 重排 → LLM 问答，
并给出 PRD §9.2 C 阶段要求的 Top-K 相关性证据。

## 2. 外部模型接入

精简内核只保留 OpenAI 兼容 Provider（`model_openai_provider`），凭据为 `api_base` + `api_key`。
新增注册（`apps/models_provider/impl/openai_model_provider/openai_model_provider.py`）：

| 模型 | 类型 | 端点 | 凭据类 | 模型类 |
|---|---|---|---|---|
| sensenova-6.8-flash-lite | LLM | https://token.sensenova.cn/v1 | OpenAILLMModelCredential | OpenAIChatModel |
| BAAI/bge-large-zh-v1.5 | EMBEDDING | https://api.siliconflow.cn/v1 | OpenAIEmbeddingCredential | OpenAIEmbeddingModel |
| BAAI/bge-reranker-v2-m3 | RERANKER | https://api.siliconflow.cn/v1 | OpenAIRerankCredential（新增） | OpenAIRerankModel（新增） |

### RERANKER 补齐（裁剪前为空壳）

- `OpenAIRerankModel`：POST `{api_base}/rerank`，请求 `{model, query, documents, top_n}`，
  解析 `results[]` 按 `relevance_score` 降序返回 `[{index, relevance_score}]`。
- `OpenAIRerankCredential`：`api_base`/`api_key` 必填；`is_valid` 用最小 rerank 调用做连通性校验；
  `top_n` 参数表单（默认 3）。`tools.py` 已预留 RERANKER top_n 默认值。
- UI 已支持 RERANKER 类型展示（`allow-create` 自由输入模型名），注册后下拉可选。

### 兼容性注意（实测）

- SiliconFlow Embedding 不接受 `dimensions` 参数（OpenAI 兼容差异），bge-large-zh-v1.5 固定 1024 维；
  模型参数表单留空即可，pgvector 列无维度约束。
- SenseNova 端点走标准 OpenAI chat completions，无特殊参数。

## 3. 试点语料与标注

- 数据源：`数据集/train.json`（天池「简历信息抽取」2000 份脱敏人工构造简历的 18 字段标注）。
- 语料生成：`installer/real_model_smoke.py` 抽样转 txt（**剥离电话字段**，对齐 PRD §6
  "默认不发送候选人联系方式"），输出 `testdata/generated/resumes/`（gitignored）。
- 缺失时回退合成语料（同名脚本内置模板）。
- 标注查询：实体查询（毕业院校→期望简历）用于 recall@5 对比；自然语言查询（无固定期望）用于定性评估。

## 4. 渐进档位（时间与调用控制）

| 档位 | 简历数 | 查询数 | 预计 embedding 调用 | 用途 |
|---|---|---|---|---|
| 1 | 5 | 3 实体 | ~30 | 链路冒烟 |
| 2 | 30 | 8 实体 + 3 自然语言 | ~250 | 规模验证 + 评估 |
| 3 | 200 | 15 | ~1500 | 可选，本次未跑（预算控制） |

幂等：模型/知识库按名复用；文档按名跳过；FAILURE 文档重触发且跳过 celery-once AlreadyQueued。

## 5. 评估口径

- 实体查询：recall@5 = 期望文档出现在命中测试 top5 的比例；对照结构化检索基线（`毕业院校` 精确匹配，预期 100%）。
- 自然语言查询：人工判断 top5 相关性。
- 重排：记录 rerank 输出索引与分数，与纯 embedding 排序对比（定性）。
- 问答：回答非空 + ChatRecord.search_step 引用数 > 0（精简内核 chat 响应不含 citation_list，
  引用信息从对话记录详情读取）。

## 6. 密钥与安全

- 凭据只走环境变量（`SENSENOVA_API_KEY`/`SILICONFLOW_API_KEY`），不入库不入提交；
  `.env.example` 提供占位说明。
- 语料已脱敏（数据集声明 CC0、人工构造），且剥离电话字段。
