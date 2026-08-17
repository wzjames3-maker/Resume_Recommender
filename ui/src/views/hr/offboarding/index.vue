<template>
  <div class="workspace-offboarding-page p-16-24">
    <div class="flex-between mb-16">
      <div>
        <h2>租户注销与数据返还</h2>
        <div class="color-secondary">注销当前工作空间的核心数据与 HR 数据。此操作不可逆，请先预览并下载返还包。</div>
      </div>
      <el-button :loading="loading" @click="loadPlan">刷新预览</el-button>
    </div>
    <el-alert title="高风险操作" type="warning" :closable="false" show-icon description="注销会删除应用、知识库、模型配置、对话记录、HR 候选人和简历等工作空间数据，并回收关联对象存储。默认不会强制删除活跃业务。" class="mb-16" />
    <el-card v-loading="loading" class="mb-16">
      <template #header><span>注销预览</span></template>
      <el-descriptions :column="2" border>
        <el-descriptions-item label="工作空间">{{ workspaceId }}</el-descriptions-item>
        <el-descriptions-item label="当前状态"><el-tag :type="plan?.can_offboard ? 'success' : 'warning'">{{ plan?.can_offboard ? '可注销' : '存在阻塞项' }}</el-tag></el-descriptions-item>
        <el-descriptions-item label="阻塞项" :span="2"><span v-if="!plan?.active_issues?.length" class="color-secondary">无</span><el-tag v-for="issue in plan?.active_issues || []" :key="issue" type="warning" class="mr-8">{{ issue }}</el-tag></el-descriptions-item>
      </el-descriptions>
    </el-card>
    <div class="count-grid mb-16" v-loading="loading">
      <el-card v-for="item in countItems" :key="item.key"><div class="count-label">{{ item.label }}</div><div class="count-value">{{ item.value }}</div><div class="count-group">{{ item.group }}</div></el-card>
    </div>
    <el-card>
      <template #header><span>执行注销</span></template>
      <div class="execute-panel">
        <el-checkbox v-model="force">强制注销（忽略活跃业务阻塞项）</el-checkbox>
        <el-checkbox v-model="includeExport">注销前生成并返回数据返还包</el-checkbox>
        <div class="color-secondary execute-hint">必须勾选工作空间确认框。建议先点击“下载返还包”，确认内容后再注销。</div>
        <el-input v-model="confirmation" :placeholder="'请输入工作空间 ID：' + workspaceId" clearable />
        <div class="actions"><el-button :loading="exportLoading" @click="downloadExport">下载数据返还包</el-button><el-button type="danger" :loading="purging" :disabled="confirmation !== workspaceId" @click="confirmPurge">注销工作空间</el-button></div>
      </div>
    </el-card>
  </div>
</template>

<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import WorkspaceApi from '@/api/workspace/workspace'
import useStore from '@/stores'
import type { WorkspaceOffboardingPlan } from '@/api/type/workspace'
import { MsgConfirm, MsgError, MsgSuccess } from '@/utils/message'

const { user } = useStore()
const workspaceId = computed(() => user.getWorkspaceId() || 'default')
const loading = ref(false)
const exportLoading = ref(false)
const purging = ref(false)
const plan = ref<WorkspaceOffboardingPlan | null>(null)
const force = ref(false)
const includeExport = ref(true)
const confirmation = ref('')

const countItems = computed(() => {
  const coreLabels: Record<string, string> = { applications: '应用', knowledge: '知识库', documents: '文档', paragraphs: '段落', embeddings: '向量', chats: '对话', models: '模型配置', core_files: '内核文件', workspace_permissions: '资源权限', resource_mappings: '资源映射', logs: '系统日志' }
  const hrLabels: Record<string, string> = { candidates: '候选人', jobs: '职位', applications: 'HR 申请', resume_files: '简历文件', knowledge_documents: '简历索引文档', knowledge_embeddings: '简历索引向量', storage_files: 'HR 存储对象' }
  const result: Array<{ key: string; label: string; value: number; group: string }> = []
  for (const [key, value] of Object.entries(plan.value?.counts?.core || {})) if (value) result.push({ key: 'core-' + key, label: coreLabels[key] || key, value, group: '内核域' })
  for (const [key, value] of Object.entries(plan.value?.counts?.hr || {})) if (value) result.push({ key: 'hr-' + key, label: hrLabels[key] || key, value, group: 'HR 域' })
  return result
})

function loadPlan() {
  loading.value = true
  WorkspaceApi.previewOffboarding(workspaceId.value, loading).then((response) => { plan.value = response.data }).catch(() => MsgError('加载注销预览失败')).finally(() => { loading.value = false })
}

function downloadJson(payload: Record<string, any>, filename: string) {
  const blob = new Blob([JSON.stringify(payload, null, 2)], { type: 'application/json;charset=utf-8' })
  const url = URL.createObjectURL(blob)
  const anchor = document.createElement('a')
  anchor.href = url
  anchor.download = filename
  anchor.click()
  URL.revokeObjectURL(url)
}

function downloadExport() {
  exportLoading.value = true
  WorkspaceApi.exportOffboarding(workspaceId.value, exportLoading).then((response) => { downloadJson(response.data, 'workspace-offboard-' + workspaceId.value + '.json'); MsgSuccess('数据返还包已下载') }).catch(() => MsgError('生成数据返还包失败')).finally(() => { exportLoading.value = false })
}

function confirmPurge() {
  if (confirmation.value !== workspaceId.value) return
  MsgConfirm('确认注销工作空间', '将永久删除工作空间“' + workspaceId.value + '”的核心域与 HR 域数据，且无法恢复。确认继续？', { confirmButtonClass: 'danger' }).then(() => {
    purging.value = true
    return WorkspaceApi.offboardWorkspace(workspaceId.value, { confirm_workspace_id: confirmation.value, force: force.value, export: includeExport.value }, purging)
  }).then((response) => { if (response.data?.export) downloadJson(response.data.export, 'workspace-offboard-' + workspaceId.value + '.json'); MsgSuccess('工作空间已注销'); plan.value = response.data }).catch(() => {}).finally(() => { purging.value = false })
}

onMounted(loadPlan)
</script>

<style scoped>
.workspace-offboarding-page { min-width: 0; }
.count-grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(150px, 1fr)); gap: 12px; }
.count-label { color: var(--el-text-color-secondary); font-size: 13px; }
.count-value { color: var(--el-color-danger); font-size: 26px; font-weight: 600; margin-top: 8px; }
.count-group { color: var(--el-text-color-placeholder); font-size: 12px; margin-top: 4px; }
.execute-panel { display: flex; flex-direction: column; gap: 14px; max-width: 720px; }
.execute-hint { font-size: 13px; }
.actions { display: flex; gap: 12px; }
.mr-8 { margin-right: 8px; }
</style>
