<template>
  <div class="p-16-24 application-setting">
    <div class="flex-between w-full mb-16">
      <h3>
        {{ $t('common.setting') }}
      </h3>
      <div>
        <el-button
          type="primary"
          @click="submit(applicationFormRef)"
          :disabled="loading"
          v-if="permissionPrecise.edit(id)"
        >
          {{ $t('common.save') }}
        </el-button>
        <el-button
          type="primary"
          @click="publish(applicationFormRef)"
          :disabled="loading"
          v-if="permissionPrecise.publish(id)"
        >
          {{ $t('common.publish') }}
        </el-button>
      </div>
    </div>

    <el-card style="--el-card-padding: 0">
      <el-row v-loading="loading">
        <el-col :span="10">
          <div class="p-24 mb-16" style="padding-bottom: 0">
            <h4 class="title-decoration-1">
              {{ $t('common.info') }}
            </h4>
          </div>
          <div class="scrollbar-height-left">
            <el-scrollbar>
              <el-form
                hide-required-asterisk
                ref="applicationFormRef"
                :model="applicationForm"
                :rules="rules"
                label-position="top"
                require-asterisk-position="right"
                class="p-24"
                style="padding-top: 0"
              >
                <el-form-item prop="name">
                  <template #label>
                    <div class="flex-between">
                      <span>{{ $t('common.name') }} <span class="color-danger">*</span></span>
                    </div>
                  </template>
                  <el-input
                    v-model="applicationForm.name"
                    maxlength="64"
                    :placeholder="$t('views.application.form.appName.placeholder')"
                    show-word-limit
                    @blur="applicationForm.name = applicationForm.name?.trim()"
                  />
                </el-form-item>
                <el-form-item :label="$t('common.desc')">
                  <el-input
                    v-model="applicationForm.desc"
                    type="textarea"
                    :placeholder="$t('views.application.form.appDescription.placeholder')"
                    :rows="3"
                    maxlength="256"
                    show-word-limit
                  />
                </el-form-item>

                <el-form-item :label="$t('views.application.form.aiModel.label')">
                  <template #label>
                    <div class="flex-between">
                      <span>{{ $t('views.application.form.aiModel.label') }}</span>

                      <el-button
                        type="primary"
                        link
                        @click="openAIParamSettingDialog"
                        :disabled="!applicationForm.model_id"
                      >
                        <AppIcon iconName="app-setting" class="mr-4"></AppIcon>
                        {{ $t('common.paramSetting') }}
                      </el-button>
                    </div>
                  </template>
                  <ModelSelect
                    v-model="applicationForm.model_id"
                    :placeholder="$t('views.application.form.aiModel.placeholder')"
                    :options="modelOptions"
                    @change="model_change"
                    @submitModel="getSelectModel"
                    showFooter
                    :model-type="'LLM'"
                  >
                  </ModelSelect>
                </el-form-item>
                <el-form-item>
                  <template #label>
                    <div class="flex-between">
                      <div class="flex align-center">
                        <span>{{ $t('views.application.form.roleSettings.label') }}</span>
                        <el-tooltip
                          effect="dark"
                          :content="$t('views.application.form.roleSettings.tooltip')"
                          placement="right"
                        >
                          <AppIcon iconName="app-warning" class="app-warning-icon ml-4"></AppIcon>
                        </el-tooltip>
                      </div>

                      <el-button
                        type="primary"
                        link
                        @click="openGeneratePromptDialog"
                        :disabled="!applicationForm.model_id"
                      >
                        <AppIcon iconName="app-generate-star" class="mr-4"></AppIcon>
                        {{ $t('views.application.generateDialog.label') }}
                      </el-button>
                    </div>
                  </template>
                  <MdEditorMagnify
                    :title="$t('views.application.form.roleSettings.label')"
                    v-model="applicationForm.model_setting.system"
                    style="height: 120px"
                    @submitDialog="submitSystemDialog"
                    :placeholder="
                      $t('views.application.form.roleSettings.placeholder', {
                        data: '{data}',
                        question: '{question}',
                        memory: '{memory}',
                      })
                    "
                  />
                </el-form-item>
                <el-form-item
                  prop="model_setting.no_references_prompt"
                  :rules="{
                    required: applicationForm.model_id,
                    message: $t('views.application.form.prompt.requiredMessage'),
                    trigger: 'blur',
                  }"
                >
                  <template #label>
                    <div class="flex align-center">
                      <span class="mr-4"
                        >{{
                          $t('views.application.form.prompt.label') +
                          $t('views.application.form.prompt.noReferences')
                        }}
                      </span>
                      <el-tooltip
                        effect="dark"
                        :content="$t('views.application.form.prompt.tooltip')"
                        placement="right"
                        popper-class="max-w-350"
                      >
                        <AppIcon iconName="app-warning" class="app-warning-icon"></AppIcon>
                      </el-tooltip>
                      <span class="color-danger ml-4" v-if="applicationForm.model_id">*</span>
                    </div>
                  </template>

                  <MdEditorMagnify
                    :title="
                      $t('views.application.form.prompt.label') +
                      $t('views.application.form.prompt.noReferences')
                    "
                    v-model="applicationForm.model_setting.no_references_prompt"
                    style="height: 120px"
                    @submitDialog="submitNoReferencesPromptDialog"
                    :placeholder="
                      $t('views.application.form.prompt.placeholder', {
                        data: '{data}',
                        question: '{question}',
                      })
                    "
                  />
                </el-form-item>
                <el-form-item
                  :label="$t('views.application.form.historyRecord.label')"
                  @click.prevent
                >
                  <el-input-number
                    v-model="applicationForm.dialogue_number"
                    :min="0"
                    :value-on-clear="0"
                    controls-position="right"
                    class="w-full"
                    :step="1"
                    :step-strictly="true"
                  />
                </el-form-item>
                <el-form-item>
                  <template #label>
                    <div class="flex-between">
                      <div class="flex align-center">
                        <span class="mr-4">{{ $t('views.application.longTermMemory.title') }}</span>
                        <el-tooltip
                          effect="dark"
                          :content="longTermPrompt"
                          placement="right"
                          popper-class="max-w-350"
                        >
                          <AppIcon iconName="app-warning" class="app-warning-icon"></AppIcon>
                        </el-tooltip>
                      </div>
                      <div>
                        <el-button
                          v-if="applicationForm.long_term_enable"
                          type="primary"
                          link
                          @click="openLongTermConfigDialog"
                        >
                          <AppIcon iconName="app-setting" class="mr-4"></AppIcon>
                        </el-button>
                        <el-switch
                          class="ml-8"
                          size="small"
                          v-model="applicationForm.long_term_enable"
                          @change="switchLongTerm"
                        />
                      </div>
                    </div>
                  </template>
                  <div v-if="applicationForm.long_term_enable" class="flex-between w-full">
                    <ModelSelect
                      v-model="applicationForm.long_term_model_id"
                      :placeholder="$t('views.application.form.aiModel.placeholder')"
                      :options="modelOptions"
                      @change="long_term_model_change"
                      @submitModel="getSelectModel"
                      showFooter
                      :model-type="'LLM'"
                    >
                    </ModelSelect>
                    <el-button
                      class="ml-8"
                      :disabled="!applicationForm.long_term_model_id"
                      @click="openLongTermParamSettingDialog"
                      @refreshForm="refreshParam"
                    >
                      <el-icon>
                        <Operation />
                      </el-icon>
                    </el-button>
                  </div>
                </el-form-item>

                <p class="mb-12 lighter">
                  {{ $t('views.knowledge.title') }}
                </p>

                <!-- 知识库 -->
                <el-card shadow="never" class="card-never" style="--el-card-padding: 12px">
                  <el-form-item
                    :label="$t('views.application.form.prompt.label')"
                    prop="model_setting.prompt"
                    :rules="{
                      required: applicationForm.model_id,
                      message: $t('views.application.form.prompt.requiredMessage'),
                      trigger: 'blur',
                    }"
                  >
                    <template #label>
                      <div
                        class="flex align-center cursor"
                        @click="collapseData.prompt = !collapseData.prompt"
                      >
                        <el-icon
                          class="mr-8 arrow-icon"
                          :class="collapseData.prompt ? 'rotate-90' : ''"
                        >
                          <CaretRight />
                        </el-icon>
                        <span class="mr-4">
                          {{ $t('views.application.form.prompt.label') }}
                          {{ $t('views.application.form.prompt.references') }}
                        </span>
                        <el-tooltip
                          effect="dark"
                          :content="$t('views.application.form.prompt.tooltip')"
                          popper-class="max-w-350"
                          placement="right"
                        >
                          <AppIcon iconName="app-warning" class="app-warning-icon"></AppIcon>
                        </el-tooltip>
                        <span class="color-danger ml-4" v-if="applicationForm.model_id">*</span>
                      </div>
                    </template>

                    <MdEditorMagnify
                      v-if="collapseData.prompt"
                      :title="
                        $t('views.application.form.prompt.label') +
                        $t('views.application.form.prompt.references')
                      "
                      v-model="applicationForm.model_setting.prompt"
                      style="height: 150px"
                      @submitDialog="submitPromptDialog"
                      :placeholder="
                        $t('views.application.form.prompt.placeholder', {
                          data: '{data}',
                          question: '{question}',
                        })
                      "
                    />
                  </el-form-item>
                  <div
                    class="flex-between mb-12 cursor"
                    @click="collapseData.knowledge_setting = !collapseData.knowledge_setting"
                  >
                    <div class="flex align-center">
                      <el-icon
                        class="mr-8 arrow-icon"
                        :class="collapseData.knowledge_setting ? 'rotate-90' : ''"
                      >
                        <CaretRight />
                      </el-icon>
                      <span class="lighter">{{
                        $t('views.application.form.relatedKnowledge.label')
                      }}</span>
                    </div>

                    <div>
                      <span class="mr-4">
                        <el-button type="primary" link @click="openParamSettingDialog">
                          <AppIcon iconName="app-setting"></AppIcon>
                        </el-button>
                      </span>

                      <el-button type="primary" link @click="openKnowledgeDialog">
                        <AppIcon iconName="app-add-outlined"></AppIcon>
                      </el-button>
                    </div>
                  </div>
                  <div class="w-full" v-if="collapseData.knowledge_setting">
                    <el-text type="info" v-if="applicationForm.knowledge_id_list?.length === 0"
                      >{{ $t('views.application.form.relatedKnowledge.placeholder') }}
                    </el-text>
                    <div v-else>
                      <template
                        v-for="(item, index) in applicationForm.knowledge_id_list"
                        :key="index"
                      >
                        <div
                          class="flex-between border border-r-6 white-bg mb-4"
                          style="padding: 5px 8px"
                        >
                          <div class="flex align-center" style="width: 80%">
                            <KnowledgeIcon
                              :type="relatedObject(knowledgeList, item, 'id')?.type"
                              class="mr-8"
                              :size="20"
                              style="--el-avatar-border-radius: 6px"
                            />

                            <span
                              class="ellipsis cursor"
                              :title="relatedObject(knowledgeList, item, 'id')?.name"
                            >
                              {{ relatedObject(knowledgeList, item, 'id')?.name }}</span
                            >
                          </div>
                          <el-button text @click="removeKnowledge(item)">
                            <el-icon><Close /></el-icon>
                          </el-button>
                        </div>
                      </template>
                    </div>
                  </div>
                </el-card>
                <!-- 开场白 -->
                <el-form-item :label="$t('views.application.form.prologue')">
                  <MdEditorMagnify
                    :title="$t('views.application.form.prologue')"
                    v-model="applicationForm.prologue"
                    style="height: 150px"
                    @submitDialog="submitPrologueDialog"
                  />
                </el-form-item>

                <el-form-item @click.prevent>
                  <template #label>
                    <div class="flex-between">
                      <span class="mr-4">
                        {{ $t('views.application.form.reasoningContent.label') }}
                      </span>

                      <div class="flex">
                        <el-button type="primary" link @click="openReasoningParamSettingDialog">
                          <AppIcon iconName="app-setting"></AppIcon>
                        </el-button>
                        <el-switch
                          class="ml-8"
                          size="small"
                          v-model="applicationForm.model_setting.reasoning_content_enable"
                        />
                      </div>
                    </div>
                  </template>
                </el-form-item>

              </el-form>
            </el-scrollbar>
          </div>
        </el-col>

        <!-- 预览 -->
        <el-col :span="14" class="p-24 border-l">
          <h4 class="title-decoration-1 mb-16">
            {{ $t('views.application.appTest') }}
          </h4>
          <div class="dialog-bg">
            <div class="scrollbar-height">
              <AiChat :applicationDetails="applicationForm" :type="'debug-ai-chat'"></AiChat>
            </div>
          </div>
        </el-col>
      </el-row>
    </el-card>

    <AIModeParamSettingDialog ref="AIModeParamSettingDialogRef" @refresh="refreshForm" />
    <AIModeParamSettingDialog
      ref="LongTermModeParamSettingDialogRef"
      @refresh="refreshLongTermForm"
    />
    <GeneratePromptDialog @replace="replace" ref="GeneratePromptDialogRef" />
    <ParamSettingDialog ref="ParamSettingDialogRef" @refresh="refreshParam" />
    <AddKnowledgeDialog
      ref="AddKnowledgeDialogRef"
      @addData="addKnowledge"
      :data="knowledgeList"
      :loading="knowledgeLoading"
    />
    <ReasoningParamSettingDialog
      ref="ReasoningParamSettingDialogRef"
      @refresh="submitReasoningDialog"
    />
    <LongTermSettingDialog ref="LongTermSettingDialogRef" @refresh="submitLongTermSettingDialog" />
  </div>
</template>
<script setup lang="ts">
import { reactive, ref, onMounted, computed, onBeforeMount } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { groupBy, set } from 'lodash'
import AIModeParamSettingDialog from './component/AIModeParamSettingDialog.vue'
import GeneratePromptDialog from './component/GeneratePromptDialog.vue'
import ParamSettingDialog from './component/ParamSettingDialog.vue'
import AddKnowledgeDialog from './component/AddKnowledgeDialog.vue'
import type { FormInstance, FormRules } from 'element-plus'
import type { ApplicationFormType } from '@/api/type/application'
import { relatedObject } from '@/utils/array'
import { MsgSuccess, MsgWarning } from '@/utils/message'
import { t } from '@/locales'
import ReasoningParamSettingDialog from './component/ReasoningParamSettingDialog.vue'
import permissionMap from '@/permission'
import { EditionConst } from '@/utils/permission/data'
import { hasPermission } from '@/utils/permission/index'
import { loadSharedApi } from '@/utils/dynamics-api/shared-api'
import useStore from '@/stores'
import LongTermSettingDialog from '@/views/application/component/LongTermSettingDialog.vue'
const route = useRoute()
const router = useRouter()
const {
  params: { id },
} = route as any
const { user, folder } = useStore()

const apiType = computed(() => {
  if (route.path.includes('resource-management')) {
    return 'systemManage'
  } else {
    return 'workspace'
  }
})
const permissionPrecise = computed(() => {
  return permissionMap['application'][apiType.value]
})

const defaultPrompt = t('views.application.form.prompt.defaultPrompt', {
  data: '{data}',
  question: '{question}',
})

const optimizationPrompt =
  t('views.application.dialog.defaultPrompt1', {
    question: '{question}',
  }) +
  '<data></data>' +
  t('views.application.dialog.defaultPrompt2')

const longTermPrompt =
  t('views.application.longTermMemory.tips1') +
  '{memory}' +
  t('views.application.longTermMemory.tips2')

const collapseData = reactive({
  prompt: true,
  knowledge_setting: true,
  MCP: true,
  tool: true,
  skill: true,
  agent: true,
})
const AIModeParamSettingDialogRef = ref<InstanceType<typeof AIModeParamSettingDialog>>()
const LongTermModeParamSettingDialogRef = ref<InstanceType<typeof AIModeParamSettingDialog>>()
const LongTermSettingDialogRef = ref<InstanceType<typeof LongTermSettingDialog>>()
const ReasoningParamSettingDialogRef = ref<InstanceType<typeof ReasoningParamSettingDialog>>()
const ParamSettingDialogRef = ref<InstanceType<typeof ParamSettingDialog>>()
const GeneratePromptDialogRef = ref<InstanceType<typeof GeneratePromptDialog>>()

const applicationFormRef = ref<FormInstance>()
const AddKnowledgeDialogRef = ref()

const loading = ref(false)
const knowledgeLoading = ref(false)

const applicationForm = ref<ApplicationFormType>({
  name: '',
  desc: '',
  model_id: '',
  dialogue_number: 1,
  prologue: t('views.application.form.defaultPrologue'),
  knowledge_id_list: [],
  knowledge_setting: {
    top_n: 3,
    similarity: 0.6,
    max_paragraph_char_number: 5000,
    search_mode: 'embedding',
    no_references_setting: {
      status: 'ai_questioning',
      value: '{question}',
    },
  },
  model_setting: {
    prompt: defaultPrompt,
    system: '',
    no_references_prompt: '{question}',
    reasoning_content_enable: false,
  },
  model_params_setting: {},
  problem_optimization: false,
  problem_optimization_prompt: optimizationPrompt,
  long_term_enable: false,
  long_term_model_id: '',
  long_term_model_params_setting: {},
  long_term_trigger_setting: { rounds: 10 },
  long_term_trigger_type: 'ROUND',
})

const rules = reactive<FormRules<ApplicationFormType>>({
  name: [
    {
      required: true,
      message: t('views.application.form.appName.placeholder'),
      trigger: 'blur',
    },
  ],
})
const modelOptions = ref<any>(null)
const knowledgeList = ref<Array<any>>([])

function submitPrologueDialog(val: string) {
  applicationForm.value.prologue = val
}
function submitPromptDialog(val: string) {
  applicationForm.value.model_setting.prompt = val
}
function submitNoReferencesPromptDialog(val: string) {
  applicationForm.value.model_setting.no_references_prompt = val
}
function submitSystemDialog(val: string) {
  applicationForm.value.model_setting.system = val
}
function submitReasoningDialog(val: any) {
  applicationForm.value.model_setting = {
    ...applicationForm.value.model_setting,
    ...val,
  }
}
const publish = (formEl: FormInstance | undefined) => {
  if (!formEl) return
  formEl.validate().then(() => {
    return loadSharedApi({ type: 'application', systemType: apiType.value })
      .putApplication(id, applicationForm.value, loading)
      .then(() => {
        return loadSharedApi({ type: 'application', systemType: apiType.value }).publish(
          id,
          {},
          loading,
        )
      })
      .then(() => {
        MsgSuccess(t('views.application.tip.publishSuccess'))
      })
  })
}
const submit = async (formEl: FormInstance | undefined) => {
  if (!formEl) return
  await formEl.validate((valid, fields) => {
    if (valid) {
      loadSharedApi({ type: 'application', systemType: apiType.value })
        .putApplication(id, applicationForm.value, loading)
        .then(() => {
          MsgSuccess(t('common.saveSuccess'))
        })
    }
  })
}
const model_change = (model_id?: string) => {
  applicationForm.value.model_id = model_id
  if (model_id) {
    AIModeParamSettingDialogRef.value?.reset_default(model_id, id)
  } else {
    refreshForm({})
  }
}

const long_term_model_change = (model_id?: string) => {
  applicationForm.value.long_term_model_id = model_id
  if (model_id) {
    LongTermModeParamSettingDialogRef.value?.reset_default(model_id, id)
  } else {
    refreshLongTermForm({})
  }
}

const openAIParamSettingDialog = () => {
  if (applicationForm.value.model_id) {
    AIModeParamSettingDialogRef.value?.open(
      applicationForm.value.model_id,
      id,
      applicationForm.value.model_params_setting,
    )
  }
}

const openLongTermParamSettingDialog = () => {
  if (applicationForm.value.long_term_model_id) {
    LongTermModeParamSettingDialogRef.value?.open(
      applicationForm.value.long_term_model_id,
      id,
      applicationForm.value.long_term_model_params_setting,
    )
  }
}

const openGeneratePromptDialog = () => {
  if (applicationForm.value.model_id) {
    GeneratePromptDialogRef.value?.open(applicationForm.value.model_id, id)
  }
}

const replace = (v: any) => {
  applicationForm.value.model_setting.system = v
}

const openReasoningParamSettingDialog = () => {
  ReasoningParamSettingDialogRef.value?.open(applicationForm.value.model_setting)
}

const openParamSettingDialog = () => {
  ParamSettingDialogRef.value?.open(applicationForm.value)
}

function openLongTermConfigDialog() {
  LongTermSettingDialogRef.value?.open(
    applicationForm.value.long_term_trigger_type,
    applicationForm.value.long_term_trigger_setting,
  )
}

function switchLongTerm() {
  if (applicationForm.value.long_term_enable) {
    applicationForm.value.model_setting.system = applicationForm.value.model_setting.system
  }
}

function submitLongTermSettingDialog(data: any) {
  applicationForm.value.long_term_trigger_type = data.trigger_type
  applicationForm.value.long_term_trigger_setting = data.trigger_setting
}

function refreshParam(data: any) {
  applicationForm.value = { ...applicationForm.value, ...data }
}

function refreshForm(data: any) {
  applicationForm.value.model_params_setting = data
}

function refreshLongTermForm(data: any) {
  applicationForm.value.long_term_model_params_setting = data
}

function removeKnowledge(id: any) {
  if (applicationForm.value.knowledge_id_list) {
    applicationForm.value.knowledge_id_list.splice(
      applicationForm.value.knowledge_id_list.indexOf(id),
      1,
    )
  }
}

function addKnowledge(val: Array<any>) {
  knowledgeList.value = val
  applicationForm.value.knowledge_id_list = val.map((item) => item.id)
}

function openKnowledgeDialog() {
  AddKnowledgeDialogRef.value.open(applicationForm.value.knowledge_id_list)
}

function getDetail() {
  loadSharedApi({ type: 'application', systemType: apiType.value })
    .getApplicationDetail(id, loading)
    .then((res: any) => {
      applicationForm.value = res.data
      applicationForm.value.model_id = res.data.model
      applicationForm.value.stt_model_id = res.data.stt_model
      applicationForm.value.tts_model_id = res.data.tts_model
      applicationForm.value.tts_type = res.data.tts_type
      applicationForm.value.long_term_model_id = res.data.long_term_model
      knowledgeList.value = res.data.knowledge_list
      applicationForm.value.model_setting.no_references_prompt =
        res.data.model_setting.no_references_prompt || '{question}'

      // 企业版和专业版
      if (hasPermission([EditionConst.IS_EE, EditionConst.IS_PE], 'OR')) {
        loadSharedApi({ type: 'application', systemType: apiType.value })
          .getApplicationSetting(id)
          .then((ok: any) => {
            applicationForm.value = { ...applicationForm.value, ...ok.data }
          })
      }
    })
}

function getSelectModel() {
  loading.value = true

  const obj =
    apiType.value === 'systemManage'
      ? {
          model_type: 'LLM',
          workspace_id: applicationForm.value?.workspace_id,
        }
      : {
          model_type: 'LLM',
        }
  loadSharedApi({ type: 'model', systemType: apiType.value })
    .getSelectModelList(obj)
    .then((res: any) => {
      modelOptions.value = groupBy(res?.data, 'provider')
      loading.value = false
    })
    .catch(() => {
      loading.value = false
    })
}

onMounted(() => {
  getSelectModel()
  getDetail()
})
</script>
<style lang="scss" scoped>
.application-setting {
  .relate-knowledge-card {
    color: var(--app-text-color);
  }

  .dialog-bg {
    border-radius: 8px;
    background: var(--dialog-bg-gradient-color);
    overflow: hidden;
    box-sizing: border-box;
  }

  .scrollbar-height-left {
    height: calc(var(--app-main-height) - 64px);
  }

  .scrollbar-height {
    padding-top: 16px;
    height: calc(var(--app-main-height) - 96px);
  }
}

.prologue-md-editor {
  height: 150px;
}
</style>
