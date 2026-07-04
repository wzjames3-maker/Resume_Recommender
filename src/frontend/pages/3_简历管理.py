"""
智能招聘 RAG 推荐系统 - 简历管理页面 v2.1

管理员可查看、搜索、筛选、编辑、批量删除简历
通过 API 客户端访问后端，不直连数据库
"""

import streamlit as st
from src.frontend.api_client import list_resumes_api, delete_resume_api, update_resume, get_resume_stats

st.set_page_config(page_title="简历管理", page_icon="🗂️", layout="wide")


def render_resume_detail(doc):
    """渲染简历详情"""
    pi = doc.get("personal_info", {})

    col1, col2 = st.columns(2)
    with col1:
        st.markdown(f"**姓名:** {pi.get('full_name', '-')}")
        st.markdown(f"**学历:** {pi.get('highest_education', '-')}")
        st.markdown(f"**工作年限:** {pi.get('years_of_experience', '-')} 年")
        ec = pi.get('expected_city', '')
        if isinstance(ec, list):
            ec = ', '.join(ec) if ec else '-'
        st.markdown(f"**期望城市:** {ec}")
    with col2:
        st.markdown(f"**期望薪资:** {pi.get('expected_salary_range', '-')}")
        st.markdown(f"**当前状态:** {pi.get('current_status', '-')}")
        created = doc.get("created_at", "")
        if isinstance(created, str) and len(created) > 10:
            created = created[:19]
        st.markdown(f"**入库时间:** {created}")

    skills = doc.get("skill_list", [])
    if skills:
        st.markdown("**🛠️ 技能标签:**")
        tags = ' '.join([f'`{s if isinstance(s, str) else s.get("name", str(s))}`' for s in skills[:20]])
        st.markdown(tags)

    edu_list = doc.get("education_list", [])
    if edu_list:
        st.markdown("**🎓 教育经历:**")
        for edu in edu_list:
            school = edu.get("school", "-")
            degree = edu.get("degree", "-")
            major = edu.get("major", "-")
            badges = []
            if edu.get("is_985"): badges.append("`985`")
            if edu.get("is_211"): badges.append("`211`")
            badge_str = " " + " ".join(badges) if badges else ""
            st.markdown(f"- {school} | {degree} | {major}{badge_str}")

    exp_list = doc.get("experience_list", [])
    if exp_list:
        st.markdown("**💼 工作经历:**")
        for exp in exp_list:
            company = exp.get("company", "-")
            title = exp.get("title", "-")
            duration = exp.get("start_date", "-")
            desc = exp.get("description", "")
            st.markdown(f"- **{company}** | {title} ({duration})")
            if desc:
                st.caption(desc)


def main():
    if not st.session_state.get("token"):
        st.warning("⚠️ 请先登录")
        st.stop()

    if st.session_state.get("role") != "admin":
        st.error("🚫 此页面仅限管理员访问")
        st.stop()

    st.title("🗂️ 简历管理")
    st.caption("查看、搜索和管理已入库的简历")

    # ===== 高级筛选器 =====
    with st.expander("🔍 高级筛选", expanded=True):
        col1, col2, col3, col4 = st.columns(4)
        with col1:
            keyword = st.text_input("搜索关键词", placeholder="姓名、技能、内容...")
        with col2:
            skill_filter = st.text_input("技能筛选", placeholder="Python, React...")
        with col3:
            city = st.text_input("期望城市", placeholder="北京, 杭州...")
        with col4:
            education = st.selectbox("学历", ["不限", "大专", "本科", "硕士", "博士"], index=0)

        col1, col2, col3, col4 = st.columns(4)
        with col1:
            min_exp = st.number_input("最低工作年限", min_value=0, max_value=20, value=0, step=1)
        with col2:
            is_985 = st.checkbox("985 院校", value=False)
        with col3:
            is_211 = st.checkbox("211 院校", value=False)
        with col4:
            st.markdown("<br>", unsafe_allow_html=True)
            search_btn = st.button("🔍 搜索", type="primary", use_container_width=True)

    # 统计
    stats = get_resume_stats()
    total_count = stats.get("total_resumes", 0) if stats else 0
    st.metric("📋 简历总数", total_count)

    # 批量选择
    if "selected_resumes" not in st.session_state:
        st.session_state.selected_resumes = []

    st.markdown("---")

    # 分页
    page_size = 10
    if "resume_page" not in st.session_state:
        st.session_state.resume_page = 1

    result = list_resumes_api(
        keyword=keyword, skill=skill_filter, city=city,
        education=education if education != "不限" else "",
        min_exp=int(min_exp), is_985=is_985, is_211=is_211,
        page=st.session_state.resume_page, size=page_size
    )

    if result is None:
        st.error("❌ 获取简历列表失败，请检查 API 连接")
        return

    docs = result.get("items", [])
    total = result.get("total", 0)
    total_pages = max(1, (total + page_size - 1) // page_size)

    # 分页 + 批量操作
    col1, col2, col3, col4 = st.columns([1, 2, 1, 1])
    with col1:
        if st.button("⬅️ 上一页") and st.session_state.resume_page > 1:
            st.session_state.resume_page -= 1
            st.rerun()
    with col2:
        st.markdown(f"<center>第 {st.session_state.resume_page}/{total_pages} 页 | 共 {total} 条</center>", unsafe_allow_html=True)
    with col3:
        if st.button("下一页 ➡️") and st.session_state.resume_page < total_pages:
            st.session_state.resume_page += 1
            st.rerun()
    with col4:
        if st.button("🗑️ 批量删除选中", type="secondary", use_container_width=True):
            if st.session_state.selected_resumes:
                st.session_state.confirm_batch_delete = True

    # 批量删除确认
    if st.session_state.get("confirm_batch_delete"):
        n_sel = len(st.session_state.selected_resumes)
        st.warning(f"⚠️ 确定删除选中的 {n_sel} 份简历？")
        cc1, cc2 = st.columns(2)
        with cc1:
            if st.button(f"✅ 确认批量删除 ({n_sel}份)", type="primary"):
                deleted = 0
                for rid in st.session_state.selected_resumes:
                    if delete_resume_api(rid):
                        deleted += 1
                st.success(f"✅ 已删除 {deleted} 份简历")
                st.session_state.selected_resumes = []
                st.session_state.confirm_batch_delete = False
                st.rerun()
        with cc2:
            if st.button("❌ 取消"):
                st.session_state.confirm_batch_delete = False
                st.rerun()

    # 简历列表
    if not docs:
        st.info("📭 暂无简历数据")
        return

    for doc in docs:
        pi = doc.get("personal_info", {})
        name = pi.get("full_name", "未知")
        skills = doc.get("skill_list", [])
        edu_list = doc.get("education_list", [])
        exp_list = doc.get("experience_list", [])
        resume_id = doc.get("id", "")

        top_school = edu_list[0].get("school", "") if edu_list else ""
        top_company = exp_list[0].get("company", "") if exp_list else ""
        skill_preview = ', '.join([s if isinstance(s, str) else s.get('name', str(s)) for s in skills[:5]]) if skills else '无技能标签'

        with st.expander(f"👤 {name}  |  {skill_preview}  |  {top_school}  |  {top_company}"):
            render_resume_detail(doc)

            # 编辑表单
            with st.expander("✏️ 编辑简历"):
                with st.form(f"edit_{resume_id}"):
                    new_name = st.text_input("姓名", value=pi.get("full_name", ""))
                    new_education = st.text_input("学历", value=pi.get("highest_education", ""))
                    new_skills = st.text_input('技能（逗号分隔）', value=', '.join([s if isinstance(s, str) else s.get('name', str(s)) for s in skills]))
                    ec = pi.get("expected_city", "")
                    if isinstance(ec, list):
                        ec = ", ".join(ec)
                    new_city = st.text_input("期望城市", value=str(ec or ""))
                    new_salary = st.text_input("期望薪资", value=pi.get("expected_salary_range", ""))
                    submitted = st.form_submit_button("💾 保存修改", type="primary")
                    if submitted:
                        updated_pi = dict(pi)
                        updated_pi["full_name"] = new_name
                        updated_pi["highest_education"] = new_education
                        updated_pi["expected_city"] = [c.strip() for c in new_city.split(",") if c.strip()]
                        updated_pi["expected_salary_range"] = new_salary
                        updated_skills = [{"name": s.strip()} for s in new_skills.split(",") if s.strip()]
                        if update_resume(resume_id, {
                            "personal_info": updated_pi,
                            "skill_list": updated_skills,
                        }):
                            st.success("✅ 修改已保存")
                            st.rerun()
                        else:
                            st.error("修改失败")

            st.markdown("---")
            col1, col2, col3 = st.columns([1, 1, 2])
            with col1:
                if st.button("🗑️ 删除", key=f"del_{resume_id}", type="secondary"):
                    st.session_state[f"confirm_del_{resume_id}"] = True
            with col2:
                is_sel = resume_id in st.session_state.selected_resumes
                if st.checkbox("☑️ 选择", value=is_sel, key=f"sel_{resume_id}"):
                    if resume_id not in st.session_state.selected_resumes:
                        st.session_state.selected_resumes.append(resume_id)
                else:
                    if resume_id in st.session_state.selected_resumes:
                        st.session_state.selected_resumes.remove(resume_id)
            with col3:
                if st.button("📋 查看详情", key=f"detail_{resume_id}"):
                    st.session_state.current_resume_id = resume_id
                    st.switch_page("pages/6_简历详情.py")

            if st.session_state.get(f"confirm_del_{resume_id}"):
                st.warning(f"确定删除 {name} 的简历？")
                cc1, cc2 = st.columns(2)
                with cc1:
                    if st.button("✅ 确认删除", key=f"confirm_yes_{resume_id}", type="primary"):
                        if delete_resume_api(resume_id):
                            st.success("✅ 已删除")
                            st.session_state[f"confirm_del_{resume_id}"] = False
                            st.rerun()
                        else:
                            st.error("删除失败")
                with cc2:
                    if st.button("❌ 取消", key=f"confirm_no_{resume_id}"):
                        st.session_state[f"confirm_del_{resume_id}"] = False
                        st.rerun()


if __name__ == "__main__":
    main()
