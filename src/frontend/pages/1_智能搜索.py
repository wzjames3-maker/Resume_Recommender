"""
智能招聘 RAG 推荐系统 - 智能搜索页面 v2.0

主聊天界面 + 候选人卡片 + 多轮对话 + 筛选器 + 对比 + 导出
"""

import streamlit as st
from src.frontend.api_client import send_chat_message, export_candidates_excel
from src.frontend.components import render_filter_sidebar

st.set_page_config(page_title="智能搜索", page_icon="💬", layout="wide")


def render_candidate_card(candidate, index):
    """渲染候选人卡片（v2.0 增强版：增加对比勾选 + 详情跳转）"""
    meta = candidate.get("metadata", {})
    reason = candidate.get("reason", {})
    resume_id = candidate.get("resume_id", "Unknown")
    name = meta.get("name", f"候选人 {resume_id[:8]}")
    score = candidate.get("score", 0)

    with st.expander(f"👤 #{index + 1} {name}  |  匹配度: {score:.1%}", expanded=(index < 3)):
        col1, col2 = st.columns([2, 1])

        with col1:
            if reason.get("reason"):
                st.info(f"💡 {reason['reason']}")

            matched = reason.get("matched_skills", [])
            missing = reason.get("missing_skills", [])

            if matched or missing:
                mc1, mc2 = st.columns(2)
                with mc1:
                    if matched:
                        st.markdown("**✅ 匹配技能:**")
                        for s in matched:
                            st.markdown(f"- {s}")
                with mc2:
                    if missing:
                        st.markdown("**❌ 缺失技能:**")
                        for s in missing:
                            st.markdown(f"- {s}")

        with col2:
            breakdown = reason.get("score_breakdown", {})
            if breakdown:
                st.markdown("**📊 评分详情:**")
                labels = {
                    "semantic_score": "语义匹配",
                    "filter_score": "过滤得分",
                    "final_score": "综合得分",
                    "skill_match_score": "技能匹配",
                    "industry_match_score": "行业匹配",
                }
                for k, v in breakdown.items():
                    label = labels.get(k, k)
                    st.metric(label, f"{v:.3f}")

        content = candidate.get("content", "")
        if content:
            with st.expander("📝 原始内容片段"):
                st.text(content[:500])

        # v2.0: 操作按钮行
        st.markdown("---")
        col_a, col_b, col_c = st.columns([2, 1, 1])
        with col_a:
            # Compare checkbox
            if "compare_candidates" not in st.session_state:
                st.session_state.compare_candidates = []
            is_compared = resume_id in st.session_state.compare_candidates
            if st.checkbox("📊 加入对比", value=is_compared, key=f"compare_{resume_id}_{index}"):
                if resume_id not in st.session_state.compare_candidates:
                    if len(st.session_state.compare_candidates) < 5:
                        st.session_state.compare_candidates.append(resume_id)
                    else:
                        st.warning("⚠️ 最多对比 5 位候选人")
            else:
                if resume_id in st.session_state.compare_candidates:
                    st.session_state.compare_candidates.remove(resume_id)
        with col_b:
            if st.button("📋 详情", key=f"detail_{resume_id}_{index}", use_container_width=True):
                st.session_state.current_resume_id = resume_id
                st.switch_page("pages/6_简历详情.py")


def init_state():
    if "messages" not in st.session_state:
        st.session_state.messages = []
    if "conversation_id" not in st.session_state:
        st.session_state.conversation_id = None
    if "last_candidates" not in st.session_state:
        st.session_state.last_candidates = []
    if "compare_candidates" not in st.session_state:
        st.session_state.compare_candidates = []
    if "search_filters" not in st.session_state:
        st.session_state.search_filters = {}
    if "sort_by" not in st.session_state:
        st.session_state.sort_by = "匹配度"


def main():
    init_state()

    if not st.session_state.get("token"):
        st.warning("⚠️ 请先登录")
        st.stop()

    st.title("💬 智能招聘搜索")
    st.caption("输入自然语言描述您的招聘需求，AI 将为您智能匹配候选人")

    # ===== 侧边栏 =====
    with st.sidebar:
        st.markdown(f"**👤 用户:** {st.session_state.get('user_id', '-')}")
        st.markdown(f"**🏷️ 角色:** {st.session_state.get('role', '-')}")

        if st.button("🆕 新建对话", use_container_width=True):
            st.session_state.conversation_id = None
            st.session_state.messages = []
            st.session_state.last_candidates = []
            st.session_state.compare_candidates = []
            st.session_state.search_filters = {}
            st.rerun()

        # v2.0: 高级筛选器
        render_filter_sidebar()

        st.markdown("---")
        st.markdown("**💡 搜索示例:**")
        examples = [
            "找3年经验的Java开发工程师",
            "有腾讯工作经验的前端工程师",
            "清华毕业的AI算法工程师",
            "会Docker和K8s的DevOps运维",
            "5年以上Go语言后端开发",
            "有B端经验的产品经理",
        ]
        for ex in examples:
            if st.button(f"📝 {ex}", key=f"ex_{ex}", use_container_width=True):
                st.session_state.messages.append({"role": "user", "content": ex})
                st.rerun()

        # v2.0: 对比快捷入口
        if st.session_state.compare_candidates:
            st.markdown("---")
            n_cmp = len(st.session_state.compare_candidates)
            st.markdown(f"📊 已选 **{n_cmp}** 位候选人")
            if st.button("→ 前往对比页", use_container_width=True, type="primary"):
                st.switch_page("pages/7_候选人对比.py")

        if st.session_state.last_candidates:
            st.markdown("---")
            st.markdown(f"**📊 上次结果:** {len(st.session_state.last_candidates)} 位候选人")
            scores = [c.get("score", 0) for c in st.session_state.last_candidates]
            if scores:
                avg_score = sum(scores) / len(scores)
                st.metric("平均匹配度", f"{avg_score:.1%}")

    # ===== 排序 + 导出工具栏 =====
    if st.session_state.last_candidates:
        col1, col2, col3, col4 = st.columns([2, 1, 1, 1])
        with col1:
            sort_options = ["匹配度", "经验", "学历"]
            st.session_state.sort_by = st.radio(
                "排序方式", sort_options, horizontal=True,
                index=sort_options.index(st.session_state.sort_by) if st.session_state.sort_by in sort_options else 0
            )
        with col3:
            if st.session_state.compare_candidates:
                st.page_link("pages/7_候选人对比.py", label="📊 候选人对比")
        with col4:
            if st.session_state.last_candidates:
                xlsx = export_candidates_excel(st.session_state.last_candidates)
                if xlsx:
                    st.download_button(
                        "📥 导出结果", xlsx, "搜索结果.xlsx",
                        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                        use_container_width=True,
                    )

    # ===== 显示历史消息 =====
    for msg in st.session_state.messages:
        with st.chat_message(msg["role"]):
            st.markdown(msg["content"])
            if msg.get("candidates"):
                st.markdown("---")
                candidates = msg["candidates"]

                # Apply sort
                if st.session_state.sort_by == "经验":
                    candidates = sorted(candidates, key=lambda c: c.get("metadata", {}).get("total_experience", 0) or 0, reverse=True)
                elif st.session_state.sort_by == "学历":
                    edu_order = {"博士": 5, "硕士": 4, "本科": 3, "大专": 2, "不限": 1}
                    candidates = sorted(candidates, key=lambda c: edu_order.get(c.get("metadata", {}).get("highest_education", "不限"), 0), reverse=True)
                else:
                    candidates = sorted(candidates, key=lambda c: c.get("score", 0), reverse=True)

                st.markdown(f"### 📋 推荐候选人（{len(candidates)} 位）")
                for i, c in enumerate(candidates):
                    render_candidate_card(c, i)

    # ===== 用户输入 =====
    if prompt := st.chat_input("描述您的招聘需求，如：找5年Java工程师，杭州，985"):
        # Build search context from filters
        filters = st.session_state.get("search_filters", {})
        filter_hints = []
        if filters.get("city"):
            c = filters["city"]
            if isinstance(c, list) and c:
                filter_hints.append(f"城市: {', '.join(c)}")
            elif isinstance(c, str) and c.strip():
                filter_hints.append(f"城市: {c}")
        if filters.get("education") and filters["education"] != "不限":
            filter_hints.append(f"学历: {filters['education']}")
        if filters.get("min_experience", 0) > 0:
            filter_hints.append(f"经验 >= {filters['min_experience']}年")
        if filters.get("skill"):
            s = filters["skill"]
            if isinstance(s, list) and s:
                filter_hints.append(f"技能: {', '.join(s)}")
            elif isinstance(s, str) and s.strip():
                filter_hints.append(f"技能: {s}")
        if filters.get("is_985"):
            filter_hints.append("985院校")
        if filters.get("is_211"):
            filter_hints.append("211院校")

        full_prompt = prompt
        if filter_hints:
            full_prompt = prompt + "（筛选条件：" + "，".join(filter_hints) + "）"

        st.session_state.messages.append({"role": "user", "content": prompt})
        with st.chat_message("user"):
            st.markdown(prompt)
            if filter_hints:
                st.caption("🔍 " + " | ".join(filter_hints))

        with st.chat_message("assistant"):
            with st.spinner("🔍 正在搜索候选人..."):
                result = send_chat_message(full_prompt, st.session_state.conversation_id)

            if result:
                st.markdown(result["message"])

                if result.get("session_id"):
                    st.session_state.conversation_id = result["session_id"]

                candidates = result.get("candidates", [])
                if candidates:
                    st.session_state.last_candidates = candidates

                    # Apply sort
                    if st.session_state.sort_by == "经验":
                        candidates = sorted(candidates, key=lambda c: c.get("metadata", {}).get("total_experience", 0) or 0, reverse=True)
                    elif st.session_state.sort_by == "学历":
                        edu_order = {"博士": 5, "硕士": 4, "本科": 3, "大专": 2, "不限": 1}
                        candidates = sorted(candidates, key=lambda c: edu_order.get(c.get("metadata", {}).get("highest_education", "不限"), 0), reverse=True)
                    else:
                        candidates = sorted(candidates, key=lambda c: c.get("score", 0), reverse=True)

                    st.markdown("---")
                    st.markdown(f"### 📋 推荐候选人（{len(candidates)} 位）")
                    for i, c in enumerate(candidates):
                        render_candidate_card(c, i)

                st.session_state.messages.append({
                    "role": "assistant",
                    "content": result["message"],
                    "candidates": candidates,
                })
            else:
                st.error("❌ 获取响应失败，请重试")


if __name__ == "__main__":
    main()