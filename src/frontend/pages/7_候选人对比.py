"""
智能招聘 RAG 推荐系统 - 候选人对比页

横向并排对比多位候选人的关键信息
"""

import streamlit as st
import pandas as pd
from src.frontend.api_client import get_resume
from src.frontend.components import export_to_excel

st.set_page_config(page_title="候选人对比", page_icon="📊", layout="wide")


def build_comparison_data(candidate_ids):
    """Build comparison data from candidate IDs."""
    rows = []
    headers = ["姓名", "学历", "毕业院校", "工作年限", "期望城市", "期望薪资", "当前状态", "技能标签", "最近公司", "最近职位"]

    for cid in candidate_ids:
        doc = get_resume(cid)
        if not doc:
            rows.append({h: "N/A" for h in headers})
            rows[-1]["姓名"] = f"{cid[:12]}... (已删除)"
            continue

        pi = doc.get("personal_info", {})
        edu = doc.get("education_list", [{}])[0] if doc.get("education_list") else {}
        exp = doc.get("experience_list", [{}])[0] if doc.get("experience_list") else {}
        skills = doc.get("skill_list", [])

        rows.append({
            "姓名": pi.get("full_name", "-"),
            "学历": pi.get("highest_education", "-"),
            "毕业院校": edu.get("school", "-"),
            "工作年限": f"{pi.get('years_of_experience', '-')} 年",
            "期望城市": ", ".join(pi.get("expected_city", [])) if isinstance(pi.get("expected_city"), list) else str(pi.get("expected_city") or "-"),
            "期望薪资": (pi.get("expected_salary_range") or "-"),
            "当前状态": (pi.get("current_status") or "-"),
            "技能标签": ", ".join([s if isinstance(s, str) else s.get("name", str(s)) for s in skills[:10]]) + ("..." if len(skills) > 10 else ""),
            "最近公司": exp.get("company", "-"),
            "最近职位": exp.get("title", "-"),
        })

    return headers, rows


def main():
    if not st.session_state.get("token"):
        st.warning("⚠️ 请先登录")
        st.stop()

    st.title("📊 候选人对比")

    candidate_ids = st.session_state.get("compare_candidates", [])

    if not candidate_ids:
        st.info("📭 暂未选择候选人进行对比")
        st.markdown("请在搜索页面勾选候选人卡片下方的「加入对比」复选框，然后返回此页面。")
        col1, col2 = st.columns(2)
        with col1:
            if st.button("→ 前往搜索页", use_container_width=True, type="primary"):
                st.switch_page("pages/1_智能搜索.py")
        with col2:
            if st.button("← 返回首页", use_container_width=True):
                st.switch_page("app.py")
        st.stop()

    # Build comparison data
    headers, rows = build_comparison_data(candidate_ids)

    if not rows:
        st.error("无法获取候选人数据")
        st.stop()

    # Transpose: each candidate as a column, each attribute as a row
    # Display as horizontal comparison
    n = len(candidate_ids)
    st.markdown(f"### 已选 {n} 位候选人")

    # Display as cards side by side
    cols = st.columns(n)
    for i, (cid, row) in enumerate(zip(candidate_ids, rows)):
        with cols[i]:
            name = row["姓名"]
            st.markdown(f"#### {name}")
            st.caption(f"ID: `{cid[:12]}...`")
            st.markdown(f"**学历:** {row['学历']}")
            st.markdown(f"**院校:** {row['毕业院校']}")
            st.markdown(f"**年限:** {row['工作年限']}")
            st.markdown(f"**城市:** {row['期望城市']}")
            st.markdown(f"**薪资:** {row['期望薪资']}")
            st.markdown(f"**状态:** {row['当前状态']}")
            st.markdown(f"**公司:** {row['最近公司']}")
            st.markdown(f"**职位:** {row['最近职位']}")
            st.markdown("**技能:**")
            st.caption(row["技能标签"])
            if st.button("📋 查看详情", key=f"detail_{cid}", use_container_width=True):
                st.session_state.current_resume_id = cid
                st.switch_page("pages/6_简历详情.py")

    # Comparison table (detailed)
    st.markdown("---")
    st.markdown("### 📋 详细对比表")

    df = pd.DataFrame(rows, index=[f"候选人 {i+1}" for i in range(len(rows))])
    st.dataframe(df.T, use_container_width=True)

    # Export
    st.markdown("---")
    col1, col2, col3, col4 = st.columns(4)
    with col1:
        export_data = [{**{"排名": i+1}, **row} for i, row in enumerate(rows)]
        xlsx_bytes = export_to_excel(export_data)
        if xlsx_bytes:
            st.download_button(
                label="📥 导出对比表 (Excel)",
                data=xlsx_bytes,
                file_name="候选人对比.xlsx",
                mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                use_container_width=True,
            )

    with col2:
        if st.button("🗑️ 清空对比列表", use_container_width=True):
            st.session_state.compare_candidates = []
            st.rerun()

    with col3:
        if st.button("→ 返回搜索页", use_container_width=True):
            st.switch_page("pages/1_智能搜索.py")


if __name__ == "__main__":
    main()