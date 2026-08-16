<template>
  <el-dialog v-model="visible" title="AI 设置" width="480px">
    <el-form label-width="96px" @submit.prevent>
      <el-form-item label="LLM 模型">
        <el-select v-model="modelId" filterable clearable placeholder="选择工作区的 LLM 模型" style="width: 100%">
          <el-option v-for="m in llmModels" :key="m.id" :label="m.name" :value="m.id" />
        </el-select>
      </el-form-item>
      <div class="color-secondary">用于自然语言搜人与职位技能抽取；未设置时 AI 功能不可用。</div>
      <el-form-item label="Rerank 模型">
        <el-select v-model="rerankModelId" filterable clearable placeholder="可选，选择工作区的 RERANKER 模型" style="width: 100%">
          <el-option v-for="m in rerankModels" :key="m.id" :label="m.name" :value="m.id" />
        </el-select>
      </el-form-item>
      <div class="color-secondary">用于简历语义检索精排；未设置时自动降级为 RRF 排序。</div>
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
import ModelApi from '@/api/model/model'
import type { Model } from '@/api/type/model'
import { MsgSuccess } from '@/utils/message'

const visible = defineModel<boolean>('visible', { default: false })
const saving = ref(false)
const modelId = ref('')
const rerankModelId = ref('')
const llmModels = ref<Model[]>([])
const rerankModels = ref<Model[]>([])

onMounted(() => {
  ModelApi.getSelectModelList({ model_type: 'LLM' }).then((response) => {
    llmModels.value = response.data
  })
  ModelApi.getSelectModelList({ model_type: 'RERANKER' }).then((response) => {
    rerankModels.value = response.data
  })
})

watch(visible, (show) => {
  if (show) {
    modelId.value = ''
    rerankModelId.value = ''
    ModelApi.getSelectModelList({ model_type: 'LLM' }).then((response) => {
      llmModels.value = response.data
    })
    ModelApi.getSelectModelList({ model_type: 'RERANKER' }).then((response) => {
      rerankModels.value = response.data
    })
    HrApi.getAiConfig().then((response) => {
      modelId.value = response.data.llm_model_id || ''
      rerankModelId.value = response.data.rerank_model_id || ''
    })
  }
})

function save() {
  saving.value = true
  HrApi.putAiConfig({ llm_model_id: modelId.value, rerank_model_id: rerankModelId.value })
    .then(() => {
      MsgSuccess('AI 设置已保存')
      visible.value = false
    })
    .finally(() => {
      saving.value = false
    })
}
</script>
