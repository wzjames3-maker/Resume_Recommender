<template>
  <div class="hr-page p-16-24">
    <div class="flex-between mb-16">
      <div>
        <h2>候选人</h2>
        <span class="color-secondary">维护招聘候选人与职位指派</span>
      </div>
      <div class="flex gap-12">
        <el-button v-if="isHrOperator" plain @click="openResumeUpload()">上传简历</el-button>
        <el-button v-if="isHrAdmin" plain @click="aiSettingVisible = true">AI 设置</el-button>
        <el-button plain @click="router.push('/hr/search')">语义检索</el-button>
        <el-button v-if="isHrAdmin" plain :loading="exporting" @click="exportCandidates">导出</el-button>
        <el-button v-if="isHrAdmin" plain @click="importDialogVisible = true">批量导入</el-button>
        <el-button v-if="isHrOperator" type="primary" @click="openCandidateDialog()">新建候选人</el-button>
      </div>
      <input ref="resumeInputRef" type="file" multiple accept=".docx,.txt" class="hidden-input" @change="handleResumeFiles" />
    </div>

    <el-card style="--el-card-padding: 0" v-loading="loading">
      <div class="p-16 border-b flex gap-12">
        <el-input v-model="filters.name" placeholder="按姓名搜索" clearable @change="refresh" />
        <el-input v-model="filters.city" placeholder="按城市搜索" clearable @change="refresh" />
        <el-input v-model="filters.skills" placeholder="按技能搜索" clearable @change="refresh" />
        <el-input-number v-model="filters.years_min" :min="0" :max="99" placeholder="最低年限" @change="refresh" style="width: 140px" />
        <el-input-number v-model="filters.years_max" :min="0" :max="99" placeholder="最高年限" @change="refresh" style="width: 140px" />
        <el-select v-model="filters.highest_degree" placeholder="学历" clearable @change="refresh" style="width: 120px">
          <el-option v-for="degree in highestDegreeOptions" :key="degree" :label="degree" :value="degree" />
        </el-select>
        <el-select v-model="filters.source" placeholder="来源" clearable @change="refresh" style="width: 140px">
          <el-option v-for="(label, value) in channelLabels" :key="value" :label="label" :value="value" />
        </el-select>
        <el-select v-model="filters.status" placeholder="状态" clearable @change="refresh" style="width: 140px">
          <el-option label="在库" value="ACTIVE" />
          <el-option label="已归档" value="ARCHIVED" />
        </el-select>
        <el-button :type="filters.owner_id ? 'primary' : 'default'" plain @click="toggleMyCandidates">待我处理</el-button>
        <el-input v-if="isHrOperator" v-model="aiQuery" placeholder="AI 搜索：如 找 3 年以上 Python 经验在上海的人" clearable @keyup.enter="aiSearch" style="width: 300px" />
        <el-button v-if="isHrOperator" type="primary" plain :loading="aiSearching" @click="aiSearch">AI 搜索</el-button>
      </div>

      <AppTable :data="candidates" :pagination-config="pagination" @change-page="loadCandidates" @size-change="refresh">
        <el-table-column label="姓名" min-width="170">
          <template #default="{ row }">
            <div class="flex align-center gap-4">
              <span class="candidate-name">{{ row.name }}</span>
              <el-tooltip v-if="complianceMissing(row).length" :content="`合规信息缺失：${complianceMissing(row).join('、')}`" placement="top">
                <el-tag type="warning" size="small" effect="plain">合规待补</el-tag>
              </el-tooltip>
            </div>
          </template>
        </el-table-column>
        <el-table-column label="城市" min-width="150">
          <template #default="{ row }">{{ row.current_city || '-' }} <span v-if="row.target_city">→ {{ row.target_city }}</span></template>
        </el-table-column>
        <el-table-column prop="years_experience" label="经验" width="90">
          <template #default="{ row }">{{ row.years_experience == null ? '-' : `${row.years_experience} 年` }}</template>
        </el-table-column>
        <el-table-column label="技能" min-width="180" show-overflow-tooltip>
          <template #default="{ row }">{{ row.skills.join('、') || '-' }}</template>
        </el-table-column>
        <el-table-column label="重复" width="110">
          <template #default="{ row }">
            <el-tooltip v-if="row.duplicate_ids?.length" :content="`与 ${row.duplicate_ids.length} 名候选人重复`" placement="top">
              <el-tag type="warning" size="small">疑似重复</el-tag>
            </el-tooltip>
          </template>
        </el-table-column>
        <el-table-column label="状态" width="100">
          <template #default="{ row }"><el-tag :type="row.status === 'ACTIVE' ? 'success' : 'info'">{{ row.status === 'ACTIVE' ? '在库' : '已归档' }}</el-tag></template>
        </el-table-column>
        <el-table-column label="操作" width="160" fixed="right">
          <template #default="{ row }">
            <el-button link type="primary" @click="router.push(`/hr/candidates/${row.id}`)">详情</el-button>
            <el-dropdown trigger="click" @command="(cmd: string) => handleRowCommand(cmd, row)">
              <el-button link type="primary">更多<el-icon class="el-icon--right"><arrow-down /></el-icon></el-button>
              <template #dropdown>
                <el-dropdown-menu>
                  <el-dropdown-item v-if="isHrAdmin" command="edit">编辑</el-dropdown-item>
                  <el-dropdown-item v-if="isHrOperator" command="assign" :disabled="row.status !== 'ACTIVE'">加入职位</el-dropdown-item>
                  <el-dropdown-item v-if="isHrAdmin" command="archive" :disabled="row.status !== 'ACTIVE'">归档</el-dropdown-item>
                  <el-dropdown-item v-if="isHrAdmin && row.status === 'ARCHIVED'" command="restore">恢复</el-dropdown-item>
                  <el-dropdown-item command="resumes">简历</el-dropdown-item>
                  <el-dropdown-item v-if="isHrAdmin" command="merge" :disabled="!row.duplicate_ids?.length">合并</el-dropdown-item>
                  <el-dropdown-item v-if="isHrAdmin" command="remove" divided>删除</el-dropdown-item>
                </el-dropdown-menu>
              </template>
            </el-dropdown>
          </template>
        </el-table-column>
      </AppTable>
    </el-card>

    <el-dialog v-model="candidateDialogVisible" :title="editingCandidate ? '编辑候选人' : '新建候选人'" width="640px">
      <el-form :model="candidateForm" label-width="96px" @submit.prevent>
        <el-form-item label="姓名" required><el-input v-model="candidateForm.name" maxlength="128" /></el-form-item>
        <el-row :gutter="16">
          <el-col :span="12"><el-form-item label="邮箱"><el-input v-model="candidateForm.email" /></el-form-item></el-col>
          <el-col :span="12"><el-form-item label="手机号"><el-input v-model="candidateForm.phone" /></el-form-item></el-col>
        </el-row>
        <el-row :gutter="16">
          <el-col :span="12"><el-form-item label="当前城市"><el-input v-model="candidateForm.current_city" /></el-form-item></el-col>
          <el-col :span="12"><el-form-item label="目标城市"><el-input v-model="candidateForm.target_city" /></el-form-item></el-col>
        </el-row>
        <el-row :gutter="16">
          <el-col :span="12"><el-form-item label="最高学历"><el-input v-model="candidateForm.highest_degree" /></el-form-item></el-col>
          <el-col :span="12"><el-form-item label="工作年限"><el-input-number v-model="candidateForm.years_experience" :min="0" :max="99" /></el-form-item></el-col>
        </el-row>
        <el-form-item label="技能"><el-input v-model="skillsText" placeholder="用逗号分隔，例如 Python, Django" /></el-form-item>
        <el-row :gutter="16">
          <el-col :span="12"><el-form-item label="来源类型"><el-select v-model="candidateForm.source_type" style="width: 100%"><el-option v-for="(label, value) in channelLabels" :key="value" :label="label" :value="value" /></el-select></el-form-item></el-col>
          <el-col :span="12"><el-form-item label="来源详情"><el-input v-model="candidateForm.source_detail" maxlength="128" /></el-form-item></el-col>
        </el-row>
        <el-row :gutter="16">
          <el-col :span="12"><el-form-item label="收集日期"><el-date-picker v-model="candidateForm.collected_at" type="datetime" style="width: 100%" value-format="YYYY-MM-DDTHH:mm:ss" /></el-form-item></el-col>
          <el-col :span="12"><el-form-item label="告知状态"><el-select v-model="candidateForm.consent_status" style="width: 100%"><el-option v-for="(label, value) in consentStatusLabels" :key="value" :label="label" :value="value" /></el-select></el-form-item></el-col>
        </el-row>
        <el-row :gutter="16">
          <el-col :span="12"><el-form-item label="告知版本"><el-input v-model="candidateForm.consent_version" maxlength="32" /></el-form-item></el-col>
          <el-col :span="12"><el-form-item label="联系偏好"><el-select v-model="candidateForm.contact_preference" style="width: 100%"><el-option v-for="(label, value) in contactPreferenceLabels" :key="value" :label="label" :value="value" /></el-select></el-form-item></el-col>
        </el-row>
        <el-form-item label="来源"><el-input v-model="candidateForm.source" /></el-form-item>
        <el-form-item label="备注"><el-input v-model="candidateForm.note" type="textarea" :rows="3" maxlength="4096" show-word-limit /></el-form-item>
      </el-form>
      <template #footer><el-button @click="candidateDialogVisible = false">取消</el-button><el-button type="primary" :loading="saving" @click="saveCandidate">保存</el-button></template>
    </el-dialog>

    <el-dialog v-model="candidateDetailVisible" title="候选人详情" width="640px">
      <el-descriptions :column="2" border>
        <el-descriptions-item label="姓名">{{ candidateDetail?.name }}</el-descriptions-item>
        <el-descriptions-item label="状态">
          <el-tag :type="candidateDetail?.status === 'ACTIVE' ? 'success' : 'info'" size="small">{{ candidateDetail?.status === 'ACTIVE' ? '在库' : '已归档' }}</el-tag>
        </el-descriptions-item>
        <el-descriptions-item label="邮箱">{{ candidateDetail?.email || '-' }}</el-descriptions-item>
        <el-descriptions-item label="手机号">{{ candidateDetail?.phone || '-' }}</el-descriptions-item>
        <el-descriptions-item label="当前城市">{{ candidateDetail?.current_city || '-' }}</el-descriptions-item>
        <el-descriptions-item label="目标城市">{{ candidateDetail?.target_city || '-' }}</el-descriptions-item>
        <el-descriptions-item label="最高学历">{{ candidateDetail?.highest_degree || '-' }}</el-descriptions-item>
        <el-descriptions-item label="工作年限">{{ candidateDetail?.years_experience == null ? '-' : `${candidateDetail.years_experience} 年` }}</el-descriptions-item>
        <el-descriptions-item label="来源">{{ candidateDetail?.source || '-' }}</el-descriptions-item>
        <el-descriptions-item label="创建时间">{{ candidateDetail ? new Date(candidateDetail.create_time).toLocaleString() : '-' }}</el-descriptions-item>
        <el-descriptions-item label="更新时间">{{ candidateDetail ? new Date(candidateDetail.update_time).toLocaleString() : '-' }}</el-descriptions-item>
        <el-descriptions-item label="技能" :span="2">
          <template v-if="candidateDetail?.skills?.length">
            <el-tag v-for="skill in candidateDetail.skills" :key="skill" size="small" class="mr-8 mb-8">{{ skill }}</el-tag>
          </template>
          <span v-else>-</span>
        </el-descriptions-item>
        <el-descriptions-item label="备注" :span="2">{{ candidateDetail?.note || '-' }}</el-descriptions-item>
      </el-descriptions>
      <div class="mt-16">
        <div class="mb-8 color-secondary">关联职位</div>
        <el-empty v-if="!candidateDetail?.assignments?.length" description="暂无关联职位" />
        <el-table v-else :data="candidateDetail.assignments" size="small">
          <el-table-column prop="job_name" label="职位" min-width="140" />
          <el-table-column label="指派状态" width="120">
            <template #default="{ row }">
              <el-tag :type="assignmentTagType(row.status)" size="small">{{ assignmentStatusLabels[row.status] || row.status }}</el-tag>
            </template>
          </el-table-column>
          <el-table-column label="关系类型" width="90">
            <template #default="{ row }">{{ relationTypeLabels[row.relation_type] || row.relation_type || '-' }}</template>
          </el-table-column>
          <el-table-column label="渠道" width="90">
            <template #default="{ row }">{{ channelLabels[row.channel] || row.channel || '-' }}</template>
          </el-table-column>
          <el-table-column label="负责人" width="100">
            <template #default="{ row }">{{ memberName(row.owner_id) || '-' }}</template>
          </el-table-column>
          <el-table-column prop="note" label="备注" show-overflow-tooltip />
        </el-table>
      </div>
      <template #footer>
        <el-button @click="candidateDetailVisible = false">关闭</el-button>
        <el-button v-if="isHrAdmin && candidateDetail?.status === 'ARCHIVED'" type="success" @click="restore(candidateDetail)">恢复</el-button>
      </template>
    </el-dialog>

    <el-dialog v-model="importDialogVisible" title="批量导入候选人" width="720px">
      <div class="mb-16">
        <el-button link type="primary" @click="downloadImportTemplate">下载 CSV 模板</el-button>
        <span class="ml-8 color-secondary">UTF-8 编码，最多 200 行，必填列：name</span>
      </div>
      <el-upload
        drag
        accept=".csv"
        :auto-upload="false"
        :limit="1"
        :on-change="handleImportFile"
        :on-remove="() => (importFile = null)"
      >
        <div class="el-upload__text">拖拽 CSV 到此处，或<em>点击选择文件</em></div>
      </el-upload>
      <div v-if="importReport" class="mt-16">
        <div class="mb-8">
          <el-tag type="success" class="mr-8">成功 {{ importReport.success }}</el-tag>
          <el-tag type="warning" class="mr-8">疑似重复 {{ importReport.duplicates }}</el-tag>
          <el-tag type="danger">失败 {{ importReport.failed }}</el-tag>
        </div>
        <el-table :data="importReport.records" size="small" max-height="260">
          <el-table-column prop="row_no" label="行号" width="60" />
          <el-table-column prop="name" label="姓名" min-width="100" />
          <el-table-column label="结果" width="100">
            <template #default="{ row }">
              <el-tag :type="row.status === 'created' ? 'success' : row.status === 'duplicate' ? 'warning' : 'danger'" size="small">
                {{ row.status === 'created' ? '已创建' : row.status === 'duplicate' ? '疑似重复' : '失败' }}
              </el-tag>
            </template>
          </el-table-column>
          <el-table-column prop="reason" label="原因" min-width="200" show-overflow-tooltip />
        </el-table>
      </div>
      <template #footer>
        <el-button @click="importDialogVisible = false">关闭</el-button>
        <el-button type="primary" :disabled="!importFile" :loading="importing" @click="submitImport">开始导入</el-button>
      </template>
    </el-dialog>

    <el-dialog v-model="uploadDialogVisible" title="上传简历" width="520px">
      <el-form label-width="96px">
        <el-form-item label="来源渠道">
          <el-select v-model="uploadChannel" style="width: 100%">
            <el-option v-for="(label, value) in channelLabels" :key="value" :label="label" :value="value" />
          </el-select>
        </el-form-item>
        <el-form-item label="上传结果">
          <div class="w-full">
            <div v-for="record in uploadResults" :key="record.resume_id" class="upload-result">
              <el-tag :type="record.status === 'SUCCESS' ? 'success' : record.status === 'FAILED' ? 'danger' : 'info'" size="small">
                {{ record.status === 'SUCCESS' ? '成功' : record.status === 'FAILED' ? '失败' : '解析中' }}
              </el-tag>
              <span class="ml-8">{{ record.file_name }}</span>
              <span v-if="record.duplicate" class="ml-8 color-secondary">重复，已关联既有候选人</span>
              <span v-if="record.status === 'FAILED'" class="ml-8 color-secondary">{{ record.error_message }}</span>
            </div>
          </div>
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="uploadDialogVisible = false">关闭</el-button>
        <el-button type="primary" @click="openResumeUpload()">继续上传</el-button>
      </template>
    </el-dialog>

    <el-dialog v-model="assignmentDialogVisible" title="加入职位" width="480px">
      <el-form label-width="96px">
        <el-form-item label="候选人"><span>{{ assigningCandidate?.name }}</span></el-form-item>
        <el-form-item label="开放职位"><el-select v-model="selectedJobId" filterable placeholder="选择职位" style="width: 100%"><el-option v-for="job in openJobs" :key="job.id" :label="`${job.name}${job.city ? ` · ${job.city}` : ''}`" :value="job.id" /></el-select></el-form-item>
        <el-form-item label="关系类型">
          <el-select v-model="assignmentRelationType" style="width: 100%">
            <el-option v-for="(label, value) in relationTypeLabels" :key="value" :label="label" :value="value" />
          </el-select>
        </el-form-item>
        <el-form-item label="渠道">
          <el-select v-model="assignmentChannel" style="width: 100%">
            <el-option v-for="(label, value) in channelLabels" :key="value" :label="label" :value="value" />
          </el-select>
        </el-form-item>
        <el-form-item label="负责人">
          <el-select v-model="assignmentOwnerId" clearable filterable placeholder="选择负责人" style="width: 100%">
            <el-option v-for="member in members" :key="member.id" :label="member.nick_name" :value="member.id" />
          </el-select>
        </el-form-item>
        <el-form-item label="备注"><el-input v-model="assignmentNote" type="textarea" :rows="3" /></el-form-item>
      </el-form>
      <template #footer><el-button @click="assignmentDialogVisible = false">取消</el-button><el-button type="primary" :disabled="!selectedJobId" :loading="saving" @click="createAssignment">确认加入</el-button></template>
    </el-dialog>

    <el-dialog v-model="resumeListVisible" title="简历" width="620px">
      <el-table :data="candidateResumes" size="small">
        <el-table-column prop="file_name" label="文件名" min-width="160" />
        <el-table-column prop="file_size" label="大小" width="90">
          <template #default="{ row }">{{ (row.file_size / 1024).toFixed(1) }} KB</template>
        </el-table-column>
        <el-table-column label="状态" width="90">
          <template #default="{ row }">
            <el-tag :type="row.status === 'SUCCESS' ? 'success' : row.status === 'FAILED' ? 'danger' : 'info'" size="small">
              {{ row.status === 'SUCCESS' ? '成功' : row.status === 'FAILED' ? '失败' : '解析中' }}
            </el-tag>
          </template>
        </el-table-column>
        <el-table-column label="索引" width="80">
          <template #default="{ row }">
            <el-tag v-if="row.document_id" type="success" size="small">已索引</el-tag>
            <el-tag v-else type="info" size="small">未索引</el-tag>
          </template>
        </el-table-column>
        <el-table-column prop="create_time" label="上传时间" min-width="150">
          <template #default="{ row }">{{ new Date(row.create_time).toLocaleString() }}</template>
        </el-table-column>
        <el-table-column label="操作" width="270">
          <template #default="{ row }">
            <el-button v-if="isHrOperator" link type="primary" size="small" :disabled="row.status !== 'SUCCESS'" @click="viewResumeContent(row)">查看</el-button>
            <el-button v-if="isHrOperator" link type="primary" size="small" @click="downloadResumeFile(row)">下载</el-button>
            <el-button v-if="isHrOperator" link type="primary" size="small" @click="openFlowLogs(row)">流转日志</el-button>
            <el-button v-if="isHrAdmin" link type="danger" size="small" @click="removeResume(row)">删除</el-button>
          </template>
        </el-table-column>
      </el-table>
      <template #footer><el-button @click="resumeListVisible = false">关闭</el-button></template>
    </el-dialog>

    <el-dialog v-model="resumeContentVisible" title="简历原文" width="640px">
      <pre class="resume-content">{{ resumeContent }}</pre>
    </el-dialog>

    <el-dialog v-model="flowLogVisible" title="简历流转日志" width="860px">
      <div v-loading="flowLogLoading" class="flow-log-wrapper">
      <el-alert
        v-if="!flowLogLoading && flowLogs.length === 0"
        title="暂无流转日志"
        type="info"
        :closable="false"
        class="mb-16"
      />
      <el-table v-else :data="flowLogs" size="small" max-height="480">
        <el-table-column label="节点" width="110">
          <template #default="{ row }">
            <el-tag :type="row.status === 'SUCCESS' ? 'success' : 'danger'" size="small">{{ flowLogNodeLabels[row.node] || row.node }}</el-tag>
          </template>
        </el-table-column>
        <el-table-column label="状态" width="80">
          <template #default="{ row }">{{ row.status === 'SUCCESS' ? '成功' : '失败' }}</template>
        </el-table-column>
        <el-table-column prop="create_time" label="时间" width="170">
          <template #default="{ row }">{{ new Date(row.create_time).toLocaleString() }}</template>
        </el-table-column>
        <el-table-column prop="document_id" label="文档 ID" min-width="150" show-overflow-tooltip>
          <template #default="{ row }">{{ row.document_id || '-' }}</template>
        </el-table-column>
        <el-table-column label="详情" min-width="220">
          <template #default="{ row }">
            <pre class="flow-log-detail">{{ formatFlowLogDetail(row.detail) }}</pre>
          </template>
        </el-table-column>
        <el-table-column label="错误" min-width="160" show-overflow-tooltip>
          <template #default="{ row }">{{ row.error_message || '-' }}</template>
        </el-table-column>
      </el-table>
      </div>
      <template #footer><el-button @click="flowLogVisible = false">关闭</el-button></template>
    </el-dialog>

    <el-dialog v-model="mergeDialogVisible" title="合并候选人" width="480px">
      <el-form label-width="96px">
        <el-form-item label="主候选人"><span>{{ mergingCandidate?.name }}</span></el-form-item>
        <el-form-item label="目标候选人">
          <el-select v-model="mergeTargetId" filterable placeholder="选择要合并进来的候选人" style="width: 100%">
            <el-option v-for="c in mergeCandidatesList" :key="c.id" :label="`${c.name}${c.phone ? ` · ${c.phone}` : ''}`" :value="c.id" />
          </el-select>
        </el-form-item>
        <div class="color-secondary">合并后目标候选人的简历与指派将迁移至主候选人，目标候选人被删除；存在冲突有效指派时将被拒绝。</div>
      </el-form>
      <template #footer><el-button @click="mergeDialogVisible = false">取消</el-button><el-button type="primary" :disabled="!mergeTargetId" :loading="saving" @click="confirmMerge">确认合并</el-button></template>
    </el-dialog>

    <AiSettingDialog v-model="aiSettingVisible" />
  </div>
</template>

<script setup lang="ts">
import { computed, onMounted, onUnmounted, reactive, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import AppTable from '@/components/app-table/index.vue'
import AiSettingDialog from '@/views/hr/components/AiSettingDialog.vue'
import HrApi from '@/api/hr/recruitment'
import AuthorizationApi from '@/api/system/resource-authorization'
import type { UploadFile } from 'element-plus'
import type { Candidate, CandidateDetail, ConsentStatus, ContactPreference, ImportReport, Job, RelationType, ResumeChannel, ResumeFile, ResumeFlowLog, ResumeUploadResult } from '@/api/type/hr'
import useStore from '@/stores'
import { MsgConfirm, MsgError, MsgSuccess } from '@/utils/message'
import {
  assignmentStatusLabels,
  assignmentTagType,
  channelLabels,
  consentStatusLabels,
  contactPreferenceLabels,
  flowLogNodeLabels,
  getComplianceMissing,
  highestDegreeOptions,
  relationTypeLabels,
} from '@/views/hr/constants'

interface WorkspaceMember {
  id: string
  nick_name: string
  roles: string[]
}

const loading = ref(false)
const saving = ref(false)
const exporting = ref(false)
const candidates = ref<Candidate[]>([])
const openJobs = ref<Job[]>([])
const members = ref<WorkspaceMember[]>([])
const filters = reactive({
  name: '', city: '', skills: '', years_min: null as number | null, years_max: null as number | null,
  highest_degree: '', source: '', status: '', owner_id: '',
})
const pagination = reactive({ current_page: 1, page_size: 20, total: 0 })
const candidateDialogVisible = ref(false)
const assignmentDialogVisible = ref(false)
const uploadDialogVisible = ref(false)
const aiSettingVisible = ref(false)
const aiQuery = ref('')
const aiSearching = ref(false)
const uploadChannel = ref('OTHER')
const uploadResults = ref<ResumeUploadResult[]>([])
let resumePollTimer: ReturnType<typeof setInterval> | null = null
const resumeInputRef = ref<HTMLInputElement>()
const editingCandidate = ref<Candidate | null>(null)
const assigningCandidate = ref<Candidate | null>(null)
const selectedJobId = ref('')
const assignmentNote = ref('')
const assignmentRelationType = ref<RelationType>('APPLY')
const assignmentChannel = ref<ResumeChannel>('OTHER')
const assignmentOwnerId = ref<string | null>(null)
const skillsText = ref('')
const { user } = useStore()
const route = useRoute()
const router = useRouter()
const isHrAdmin = computed(() => user.getHrRole() === 'ADMIN')
const isHrOperator = computed(() => user.getHrRole() === 'OPERATOR' || user.getHrRole() === 'ADMIN')
const candidateForm = reactive({
  name: '', email: '', phone: '', current_city: '', target_city: '', highest_degree: '',
  years_experience: null as number | null, source: '', note: '',
  source_type: 'OTHER' as ResumeChannel, source_detail: '',
  collected_at: null as string | null, consent_status: 'UNKNOWN' as ConsentStatus,
  consent_version: '', contact_preference: 'UNSPECIFIED' as ContactPreference,
})

function memberName(memberId: string | null) {
  if (!memberId) return ''
  return members.value.find((member) => member.id === memberId)?.nick_name || ''
}

function complianceMissing(candidate: Candidate) {
  return getComplianceMissing(candidate)
}

function loadMembers() {
  AuthorizationApi.getUserMember(user.getWorkspaceId() || '').then((response) => {
    members.value = response.data || []
  }).catch(() => {})
}

function toggleMyCandidates() {
  filters.owner_id = filters.owner_id ? '' : user.userInfo?.id || ''
  refresh()
}

function resetCandidateForm(candidate?: Candidate) {
  candidateForm.name = candidate?.name || ''
  candidateForm.email = candidate?.email || ''
  candidateForm.phone = candidate?.phone || ''
  candidateForm.current_city = candidate?.current_city || ''
  candidateForm.target_city = candidate?.target_city || ''
  candidateForm.highest_degree = candidate?.highest_degree || ''
  candidateForm.years_experience = candidate?.years_experience ?? null
  candidateForm.source = candidate?.source || ''
  candidateForm.note = candidate?.note || ''
  candidateForm.source_type = candidate?.source_type || 'OTHER'
  candidateForm.source_detail = candidate?.source_detail || ''
  candidateForm.collected_at = candidate?.collected_at || null
  candidateForm.consent_status = candidate?.consent_status || 'UNKNOWN'
  candidateForm.consent_version = candidate?.consent_version || ''
  candidateForm.contact_preference = candidate?.contact_preference || 'UNSPECIFIED'
  skillsText.value = candidate?.skills.join(', ') || ''
}

function openCandidateDialog(candidate?: Candidate) {
  editingCandidate.value = candidate || null
  resetCandidateForm(candidate)
  candidateDialogVisible.value = true
}

const candidateDetailVisible = ref(false)
const candidateDetail = ref<CandidateDetail | null>(null)

function openCandidateDetail(candidate: Candidate) {
  candidateDetail.value = null
  candidateDetailVisible.value = true
  HrApi.getCandidate(candidate.id).then((response) => {
    candidateDetail.value = response.data
  })
}

function handleRowCommand(command: string, row: Candidate) {
  if (command === 'edit') openCandidateDialog(row)
  else if (command === 'assign') openAssignmentDialog(row)
  else if (command === 'archive') archive(row)
  else if (command === 'restore') restore(row)
  else if (command === 'remove') removeCandidate(row)
  else if (command === 'resumes') openResumeListDialog(row)
  else if (command === 'merge') openMergeDialog(row)
}

function loadCandidates() {
  HrApi.getCandidates(pagination, filters).then((response) => {
    candidates.value = response.data.records
    pagination.total = response.data.total
  })
}

function refresh() {
  pagination.current_page = 1
  loadCandidates()
}

function aiSearch() {
  const query = aiQuery.value.trim()
  if (!query) return
  aiSearching.value = true
  HrApi.parseSearch(query)
    .then((response) => {
      const conditions = response.data.conditions
      filters.name = ''
      filters.city = conditions.city || ''
      filters.skills = conditions.skills.join(', ')
      filters.years_min = conditions.years_min
      filters.years_max = conditions.years_max
      filters.highest_degree = conditions.highest_degree || ''
      filters.source = ''
      filters.status = conditions.status || ''
      refresh()
      MsgSuccess('已按 AI 解析条件搜索，可继续修改筛选条件')
    })
    .catch(() => {})
    .finally(() => {
      aiSearching.value = false
    })
}

function saveCandidate() {
  if (!candidateForm.name.trim()) return
  const data = { ...candidateForm, skills: skillsText.value.split(',').map((skill) => skill.trim()).filter(Boolean) }
  saving.value = true
  HrApi.checkDuplicate({ phone: candidateForm.phone, email: candidateForm.email, exclude_id: editingCandidate.value?.id || '' })
    .then((response) => {
      if (response.data.candidates.length > 0) {
        return MsgConfirm('发现疑似重复候选人', `有 ${response.data.candidates.length} 名候选人手机号或邮箱相同，是否继续保存？`, { type: 'warning' })
          .then(() => doSaveCandidate(data))
          .catch(() => {})
      }
      return doSaveCandidate(data)
    })
    .catch(() => {})
    .finally(() => {
      saving.value = false
    })
}

function doSaveCandidate(data: Record<string, unknown>) {
  const request = editingCandidate.value
    ? HrApi.updateCandidate(editingCandidate.value.id, data)
    : HrApi.createCandidate(data)
  return request.then(() => {
    candidateDialogVisible.value = false
    MsgSuccess('候选人已保存')
    refresh()
  })
}

function archive(candidate: Candidate) {
  MsgConfirm('归档候选人', `归档后将保留 ${candidate.name} 的历史指派记录。`, { confirmButtonClass: 'danger' })
    .then(() => HrApi.archiveCandidate(candidate.id))
    .then(() => {
      MsgSuccess('候选人已归档')
      refresh()
    })
    .catch(() => {})
}

function restore(candidate: Candidate) {
  MsgConfirm('恢复候选人', `将 ${candidate.name} 恢复为在库状态，可继续加入职位。`)
    .then(() => HrApi.restoreCandidate(candidate.id))
    .then(() => {
      MsgSuccess('候选人已恢复')
      refresh()
      if (candidateDetailVisible.value && candidateDetail.value?.id === candidate.id) {
        openCandidateDetail(candidate)
      }
    })
    .catch(() => {})
}

function removeCandidate(candidate: Candidate) {
  MsgConfirm(
    '删除候选人',
    `删除即匿名化处理：姓名被替换、联系方式等个人信息将被清空，且该候选人的简历文件会被删除。确认删除 ${candidate.name}？`,
    { confirmButtonClass: 'danger' },
  )
    .then(() => HrApi.deleteCandidate(candidate.id))
    .then(() => {
      MsgSuccess('候选人已删除')
      refresh()
    })
    .catch(() => {})
}

function exportCandidates() {
  exporting.value = true
  HrApi.exportCandidates({ ...filters })
    .then(() => MsgSuccess('候选人已导出'))
    .catch(() => {})
    .finally(() => {
      exporting.value = false
    })
}

const importDialogVisible = ref(false)
const importing = ref(false)
const importFile = ref<File | null>(null)
const importReport = ref<ImportReport | null>(null)

function handleImportFile(file: UploadFile) {
  importFile.value = file.raw || null
  importReport.value = null
}

function downloadImportTemplate() {
  HrApi.downloadImportTemplate()
}

function submitImport() {
  if (!importFile.value) return
  importing.value = true
  HrApi.importCandidates(importFile.value)
    .then((response) => {
      importReport.value = response.data
      MsgSuccess('导入完成')
      refresh()
    })
    .catch(() => {})
    .finally(() => {
      importing.value = false
    })
}

function openAssignmentDialog(candidate: Candidate) {
  assigningCandidate.value = candidate
  selectedJobId.value = ''
  assignmentNote.value = ''
  assignmentRelationType.value = 'APPLY'
  assignmentChannel.value = 'OTHER'
  assignmentOwnerId.value = null
  HrApi.getJobs({ current_page: 1, page_size: 100 }, { status: 'OPEN' }).then((response) => {
    openJobs.value = response.data.records
    assignmentDialogVisible.value = true
  })
}

function createAssignment() {
  if (!assigningCandidate.value || !selectedJobId.value) return
  saving.value = true
  HrApi.createAssignment(selectedJobId.value, assigningCandidate.value.id, assignmentNote.value, {
    relation_type: assignmentRelationType.value,
    channel: assignmentChannel.value,
    owner_id: assignmentOwnerId.value || null,
  })
    .then(() => {
      assignmentDialogVisible.value = false
      MsgSuccess('已加入职位')
    })
    .catch(() => {})
    .finally(() => { saving.value = false })
}

function openResumeUpload() {
  uploadResults.value = []
  resumeInputRef.value?.click()
}

function handleResumeFiles(event: Event) {
  const input = event.target as HTMLInputElement
  const files = input.files ? Array.from(input.files) : []
  input.value = ''
  if (files.length === 0) return
  uploadDialogVisible.value = true
  HrApi.uploadResumes(files, uploadChannel.value)
    .then((response) => {
      uploadResults.value = response.data
      const pendingIds = uploadResults.value.filter((record) => record.status === 'PENDING').map((record) => record.resume_id)
      if (pendingIds.length > 0) startResumePolling(pendingIds)
      else finishResumeUpload()
    })
    .catch(() => {})
}

function finishResumeUpload() {
  const failed = uploadResults.value.some((record) => record.status === 'FAILED')
  if (failed) MsgError('部分简历解析失败，请查看结果')
  else MsgSuccess('简历解析完成')
  refresh()
}

function startResumePolling(ids: string[]) {
  stopResumePolling()
  const endsAt = Date.now() + 60 * 1000
  resumePollTimer = setInterval(() => {
    HrApi.getResumeBatchStatus(ids)
      .then((response) => {
        const statusMap = new Map(response.data.map((item) => [item.resume_id, item]))
        let allDone = true
        for (const record of uploadResults.value) {
          const latest = statusMap.get(record.resume_id)
          if (!latest) continue
          record.status = latest.status
          record.error_message = latest.error_message || ''
          if (latest.status === 'PENDING') allDone = false
        }
        if (allDone || Date.now() > endsAt) {
          stopResumePolling()
          finishResumeUpload()
        }
      })
      .catch(() => {})
  }, 1000)
}

function stopResumePolling() {
  if (resumePollTimer) {
    clearInterval(resumePollTimer)
    resumePollTimer = null
  }
}

const resumeListVisible = ref(false)
const candidateResumes = ref<ResumeFile[]>([])
const resumeContentVisible = ref(false)
const resumeContent = ref('')
const flowLogVisible = ref(false)
const flowLogLoading = ref(false)
const flowLogs = ref<ResumeFlowLog[]>([])
const mergingCandidate = ref<Candidate | null>(null)
const mergeDialogVisible = ref(false)
const mergeTargetId = ref('')
const mergeCandidatesList = ref<Candidate[]>([])

function openResumeListDialog(candidate: Candidate) {
  candidateResumes.value = []
  resumeListVisible.value = true
  HrApi.getCandidateResumes(candidate.id).then((response) => {
    candidateResumes.value = response.data
  })
}

function viewResumeContent(resume: ResumeFile) {
  resumeContent.value = ''
  resumeContentVisible.value = true
  HrApi.getResumeContent(resume.id).then((response) => {
    resumeContent.value = response.data.content
  }).catch(() => MsgError('简历内容提取失败'))
}

function downloadResumeFile(resume: ResumeFile) {
  HrApi.downloadResume(resume.id, resume.file_name)
}

function removeResume(resume: ResumeFile) {
  MsgConfirm(
    '删除简历',
    `确认删除简历「${resume.file_name}」？该操作会同时删除语义索引与流转日志，不可恢复。`,
    { confirmButtonClass: 'danger' },
  )
    .then(() => HrApi.deleteResume(resume.id))
    .then(() => {
      MsgSuccess('简历已删除')
      if (candidateResumes.value.length) {
        const candidateId = candidateResumes.value[0]?.candidate_id
        if (candidateId) {
          HrApi.getCandidateResumes(candidateId).then((response) => {
            candidateResumes.value = response.data
          })
        }
      }
      refresh()
    })
    .catch(() => {})
}

function openFlowLogs(resume: ResumeFile) {
  flowLogs.value = []
  flowLogLoading.value = true
  flowLogVisible.value = true
  HrApi.getResumeFlowLogs(resume.id)
    .then((response) => {
      flowLogs.value = response.data
    })
    .catch(() => MsgError('加载流转日志失败'))
    .finally(() => {
      flowLogLoading.value = false
    })
}

function formatFlowLogDetail(detail: Record<string, unknown>) {
  try {
    return JSON.stringify(detail, null, 2)
  } catch {
    return String(detail)
  }
}

function openMergeDialog(candidate: Candidate) {
  mergingCandidate.value = candidate
  mergeTargetId.value = ''
  HrApi.getCandidates({ current_page: 1, page_size: 100 }, { status: '' }).then((response) => {
    mergeCandidatesList.value = response.data.records.filter((item) => item.id !== candidate.id)
    mergeDialogVisible.value = true
  })
}

function confirmMerge() {
  if (!mergingCandidate.value || !mergeTargetId.value) return
  saving.value = true
  HrApi.mergeCandidates(mergingCandidate.value.id, mergeTargetId.value)
    .then(() => {
      mergeDialogVisible.value = false
      MsgSuccess('候选人已合并')
      refresh()
    })
    .catch(() => {})
    .finally(() => {
      saving.value = false
    })
}

function openCandidateFromQuery() {
  const candidateId = route.query.candidate_id
  if (typeof candidateId === 'string' && candidateId) {
    openCandidateDetail({ id: candidateId } as Candidate)
  }
  const editCandidateId = route.query.edit_candidate
  if (typeof editCandidateId === 'string' && editCandidateId) {
    HrApi.getCandidate(editCandidateId).then((response) => {
      openCandidateDialog(response.data)
    }).catch(() => {})
  }
}

onMounted(() => {
  loadMembers()
  loadCandidates()
  openCandidateFromQuery()
})
watch(() => route.query.candidate_id, (candidateId) => {
  if (typeof candidateId === 'string' && candidateId) {
    openCandidateDetail({ id: candidateId } as Candidate)
  }
})
watch(() => route.query.edit_candidate, (editCandidateId) => {
  if (typeof editCandidateId === 'string' && editCandidateId) {
    HrApi.getCandidate(editCandidateId).then((response) => {
      openCandidateDialog(response.data)
    }).catch(() => {})
  }
})
watch(uploadDialogVisible, (visible) => {
  if (!visible) stopResumePolling()
})

onUnmounted(stopResumePolling)
</script>

<style scoped>
.hr-page { min-width: 0; }
.candidate-name { font-weight: 600; }
.gap-12 { gap: 12px; }
.gap-4 { gap: 4px; }
.align-center { align-items: center; }
.flex { display: flex; }
.hidden-input { display: none; }
.upload-result { padding: 6px 0; }
.resume-content {
  white-space: pre-wrap;
  word-break: break-all;
  max-height: 480px;
  overflow-y: auto;
  margin: 0;
}
.flow-log-wrapper {
  min-height: 120px;
}
.flow-log-detail {
  white-space: pre-wrap;
  word-break: break-all;
  margin: 0;
  max-height: 120px;
  overflow-y: auto;
  font-size: 12px;
}
</style>
