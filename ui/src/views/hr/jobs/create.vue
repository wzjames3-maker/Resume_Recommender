<template>
  <div class="create-job-page p-16-24">
    <header class="page-header">
      <div class="page-heading">
        <el-button link :icon="ArrowLeft" @click="goBack">返回职位</el-button>
        <div class="heading-copy">
          <span class="eyebrow">职位设置</span>
          <h2>新建职位</h2>
          <p>创建职位后，系统会自动生成默认招聘阶段，可直接进入 Pipeline 接收申请。</p>
        </div>
      </div>
      <el-tag :type="form.status === 'OPEN' ? 'success' : 'info'" effect="plain">{{ form.status === 'OPEN' ? '创建后立即开放' : '保存为草稿' }}</el-tag>
    </header>

    <main class="create-layout">
      <section class="form-surface">
        <div class="section-heading">
          <div><h3>职位信息</h3><p>先填写招聘团队能立即使用的最小信息，后续可以在职位管理中继续编辑。</p></div>
          <span class="required-note"><i>*</i> 必填</span>
        </div>

        <el-form ref="formRef" :model="form" :rules="rules" label-position="top" @submit.prevent>
          <div class="field-grid field-grid--three">
            <el-form-item label="职位名称" prop="name" class="field-span-2">
              <el-input v-model="form.name" maxlength="128" show-word-limit placeholder="例如：高级后端工程师" />
            </el-form-item>
            <el-form-item label="招聘人数" prop="headcount">
              <el-input-number v-model="form.headcount" :min="1" :max="999" controls-position="right" class="full-width" />
            </el-form-item>
            <el-form-item label="部门" prop="department">
              <el-input v-model="form.department" placeholder="例如：技术中心" />
            </el-form-item>
            <el-form-item label="工作城市" prop="city">
              <el-input v-model="form.city" placeholder="例如：北京 / 上海 / 远程" />
            </el-form-item>
            <el-form-item label="职级" prop="level">
              <el-input v-model="form.level" placeholder="例如：P6 / 专家" />
            </el-form-item>
            <el-form-item label="负责人" prop="owner_id" class="field-span-2">
              <el-select v-model="form.owner_id" clearable filterable placeholder="选择负责人" class="full-width" :loading="membersLoading">
                <el-option v-for="member in members" :key="member.id" :label="member.nick_name" :value="member.id" />
              </el-select>
            </el-form-item>
          </div>

          <el-divider />

          <el-form-item label="职位描述" prop="description">
            <el-input v-model="form.description" type="textarea" :rows="12" maxlength="4096" show-word-limit resize="vertical" placeholder="描述岗位职责、团队背景、工作方式和任职要求。建议写清楚必须条件与可加分项。" />
          </el-form-item>

          <el-form-item label="技能要求" prop="skill_requirements">
            <div class="skill-editor">
              <div class="skill-list">
                <el-tag v-for="skill in form.skill_requirements" :key="skill" closable effect="plain" @close="removeSkill(skill)">{{ skill }}</el-tag>
                <span v-if="!form.skill_requirements.length" class="empty-skill">还没有添加技能要求</span>
              </div>
              <div class="skill-input-row">
                <el-input v-model="skillDraft" clearable placeholder="输入技能后按 Enter，例如 Python" @keyup.enter="addSkill" @blur="addSkill" />
                <el-button plain :icon="MagicStick" :loading="extractingSkills" :disabled="!form.description.trim()" @click="extractSkills">AI 抽取</el-button>
              </div>
              <span class="field-help">技能会用于简历检索和候选人匹配，可在保存前手动调整。</span>
            </div>
          </el-form-item>
        </el-form>
      </section>

      <aside class="side-surface">
        <section class="side-section">
          <div class="side-heading"><h3>发布状态</h3><el-icon><InfoFilled /></el-icon></div>
          <el-radio-group v-model="form.status" class="status-options">
            <el-radio-button label="OPEN"><span class="status-dot status-dot--open" />立即开放</el-radio-button>
            <el-radio-button label="DRAFT"><span class="status-dot status-dot--draft" />保存草稿</el-radio-button>
          </el-radio-group>
          <p class="side-help">开放职位会立即出现在 Pipeline 和候选人匹配结果中；草稿只对招聘团队可见。</p>
        </section>

        <section class="side-section">
          <div class="side-heading"><h3>默认招聘阶段</h3><span class="color-secondary text-12">创建后可调整</span></div>
          <div class="stage-preview">
            <div v-for="stage in defaultStages" :key="stage.name" class="stage-preview-item">
              <span class="stage-marker" :style="{ background: stage.color }" />
              <span>{{ stage.name }}</span>
            </div>
          </div>
          <p class="side-help">阶段由 JobStage 驱动，Application 在阶段之间流转时会自动留下事件记录。</p>
        </section>

        <section class="side-section side-section--summary">
          <div class="side-heading"><h3>创建摘要</h3></div>
          <dl class="summary-list">
            <div><dt>职位名称</dt><dd>{{ form.name || '未填写' }}</dd></div>
            <div><dt>团队</dt><dd>{{ form.department || '未填写' }}</dd></div>
            <div><dt>城市</dt><dd>{{ form.city || '未填写' }}</dd></div>
            <div><dt>招聘人数</dt><dd>{{ form.headcount }} 人</dd></div>
            <div><dt>技能数量</dt><dd>{{ form.skill_requirements.length }} 项</dd></div>
          </dl>
        </section>
      </aside>
    </main>

    <footer class="action-bar">
      <el-button type="primary" :icon="Check" :loading="saving" @click="submit">创建职位</el-button>
    </footer>
  </div>
</template>

<script setup lang="ts">
import { onMounted, reactive, ref } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import type { FormInstance, FormRules } from 'element-plus'
import { ArrowLeft, Check, InfoFilled, MagicStick } from '@element-plus/icons-vue'
import HrApi from '@/api/hr/recruitment'
import type { JobStatus } from '@/api/type/hr'
import { MsgError, MsgSuccess } from '@/utils/message'

interface MemberOption { id: string; nick_name: string }

const router = useRouter()
const formRef = ref<FormInstance>()
const saving = ref(false)
const extractingSkills = ref(false)
const membersLoading = ref(false)
const skillDraft = ref('')
const members = ref<MemberOption[]>([])
const form = reactive({
  name: '',
  department: '',
  city: '',
  level: '',
  headcount: 1,
  description: '',
  skill_requirements: [] as string[],
  status: 'OPEN' as JobStatus,
  owner_id: null as string | null,
})

const rules: FormRules = {
  name: [{ required: true, message: '请填写职位名称', trigger: ['blur', 'change'] }],
  headcount: [{ required: true, message: '请设置招聘人数', trigger: 'change' }],
  description: [{ required: true, message: '请填写职位描述，至少说明岗位职责或任职要求', trigger: 'blur' }],
}

const defaultStages = [
  { name: '待筛选', color: '#909399' },
  { name: '初筛通过', color: '#409eff' },
  { name: '面试中', color: '#e6a23c' },
  { name: 'Offer', color: '#67c23a' },
]

function goBack() { router.push('/hr/pipeline') }

function loadMembers() {
  membersLoading.value = true
  HrApi.getMembers()
    .then((response) => { members.value = response.data || [] })
    .catch(() => {})
    .finally(() => { membersLoading.value = false })
}

function addSkill() {
  const skill = skillDraft.value.trim()
  if (!skill) return
  if (!form.skill_requirements.includes(skill)) form.skill_requirements.push(skill)
  skillDraft.value = ''
}

function removeSkill(skill: string) {
  form.skill_requirements = form.skill_requirements.filter((item) => item !== skill)
}

function extractSkills() {
  if (!form.description.trim()) return
  extractingSkills.value = true
  HrApi.extractSkills(form.description.trim())
    .then((response) => {
      response.data.skills.forEach((skill) => { if (!form.skill_requirements.includes(skill)) form.skill_requirements.push(skill) })
      MsgSuccess('技能已抽取，请确认后保存')
    })
    .catch(() => MsgError('技能抽取失败，请稍后重试'))
    .finally(() => { extractingSkills.value = false })
}

async function submit() {
  const valid = await formRef.value?.validate().catch(() => false)
  if (!valid) return
  saving.value = true
  try {
    const response = await HrApi.createJob({ ...form, skill_requirements: [...form.skill_requirements] })
    MsgSuccess('职位已创建')
    router.replace({ path: '/hr/pipeline', query: { job: response.data.id } })
  } catch {
    ElMessage.error('职位创建失败，请检查表单或稍后重试')
  } finally {
    saving.value = false
  }
}

onMounted(loadMembers)
</script>

<style scoped>
.create-job-page { min-height: 100%; background: var(--el-bg-color-page); }
.page-header { display: flex; justify-content: space-between; align-items: flex-start; gap: 20px; margin-bottom: 20px; }
.page-heading { display: flex; align-items: flex-start; gap: 16px; }
.heading-copy { padding-left: 16px; border-left: 1px solid var(--el-border-color); }
.eyebrow { display: block; margin-bottom: 4px; color: var(--el-color-primary); font-size: 12px; font-weight: 700; letter-spacing: 1px; }
h2 { margin: 0 0 6px; font-size: 24px; line-height: 32px; }
.heading-copy p { margin: 0; color: var(--el-text-color-secondary); font-size: 13px; }
.create-layout { display: grid; grid-template-columns: minmax(0, 1fr) 320px; gap: 16px; align-items: start; }
.form-surface, .side-surface { border: 1px solid var(--el-border-color-light); border-radius: 6px; background: var(--el-bg-color); }
.form-surface { padding: 24px; }
.section-heading { display: flex; justify-content: space-between; gap: 16px; margin-bottom: 22px; }
.section-heading h3, .side-heading h3 { margin: 0; font-size: 16px; }
.section-heading p { margin: 5px 0 0; color: var(--el-text-color-secondary); font-size: 12px; }
.required-note { color: var(--el-text-color-secondary); font-size: 12px; white-space: nowrap; }
.required-note i { color: var(--el-color-danger); font-style: normal; }
.field-grid { display: grid; gap: 0 16px; }
.field-grid--three { grid-template-columns: repeat(3, minmax(0, 1fr)); }
.field-span-2 { grid-column: span 2; }
.full-width { width: 100%; }
.skill-editor { width: 100%; }
.skill-list { display: flex; flex-wrap: wrap; align-items: center; gap: 8px; min-height: 34px; margin-bottom: 10px; }
.empty-skill { color: var(--el-text-color-placeholder); font-size: 12px; }
.skill-input-row { display: flex; gap: 10px; }
.skill-input-row .el-input { flex: 1; }
.field-help, .side-help { color: var(--el-text-color-secondary); font-size: 12px; line-height: 18px; }
.field-help { display: block; margin-top: 8px; }
.side-surface { padding: 0 18px; }
.side-section { padding: 20px 0; border-bottom: 1px solid var(--el-border-color-lighter); }
.side-section:last-child { border-bottom: 0; }
.side-heading { display: flex; justify-content: space-between; align-items: center; gap: 8px; margin-bottom: 14px; }
.side-heading .el-icon { color: var(--el-text-color-secondary); }
.status-options { display: flex; width: 100%; }
.status-options .el-radio-button { flex: 1; }
.status-options :deep(.el-radio-button__inner) { width: 100%; padding: 9px 8px; }
.status-dot { display: inline-block; width: 7px; height: 7px; margin-right: 5px; border-radius: 50%; }
.status-dot--open { background: var(--el-color-success); }
.status-dot--draft { background: var(--el-text-color-placeholder); }
.side-help { margin: 10px 0 0; }
.stage-preview { display: grid; gap: 10px; }
.stage-preview-item { display: flex; align-items: center; gap: 9px; color: var(--el-text-color-regular); font-size: 13px; }
.stage-marker { width: 9px; height: 9px; border-radius: 50%; }
.summary-list { display: grid; gap: 10px; margin: 0; }
.summary-list div { display: flex; justify-content: space-between; gap: 12px; font-size: 12px; }
.summary-list dt { color: var(--el-text-color-secondary); }
.summary-list dd { max-width: 170px; margin: 0; overflow: hidden; color: var(--el-text-color-primary); text-align: right; text-overflow: ellipsis; white-space: nowrap; }
.action-bar { display: flex; justify-content: flex-end; gap: 10px; padding: 16px 0 4px; }
.text-12 { font-size: 12px; }
@media (max-width: 900px) {
  .page-header { flex-direction: column; }
  .create-layout { grid-template-columns: 1fr; }
  .side-surface { order: -1; }
}
@media (max-width: 640px) {
  .page-heading { gap: 8px; }
  .heading-copy { padding-left: 10px; }
  .form-surface { padding: 16px; }
  .field-grid--three { grid-template-columns: 1fr; }
  .field-span-2 { grid-column: auto; }
  .skill-input-row { align-items: stretch; flex-direction: column; }
}
</style>
