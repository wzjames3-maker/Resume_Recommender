*** Begin Patch
*** Update File: C:\Users\Administrator\Desktop\简历推荐系统\specs\resume-parser\00-overview.md
@@ 语义段落切分 @@
-| 语义段落切分 | 按教育/工作/项目/技能等语义维度切分简历段落，保留 Metadata |
+| 语义段落切分 | 按教育/工作/项目/技能等语义维度切分为 Section（Parent Chunk），再细分为 Small Chunk（单句级），保留层级关系和 Metadata |
@@ ## 7. 数据流 @@
-输入文件 ──> 格式识别 ──> 文本提取 ──> 语义切分 ──> LLM 结构化提取 ──> Skill 标准化 ──> Resume 实体
-  │              │            │            │              │                │
-  │              │            │            │              │                │
-  ▼              ▼            ▼            ▼              ▼                ▼
- PDF           PDF/DOCX    纯文本       段落列表      结构化 JSON      最终 Resume
- DOCX          /Image      + 元数据     (教育/工作/   (Pydantic)       Schema
- Image         判定         + 语言      项目/技能)
- JSON ──────────────────────────────────────────────────────────────────> 直接映射
+输入文件 ──> 格式识别 ──> 文本提取 ──> 语义切分 ──> LLM 结构化提取 ──> Skill 标准化 ──> Resume 实体
+                                         │
+                                         ├── Section (Parent Chunk)
+                                         │     └── Small Chunk (单句级)
+                                         └── Full Resume (整份简历)
*** End Patch
