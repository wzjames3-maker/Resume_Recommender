"""
智能招聘 RAG 推荐系统 - 简历详情页

通过 st.query_params["id"] 获取简历ID，展示完整简历信息
"""

import streamlit as st
from src.frontend.api_client import get_resume, delete_resume_api
from src.frontend.components import render_resume_full

st.set_page_config(page_title="简历详情", page_icon="📋", layout="wide")


def main():
    if not st.session_state.get("token"):
        st.warning("⚠️ 请先登录")
        st.stop()

    # Get resume ID from query params or session state
    resume_id = st.query_params.get("id", None)
    if not resume_id:
        resume_id = st.session_state.get("current_resume_id", None)

    if not resume_id:
        st.error("❌ 未指定简历 ID")
        st.markdown("请从搜索页面或管理页面选择一份简历查看。")
        if st.button("← 返回搜索", use_container_width=True):
            st.switch_page("pages/1_智能搜索.py")
        st.stop()

    st.title("📋 简历详情")

    # Back button
    col1, col2 = st.columns([1, 5])
    with col1:
        if st.button("← 返回", use_container_width=True):
            st.switch_page("pages/1_智能搜索.py")

    # Fetch resume data
    doc = get_resume(resume_id)

    if not doc:
        st.error(f"❌ 简历不存在（ID: `{resume_id}`）")
        st.info("该简历可能已被删除，或 ID 无效。")
        if st.button("← 返回搜索页", use_container_width=True):
            st.switch_page("pages/1_智能搜索.py")
        st.stop()

    # Render full resume
    render_resume_full(doc, show_id=True)

    # Admin actions
    st.markdown("---")
    role = st.session_state.get("role", "")
    if role == "admin":
        col1, col2, col3 = st.columns(3)
        with col1:
            st.markdown(f"**简历 ID:** `{resume_id}`")
        with col2:
            if st.button("✏️ 编辑简历", use_container_width=True, type="secondary"):
                st.session_state.edit_resume_id = resume_id
                st.switch_page("pages/3_简历管理.py")
        with col3:
            if st.button("🗑️ 删除简历", use_container_width=True, type="secondary"):
                st.session_state[f"detail_confirm_del_{resume_id}"] = True

        if st.session_state.get(f"detail_confirm_del_{resume_id}"):
            st.warning(f"⚠️ 确定删除 {doc.get('personal_info', {}).get('full_name', '此简历')}？此操作不可撤销。")
            cc1, cc2 = st.columns(2)
            with cc1:
                if st.button("✅ 确认删除", key=f"detail_yes_{resume_id}", type="primary"):
                    if delete_resume_api(resume_id):
                        st.success("✅ 已删除")
                        st.session_state[f"detail_confirm_del_{resume_id}"] = False
                        st.switch_page("pages/3_简历管理.py")
                    else:
                        st.error("删除失败")
            with cc2:
                if st.button("❌ 取消", key=f"detail_no_{resume_id}"):
                    st.session_state[f"detail_confirm_del_{resume_id}"] = False
                    st.rerun()

    # Compare button available to ALL logged-in users
    st.markdown("---")
    if st.button("📊 加入对比", use_container_width=True, type="secondary", key=f"compare_btn_{resume_id}"):
        if "compare_candidates" not in st.session_state:
            st.session_state.compare_candidates = []
        if resume_id not in st.session_state.compare_candidates:
            if len(st.session_state.compare_candidates) < 5:
                st.session_state.compare_candidates.append(resume_id)
                st.success("✅ 已加入对比列表")
            else:
                st.warning("⚠️ 最多对比 5 位候选人")
        else:
            st.info("已在对比列表中")

    # Compare shortcut
    if st.session_state.get("compare_candidates"):
        st.markdown("---")
        compare_ids = st.session_state.compare_candidates
        st.markdown(f"📊 已选 {len(compare_ids)} 位候选人待对比：")
        for cid in compare_ids:
            st.caption(f"- `{cid}`")
        if st.button("→ 前往对比页", use_container_width=True, type="primary"):
            st.switch_page("pages/7_候选人对比.py")


if __name__ == "__main__":
    main()