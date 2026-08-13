<template>
  <el-row :gutter="16" v-loading.fullscreen.lock="importLoading">
    <el-col
      :xs="12"
      :sm="12"
      :md="12"
      :lg="6"
      :xl="6"
      class="mb-16"
      v-if="permissionPrecise.application.workspace.create()"
    >
      <el-dropdown
        trigger="hover"
        class="w-full"
        @visible-change="(visible: boolean) => handleVisibleChange('application', visible)"
      >
        <el-card shadow="never" class="cursor w-full quick-create-card">
          <div class="flex-between">
            <div class="flex align-center">
              <img src="@/assets/home/icon_create-agent.svg" alt="" />
              <div class="ml-8">
                <p>{{ $t('home.createAgent') }}</p>
                <p class="color-secondary font-small mt-8 lighter">
                  {{ $t('home.createAgentDescribe') }}
                </p>
              </div>
            </div>
            <el-icon
              class="arrow-icon"
              :class="{ 'rotate-180': isDropdownVisible === 'application' }"
              ><ArrowDown
            /></el-icon>
          </div>
        </el-card>
        <template #dropdown>
          <el-dropdown-menu class="create-dropdown">
            <el-dropdown-item @click="openCreateApplicationDialog()">
              <div class="flex">
                <el-avatar shape="square" class="avatar-blue mt-4" :size="32">
                  <img
                    src="@/assets/application/icon_simple_application.svg"
                    style="width: 65%"
                    alt=""
                  />
                </el-avatar>
                <div class="pre-wrap ml-8">
                  <div class="lighter">
                    {{ $t('views.application.simpleAgent') }}
                  </div>
                  <el-text type="info" size="small" class="color-secondary"
                    >{{ $t('views.application.simplePlaceholder') }}
                  </el-text>
                </div>
              </div>
            </el-dropdown-item>
          </el-dropdown-menu>
        </template>
      </el-dropdown>
    </el-col>
    <el-col
      :xs="12"
      :sm="12"
      :md="12"
      :lg="6"
      :xl="6"
      class="mb-16"
      v-if="permissionPrecise.knowledge.workspace.create()"
    >
      <el-dropdown
        trigger="hover"
        class="w-full"
        @visible-change="(visible: boolean) => handleVisibleChange('knowledge', visible)"
      >
        <el-card shadow="never" class="cursor w-full quick-create-card">
          <div class="flex-between">
            <div class="flex align-center">
              <img src="@/assets/home/icon_create-knowledge.svg" alt="" />
              <div class="ml-8">
                <p>{{ $t('home.createKnowledge') }}</p>
                <p class="color-secondary font-small mt-8 lighter">
                  {{ $t('home.createKnowledgeDescribe') }}
                </p>
              </div>
            </div>
            <el-icon class="arrow-icon" :class="{ 'rotate-180': isDropdownVisible === 'knowledge' }"
              ><ArrowDown
            /></el-icon>
          </div>
        </el-card>
        <template #dropdown>
          <el-dropdown-menu class="create-dropdown">
            <el-dropdown-item @click="openCreateKnowledgeDialog(CreateKnowledgeDialog)">
              <div class="flex">
                <el-avatar class="avatar-blue mt-4" shape="square" :size="32">
                  <img src="@/assets/knowledge/icon_document.svg" style="width: 58%" alt="" />
                </el-avatar>
                <div class="pre-wrap ml-8">
                  <div class="lighter">
                    {{ $t('views.knowledge.knowledgeType.generalKnowledge') }}
                  </div>
                  <el-text type="info" size="small" class="color-secondary"
                    >{{ $t('views.knowledge.knowledgeType.generalInfo') }}
                  </el-text>
                </div>
              </div>
            </el-dropdown-item>
            <el-dropdown-item @click="openCreateKnowledgeDialog(CreateWebKnowledgeDialog)">
              <div class="flex">
                <el-avatar class="avatar-purple mt-4" shape="square" :size="32">
                  <img src="@/assets/knowledge/icon_web.svg" style="width: 58%" alt="" />
                </el-avatar>
                <div class="pre-wrap ml-8">
                  <div class="lighter">
                    {{ $t('views.knowledge.knowledgeType.webKnowledge') }}
                  </div>
                  <el-text type="info" size="small" class="color-secondary"
                    >{{ $t('views.knowledge.knowledgeType.webInfo') }}
                  </el-text>
                </div>
              </div>
            </el-dropdown-item>
            <el-dropdown-item
              @click="openCreateKnowledgeDialog(CreateLarkKnowledgeDialog)"
              v-if="user.isPE() || user.isEE()"
            >
              <div class="flex">
                <el-avatar
                  class="avatar-purple mt-4"
                  shape="square"
                  :size="32"
                  style="background: none"
                >
                  <img src="@/assets/knowledge/logo_lark.svg" alt="" />
                </el-avatar>
                <div class="pre-wrap ml-8">
                  <div class="lighter">
                    {{ $t('views.knowledge.knowledgeType.larkKnowledge') }}
                  </div>
                  <el-text type="info" size="small" class="color-secondary"
                    >{{ $t('views.knowledge.knowledgeType.larkInfo') }}
                  </el-text>
                </div>
              </div>
            </el-dropdown-item>
            <el-upload
              ref="importKnowledgeUploadRef"
              :file-list="[]"
              action="#"
              multiple
              :auto-upload="false"
              :show-file-list="false"
              :limit="1"
              accept=".zip"
              :on-change="(file: any) => importKnowledgeBundle(file)"
              class="import-button"
            >
              <el-dropdown-item>
                <div class="flex align-center w-full">
                  <el-avatar shape="square" :size="32" style="background: none">
                    <img src="@/assets/icon_import.svg" alt="" />
                  </el-avatar>
                  <div class="pre-wrap ml-8">
                    <div class="lighter">{{ $t('common.importCreate') }}</div>
                  </div>
                </div>
              </el-dropdown-item>
            </el-upload>
          </el-dropdown-menu>
        </template>
      </el-dropdown>
    </el-col>
  </el-row>
  <!-- 智能体dialog -->
  <CreateApplicationDialog ref="CreateApplicationDialogRef" />

  <!-- 知识库dialog -->
  <component :is="currentCreateDialog" ref="CreateKnowledgeDialogRef" />
  <!-- 模型dialog-->
  <CreateModelDialog
    ref="createModelRef"
    @submit="modelRefresh"
    @change="openCreateModel($event)"
  ></CreateModelDialog>

  <SelectProviderDialog
    ref="selectProviderRef"
    @change="(provider, modelType) => openCreateModel(provider, modelType)"
  ></SelectProviderDialog>
</template>
<script setup lang="ts">
import { ref, shallowRef, nextTick, computed } from 'vue'
import CreateApplicationDialog from '@/views/application/component/CreateApplicationDialog.vue'
import CreateKnowledgeDialog from '@/views/knowledge/create-component/CreateKnowledgeDialog.vue'
import CreateWebKnowledgeDialog from '@/views/knowledge/create-component/CreateWebKnowledgeDialog.vue'
import CreateLarkKnowledgeDialog from '@/views/knowledge/create-component/CreateLarkKnowledgeDialog.vue'
import knowledgeApi from '@/api/knowledge/knowledge'
import CreateModelDialog from '@/views/model/component/CreateModelDialog.vue'
import SelectProviderDialog from '@/views/model/component/SelectProviderDialog.vue'
import type { Provider, Model } from '@/api/type/model'
import { allObj } from '@/views/model/component/data'
import { MsgSuccess, MsgConfirm, MsgError } from '@/utils/message'
import { useRouter, useRoute } from 'vue-router'
import useStore from '@/stores'
import { t } from '@/locales'
import permissionMap from '@/permission'
const { user, tool } = useStore()
const router = useRouter()
const props = defineProps({
  data: {
    type: Array,
    default: () => [],
  },
  tokenUsage: {
    type: Array,
    default: () => [],
  },
  topQuestions: {
    type: Array,
    default: () => [],
  },
})

const permissionPrecise = computed(() => {
  return permissionMap
})

const importLoading = ref(false)

// 智能体快捷方式

const isDropdownVisible = ref('')

const handleVisibleChange = (val: string, visible: boolean) => {
  isDropdownVisible.value = visible ? val : ''
}
const CreateApplicationDialogRef = ref()

function openCreateApplicationDialog() {
  CreateApplicationDialogRef.value.open(user.getWorkspaceId() ?? 'default')
}

// 知识库快捷方式
const CreateKnowledgeDialogRef = ref()
const currentCreateDialog = shallowRef<any>(null)

function openCreateKnowledgeDialog(data: any) {
  currentCreateDialog.value = data
  nextTick(() => {
    CreateKnowledgeDialogRef.value.open({ id: user.getWorkspaceId() ?? 'default' })
  })
}

const importKnowledgeUploadRef = ref()

function importKnowledgeBundle(file: any) {
  const formData = new FormData()
  formData.append('file', file.raw)
  const folderId = user.getWorkspaceId() ?? 'default'
  formData.append('folder_id', folderId)
  importKnowledgeUploadRef.value.clearFiles()

  knowledgeApi
    .importKnowledgeBundle(formData, importLoading)
    .then(async (res: any) => {
      if (res?.data) {
        const knowledgeId = res.data.knowledge_id
        const knowledgeType = res.data.type
        const folderId = user.getWorkspaceId() ?? 'default'
        await user.profile()
        router.push({
          path: `/knowledge/${knowledgeId}/${folderId}/${knowledgeType}/document`,
          query: { imported: 'true' },
        })
      }
    })
    .catch((e: any) => {
      if (e.code === 400) {
        MsgConfirm(t('common.tip'), t('views.application.tip.professionalMessage'), {
          cancelButtonText: t('common.confirm'),
          confirmButtonText: t('common.professional'),
        }).then(() => {
          window.open('https://maxkb.cn/pricing.html', '_blank')
        })
      }
    })
}

// 模型快捷方式
const createModelRef = ref<InstanceType<typeof CreateModelDialog>>()
const selectProviderRef = ref<InstanceType<typeof SelectProviderDialog>>()
const openCreateModel = (provider?: Provider, model_type?: string) => {
  if (provider && provider.provider) {
    createModelRef.value?.open(provider, model_type)
  } else {
    selectProviderRef.value?.open()
  }
}
function modelRefresh() {
  router.push({ path: `/model` })
}
</script>
<style lang="scss" scoped>
.quick-create-card {
  &:hover {
    background: rgba(31, 35, 41, 0.1);
  }
}
</style>
