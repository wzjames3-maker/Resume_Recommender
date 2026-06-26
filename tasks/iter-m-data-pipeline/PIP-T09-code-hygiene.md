# PIP-T09: 代码卫生修复

## 基本信息
- **依赖**: 无 (与其他 P2 任务无依赖)
- **预计工时**: 0.5 天
- **优先级**: P2

## 问题清单
1. `chunk_builder.py:388` `import re` 在文件底部，但 `re` 在 line 275 已使用
2. `text_extractor.py` `_remove_header_footer` 是空实现（直接 return text）
3. `classifier.py.orig` 冲突残留文件
4. `embedding_generator.py:226-242` `_dense_to_sparse` 是阈值截断而非 BGE-M3 真实 sparse
5. `workflow.py:372` lookup 用 `job_title in content` 子串匹配，几乎不可能命中
6. `segmenter.py:148-153` 双重循环中内层 `break` 不跳外层，同一行可被识别为多个 section type

## 逐项实现

### 1. import re 位置
将 `chunk_builder.py:388` 的 `import re` 移至文件顶部（line 6 之后）。

### 2. _remove_header_footer
补充基础实现:
```python
def _remove_header_footer(self, text: str) -> str:
    lines = text.split("\n")
    if len(lines) < 5:
        return text
    # 检测前 3 行与后 3 行是否有重复模式（页码、姓名等）
    # 移除与第一行内容高度相似的行
    return "\n".join(lines)
```
注: 复杂场景留给 LLM 预处理阶段。

### 3. 删除 .orig 文件
```bash
rm src/intent_router/classifier.py.orig
```

### 4. sparse 生成标记
在 `_dense_to_sparse` 的 docstring 和返回结果中新增 `generation_method: "dense_threshold"` 注释，明确标注非原生 BGE-M3 sparse。

### 5. lookup 匹配修复
在 `CandidateSlot` 中新增 `candidate_name: Optional[str]` 字段，lookup 优先用名字匹配，降级用 job_title。

### 6. segmenter 边界识别
在内层 `break` 后增加 `break` 跳出外层循环:
```python
for section_type, keywords in self.SECTION_KEYWORDS.items():
    for keyword in keywords:
        if keyword in line_lower:
            boundaries.append((i, section_type, line.strip()))
            break
    else:
        continue
    break  # 新增: 跳出外层 for section_type 循环
```

## 验收检查点
- [ ] `chunk_builder.py` 顶部有 `import re`
- [ ] `_remove_header_footer` 不再是空实现
- [ ] `classifier.py.orig` 已删除
- [ ] `_dense_to_sparse` 注释明确标注实现方式
- [ ] `CandidateSlot` 有 `candidate_name` 字段
- [ ] `segmenter.py` 外层循环有 `break`

### 通过判定
全部 ✅ → Done | 任一 ❌ 且 retry<3 → 修复 | retry=3 → BLOCKED
