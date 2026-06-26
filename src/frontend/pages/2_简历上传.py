"""
智能招聘 RAG 推荐系统 - 简历上传页面 v2.0

支持单个上传和批量上传 PDF/DOCX/JSON，上传后预览解析结果
"""

import streamlit as st
import time
from src.frontend.api_client import upload_resume, get_resume
from src.frontend.components import render_resume_full

st.set_page_config(page_title="简历上传", page_icon="📄", layout="wide")

ALLOWED_TYPES = ["pdf", "docx", "json"]
MAX_FILE_SIZE_MB = 20


def show_upload_result(result, uploaded_file):
    """v2.0: 展示上传结果 + 解析预览"""
    if result and result.get("success"):
        st.success("✅ 简历上传成功！")

        col1, col2, col3, col4 = st.columns(4)
        resume_id = result.get("resume_id", "-")
        with col1:
            st.metric("简历 ID", resume_id[:12] + "..." if len(resume_id) > 12 else resume_id)
        with col2:
            st.metric("解析状态", result.get("parse_status", "-"))
        with col3:
            st.metric("消息", result.get("message", "-"))
        with col4:
            st.metric("文件名", uploaded_file.name)

        # v2.0: 解析结果预览
        st.markdown("---")
        st.markdown("### 📋 解析结果预览")
        with st.spinner("正在获取解析结果..."):
            doc = get_resume(resume_id)
            if doc:
                with st.expander("查看完整解析结果", expanded=True):
                    render_resume_full(doc, show_id=True)
            else:
                st.info("解析结果尚未就绪，请稍后查看")

        st.markdown("---")
        st.markdown("🔍 前往 **智能搜索** 页面测试搜索新上传的简历")
    elif result:
        st.error(f"❌ 上传失败: {result.get('message', '未知错误')}")
    else:
        st.error("❌ 上传请求失败，请检查网络连接")


def main():
    if not st.session_state.get("token"):
        st.warning("⚠️ 请先登录")
        st.stop()

    st.title("📄 简历上传")
    st.caption("上传简历文件，系统将自动解析并入库")

    # 信息提示
    col1, col2, col3 = st.columns(3)
    with col1:
        st.info("**支持格式:** PDF / DOCX / JSON")
    with col2:
        st.info(f"**文件大小限制:** {MAX_FILE_SIZE_MB}MB")
    with col3:
        st.info("**自动处理:** OCR → 结构化提取 → 向量索引")

    st.markdown("---")

    tab1, tab2 = st.tabs(["📤 单个上传", "📦 批量上传"])

    # ========== 单个上传 ==========
    with tab1:
        col1, col2 = st.columns([2, 1])

        with col1:
            st.caption("💡 支持拖拽上传，点击下方区域选择文件")
            uploaded_file = st.file_uploader(
                "选择简历文件",
                type=ALLOWED_TYPES,
                help="支持 PDF、DOCX、JSON 格式",
                key="single_upload",
            )

        with col2:
            if uploaded_file:
                st.markdown("**文件信息:**")
                st.markdown(f"- 文件名: `{uploaded_file.name}`")
                st.markdown(f"- 大小: {uploaded_file.size / 1024:.1f} KB")
                st.markdown(f"- 类型: {uploaded_file.type}")

        if uploaded_file and st.button("🚀 开始上传", type="primary", use_container_width=True):
            if uploaded_file.size > MAX_FILE_SIZE_MB * 1024 * 1024:
                st.error(f"❌ 文件大小超过 {MAX_FILE_SIZE_MB}MB 限制")
            else:
                with st.spinner("⏳ 正在上传并解析简历..."):
                    result = upload_resume(uploaded_file.getvalue(), uploaded_file.name)

                show_upload_result(result, uploaded_file)

    # ========== 批量上传 ==========
    with tab2:
        st.caption("💡 支持拖拽多个文件，或点击下方区域批量选择")
        uploaded_files = st.file_uploader(
            "选择多个简历文件",
            type=ALLOWED_TYPES,
            accept_multiple_files=True,
            help="可同时选择多个文件",
            key="batch_upload",
        )

        if uploaded_files:
            st.markdown(f"**已选择 {len(uploaded_files)} 个文件:**")
            for f in uploaded_files:
                st.markdown(f"- `{f.name}` ({f.size / 1024:.1f} KB)")

        if uploaded_files and st.button("🚀 开始批量上传", type="primary", use_container_width=True):
            progress_bar = st.progress(0)
            status_text = st.empty()
            results = []

            for i, f in enumerate(uploaded_files):
                status_text.text(f"正在处理: {f.name} ({i + 1}/{len(uploaded_files)})")
                progress_bar.progress((i + 1) / len(uploaded_files))

                if f.size > MAX_FILE_SIZE_MB * 1024 * 1024:
                    results.append({"filename": f.name, "success": False, "message": "文件过大", "resume_id": "-"})
                    continue

                result = upload_resume(f.getvalue(), f.name)
                if result:
                    results.append({
                        "filename": f.name,
                        "success": result.get("success", False),
                        "message": result.get("message", ""),
                        "resume_id": result.get("resume_id", "-"),
                        "parse_status": result.get("parse_status", "-"),
                    })
                else:
                    results.append({"filename": f.name, "success": False, "message": "请求失败", "resume_id": "-"})

                time.sleep(0.5)

            status_text.text("✅ 批量上传完成！")
            progress_bar.progress(1.0)

            st.markdown("---")
            st.markdown("### 📊 上传结果")

            success_count = sum(1 for r in results if r.get("success"))
            st.metric("成功/总数", f"{success_count}/{len(results)}")

            for r in results:
                icon = "✅" if r.get("success") else "❌"
                with st.expander(f"{icon} {r['filename']}"):
                    col1, col2 = st.columns(2)
                    with col1:
                        st.markdown(f"**状态:** {r.get('message', '-')}")
                        st.markdown(f"**简历 ID:** {r.get('resume_id', '-')}")
                    with col2:
                        st.markdown(f"**解析状态:** {r.get('parse_status', '-')}")

                    # v2.0: 预览批量上传的每份简历
                    if r.get("success") and r.get("resume_id") and r["resume_id"] != "-":
                        with st.spinner("加载解析结果..."):
                            doc = get_resume(r["resume_id"])
                            if doc:
                                pi = doc.get("personal_info", {})
                                st.markdown(f"**姓名:** {pi.get('full_name', '-')}  |  **学历:** {pi.get('highest_education', '-')}  |  **年限:** {pi.get('years_of_experience', '-')} 年")


if __name__ == "__main__":
    main()