<template>
  <el-dialog v-model="visible" title="AI 设置" width="560px">
    <el-form label-width="96px" @submit.prevent>
      <el-form-item label="LLM 模型">
        <el-select v-model="modelId" filterable clearable placeholder="选择工作区的 LLM 模型" style="width: 100%">
          <el-option v-for="m in llmModels" :key="m.id" :label="m.name" :value="m.id" />
        </el-select>
      </el-form-item>
      <div class="color-secondary">用于自然语言搜人、职位技能抽取与 Agent（评估/JD 起草/面试助手）；未设置时 AI 功能不可用。</div>
      <el-form-item label="Rerank 模型">
        <el-select v-model="rerankModelId" filterable clearable placeholder="可选，选择工作区的 RERANKER 模型" style="width: 100%">
          <el-option v-for="m in rerankModels" :key="m.id" :label="m.name" :value="m.id" />
        </el-select>
      </el-form-item>
      <div class="color-secondary">用于简历语义检索与知识库检索精排；未设置时自动降级为 RRF 排序。</div>
      <el-form-item label="企业知识库">
        <el-select v-model="kbIds" multiple filterable collapse-tags collapse-tags-tooltip placeholder="Agent 可检索的知识库白名单（可多选）" style="width: 100%">
          <el-option v-for="kb in kbOptions" :key="kb.id" :label="kb.name" :value="kb.id" />
        </el-select>
      </el-form-item>
      <div class="color-secondary">仅白名单内的知识库可作为 JD 起草、面试助手的检索来源；简历语义索引受保护，不可加入。</div>
    </el-form>
    <template #footer>
      <el-button @click="visible = false">取消</el-button>
      <el-button type="primary" :loading="saving" @click="save">保存</el-button>
    </template>
  </el-dialog>
</template>

<script setup lang="ts">
import { onMounted, ref, watch } from 'vue'
import HrApi from '@/api/hr/recruitment'
import KnowledgeApi from '@/api/knowledge/knowledge'
import ModelApi from '@/api/model/model'
import type { Model } from '@/api/type/model'
import { MsgSuccess } from '@/utils/message'

const visible = defineModel<boolean>('visible', { default: false })
const saving = ref(false)
const modelId = ref('')
const rerankModelId = ref('')
const kbIds = ref<string[]>([])
const kbOptions = ref<{ id: string; name: string }[]>([])
const llmModels = ref<Model[]>([])
const rerankModels = ref<Model[]>([])

function loadOptions() {
  ModelApi.getSelectModelList({ model_type: 'LLM' }).then((response) => {
    llmModels.value = response.data
  })
  ModelApi.getSelectModelList({ model_type: 'RERANKER' }).then((response) => {
    rerankModels.value = response.data
  })
  KnowledgeApi.getKnowledgeList().then((response) => {
    const rows = Array.isArray(response.data) ? response.data : response.data?.records || []
    kbOptions.value = rows.map((row: { id: string; name: string }) => ({ id: row.id, name: row.name }))
  })
}

onMounted(loadOptions)

watch(visible, (show) => {
  if (show) {
    modelId.value = ''
    rerankModelId.value = ''
    kbIds.value = []
    loadOptions()
    HrApi.getAiConfig().then((response) => {
      modelId.value = response.data.llm_model_id || ''
      rerankModelId.value = response.data.rerank_model_id || ''
      kbIds.value = response.data.agent_knowledge_bases || []
    })
  }
})

function save() {
  saving.value = true
  HrApi.putAiConfig({
    llm_model_id: modelId.value,
    rerank_model_id: rerankModelId.value,
    agent_knowledge_bases: kbIds.value,
  })
    .then(() => {
      MsgSuccess('AI 设置已保存')
      visible.value = false
    })
    .finally(() => {
      saving.value = false
    })
}
</script>