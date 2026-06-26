p = r"C:\Users\Administrator\Desktop\简历推荐系统\src\frontend\pages\6_简历详情.py"
with open(p, "r", encoding="utf-8") as f:
    c = f.read()

# Find the admin block that contains the compare button
# Replace: 4-column layout with compare inside admin -> 3-column admin only + compare outside

old_block = '''    if role == "admin":
        col1, col2, col3, col4 = st.columns(4)
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
            st.warning(f"⚠️ 确定删除 {doc.get('personal_info', {}).get('name', '此简历')}？此操作不可撤销。")
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

        with col4:
            if st.button("📊 加入对比", use_container_width=True, type="secondary"):
                if "compare_candidates" not in st.session_state:
                    st.session_state.compare_candidates = []
                if resume_id not in st.session_state.compare_candidates:
                    if len(st.session_state.compare_candidates) < 5:
                        st.session_state.compare_candidates.append(resume_id)
                        st.success("✅ 已加入对比列表")
                    else:
                        st.warning("⚠️ 最多对比 5 位候选人")
                else:
                    st.info("已在对比列表中")'''

new_block = '''    if role == "admin":
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
            st.warning(f"⚠️ 确定删除 {doc.get('personal_info', {}).get('name', '此简历')}？此操作不可撤销。")
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
            st.info("已在对比列表中")'''

print("Old found:", old_block in c)
c = c.replace(old_block, new_block)
with open(p, "w", encoding="utf-8") as f:
    f.write(c)
print("Fix 3 reapplied correctly")