<template>
  <div class="hr-page p-16-24">
    <div class="flex-between mb-16">
      <div>
        <div class="eyebrow">HIRING REQUISITIONS</div>
        <h2>职位</h2>
        <span class="color-secondary">维护招聘需求、开放职位与候选人筛选进度</span>
      </div>
      <el-button v-if="isHrAdmin" type="primary" @click="router.push('/hr/jobs/new')">新建职位</el-button>
      <el-button v-if="isHrAdmin" plain @click="aiSettingVisible = true">AI 设置</el-button>
    </div>

    <el-card style="--el-card-padding: 0" v-loading="loading">
      <div class="filter-toolbar p-16 border-b">
        <el-input v-model="filters.name" placeholder="按职位名称搜索" clearable @change="refresh" />
        <el-select v-model="filters.status" placeholder="状态" clearable @change="refresh" style="width: 140px">
          <el-option v-for="(label, value) in jobStatusLabels" :key="value" :label="label" :value="value" />
        </el-select>
        <el-button :type="filters.owner_id ? 'primary' : 'default'" plain @click="toggleMyJobs">待我处理</el-button>
        <el-button plain @click="resetJobFilters">重置筛选</el-button>
      </div>

      <AppTable :data="jobs" :pagination-config="pagination" @change-page="loadJobs" @size-change="refresh" @expand-change="handleExpand">
        <el-table-column type="expand">
          <template #default="{ row }">
            <div class="assignment-panel" v-loading="detailLoading === row.id">
              <el-tabs v-model="expandTab[row.id]" @tab-change="(name: string) => handleExpandTab(row, name)">
                <el-tab-pane label="候选人" name="assignments">
                  <el-empty v-if="jobDetails[row.id]?.assignments?.length === 0" description="暂无候选人" />
                  <div v-else class="assignment-panel__body">
                    <div class="assignment-panel__toolbar">
                      <span class="color-secondary">共 {{ jobDetails[row.id]?.assignments?.length || 0 }} 位候选人，阶段流转请在 Pipeline 中进行</span>
                      <el-button link type="primary" size="small" @click="goPipeline(row)">前往 Pipeline</el-button>
                    </div>
                    <el-table :data="jobDetails[row.id]?.assignments || []" size="small" v-loading="detailLoading === row.id">
                      <el-table-column label="候选人" min-width="150">
                        <template #default="{ row: app }">
                          <div class="flex align-center gap-6">
                            <span>{{ app.candidate_name || '-' }}</span>
                            <el-tag v-if="app.reapply_no > 0" size="small" type="warning" effect="plain">重投</el-tag>
                            <el-tag v-if="applicationStatusLabels[app.status] && app.status !== 'ACTIVE'" size="small" :type="applicationStatusTagType(app.status)" effect="plain">
                              {{ applicationStatusLabels[app.status] }}
                            </el-tag>
                          </div>
                        </template>
                      </el-table-column>
                      <el-table-column label="当前阶段" min-width="120">
                        <template #default="{ row: app }">{{ app.current_stage?.name || '-' }}</template>
                      </el-table-column>
                      <el-table-column label="来源" width="100">
                        <template #default="{ row: app }">{{ channelLabels[app.channel] || app.channel || '-' }}</template>
                      </el-table-column>
                      <el-table-column label="负责人" width="110">
                        <template #default="{ row: app }">{{ app.owner_id ? memberName(app.owner_id) : '未分配' }}</template>
                      </el-table-column>
                      <el-table-column label="AI 提案" width="160">
                        <template #default="{ row: app }">
                          <el-tag v-if="app.agent && app.agent.status === 'PENDING'" size="small" :type="agentActionTagType(app.agent.action)" effect="dark">
                            AI {{ agentActionLabel(app.agent.action) }}{{ app.agent.score != null ? ' ' + app.agent.score : '' }}
                          </el-tag>
                          <el-tag v-else-if="app.agent" size="small" type="info" effect="plain">
                            AI {{ agentActionLabel(app.agent.action) }} · {{ proposalStatusLabel(app.agent.status) }}
                          </el-tag>
                          <span v-else class="color-secondary">-</span>
                        </template>
                      </el-table-column>
                      <el-table-column label="操作" width="230" fixed="right">
                        <template #default="{ row: app }">
                          <el-button v-if="app.agent" link size="small" @click="openAiDrawer(row, app)">AI</el-button>
                          <el-button v-if="isHrOperator" link type="primary" size="small" @click="openInterviewDrawer(row, app)">面试</el-button>
                          <el-button v-if="isHrAdmin && isOfferStage(app)" link type="primary" size="small" @click="openOfferDrawer(row, app)">Offer</el-button>
                          <el-dropdown v-if="isHrOperator" trigger="click" size="small" @click.stop @command="(cmd: string) => onCardCommand(cmd, row, app)">
                            <el-button link size="small" @click.stop>更多</el-button>
                            <template #dropdown>
                              <el-dropdown-menu>
                                <el-dropdown-item command="ai">AI 评估</el-dropdown-item>
                                <el-dropdown-item v-if="!app.agent || app.agent.status !== 'PENDING'" command="ai-run">运行 AI 评估</el-dropdown-item>
                                <el-dropdown-item v-if="isActiveApplication(app)" command="draft">生成沟通草稿</el-dropdown-item>
                                <el-dropdown-item v-if="isActiveApplication(app)" command="reject" divided>淘汰</el-dropdown-item>
                                <el-dropdown-item v-if="isActiveApplication(app)" command="withdraw">候选人退出</el-dropdown-item>
                                <el-dropdown-item v-if="isActiveApplication(app)" command="close">关闭申请</el-dropdown-item>
                                <el-dropdown-item v-if="isHrAdmin && app.status === 'REJECTED'" command="restore" divided>恢复申请</el-dropdown-item>
                              </el-dropdown-menu>
                            </template>
                          </el-dropdown>
                        </template>
                      </el-table-column>
                    </el-table>
                  </div>
                </el-tab-pane>
                <el-tab-pane label="匹配候选人" name="matches">
                  <el-empty v-if="matches[row.id]?.records?.length === 0" description="暂无匹配候选人" />
                  <el-table v-else :data="matches[row.id]?.records || []" size="small">
                    <el-table-column prop="name" label="候选人" min-width="120" />
                    <el-table-column label="匹配分" width="90">
                      <template #default="{ row: match }"><el-tag size="small">{{ match.match_score }}</el-tag></template>
                    </el-table-column>
                    <el-table-column label="命中技能" min-width="160">
                      <template #default="{ row: match }">{{ match.matched_skills.join('、') || '-' }}</template>
                    </el-table-column>
                    <el-table-column prop="current_city" label="现居" width="100"><template #default="{ row: match }">{{ match.current_city || '-' }}</template></el-table-column>
                    <el-table-column label="操作" width="110">
                      <template #default="{ row: match }">
                        <el-button v-if="isHrOperator" link type="primary" size="small" :disabled="row.status === 'CLOSED'" @click="addMatchToJob(row, match)">加入职位</el-button>
                      </template>
                    </el-table-column>
                  </el-table>
                </el-tab-pane>
              </el-tabs>
            </div>
          </template>
        </el-table-column>
        <el-table-column prop="name" label="职位" min-width="180" />
        <el-table-column prop="department" label="部门" min-width="130"><template #default="{ row }">{{ row.department || '-' }}</template></el-table-column>
        <el-table-column prop="city" label="城市" width="120"><template #default="{ row }">{{ row.city || '-' }}</template></el-table-column>
        <el-table-column label="HC" width="90"><template #default="{ row }">{{ row.active_assignment_count }}/{{ row.headcount }}</template></el-table-column>
        <el-table-column label="状态" width="100">
          <template #default="{ row }"><el-tag :type="jobStatusTagType(row.status)">{{ jobStatusLabels[row.status] || row.status }}</el-tag></template>
        </el-table-column>
        <el-table-column label="负责人" width="110">
          <template #default="{ row }">{{ memberName(row.owner_id) || '-' }}</template>
        </el-table-column>
        <el-table-column label="操作" width="300" fixed="right">
          <template #default="{ row }">
            <el-button v-if="isHrAdmin" link type="primary" @click="openJobDialog(row)">编辑</el-button>
            <el-button v-if="isHrOperator && row.status === 'OPEN'" link type="primary" :loading="sourcingRunning === row.id" @click="startSourcing(row)">AI 找人才</el-button>
            <el-button v-if="isHrAdmin" link type="warning" :disabled="row.status !== 'ON_HOLD' && row.status !== 'CLOSED'" @click="reopenJob(row)">恢复</el-button>
            <el-button v-if="isHrAdmin" link type="danger" :disabled="row.status === 'CLOSED'" @click="openCloseDialog(row)">关闭</el-button>
          </template>
        </el-table-column>
      </AppTable>
    </el-card>

    <el-dialog v-model="jobDialogVisible" :title="editingJob ? '编辑职位' : '新建职位'" width="620px">
      <el-form :model="jobForm" label-width="88px" @submit.prevent>
        <el-form-item label="职位名称" required><el-input v-model="jobForm.name" maxlength="128" /></el-form-item>
        <el-row :gutter="16">
          <el-col :span="12"><el-form-item label="部门"><el-input v-model="jobForm.department" /></el-form-item></el-col>
          <el-col :span="12"><el-form-item label="城市"><el-input v-model="jobForm.city" /></el-form-item></el-col>
        </el-row>
        <el-row :gutter="16">
          <el-col :span="12"><el-form-item label="职级"><el-input v-model="jobForm.level" /></el-form-item></el-col>
          <el-col :span="12"><el-form-item label="招聘人数"><el-input-number v-model="jobForm.headcount" :min="1" :max="999" /></el-form-item></el-col>
        </el-row>
        <el-row :gutter="16">
          <el-col :span="12">
            <el-form-item label="状态">
              <el-select v-model="jobForm.status" style="width: 100%" :disabled="editingJob?.status === 'CLOSED'">
                <el-option v-for="(label, value) in statusOptions" :key="value" :label="label" :value="value" />
              </el-select>
            </el-form-item>
          </el-col>
          <el-col :span="12">
            <el-form-item label="负责人">
              <el-select v-model="jobForm.owner_id" clearable filterable placeholder="选择负责人" style="width: 100%">
                <el-option v-for="member in members" :key="member.id" :label="member.nick_name" :value="member.id" />
              </el-select>
            </el-form-item>
          </el-col>
        </el-row>
        <el-form-item v-if="jobForm.status === 'CLOSED'" label="关闭原因" required>
          <el-select v-model="jobForm.close_reason" placeholder="选择关闭原因" style="width: 100%">
            <el-option v-for="(label, value) in jobCloseReasonLabels" :key="value" :label="label" :value="value" />
          </el-select>
        </el-form-item>
        <el-form-item label="职位描述">
          <el-input v-model="jobForm.description" type="textarea" :rows="5" maxlength="4096" show-word-limit />
          <el-button v-if="editingJob && isHrOperator" class="mt-8" size="small" :loading="jdDrafting" @click="startJdDraft()">
            AI 起草 JD
          </el-button>
        </el-form-item>
        <el-form-item label="技能要求">
          <div class="w-full">
            <el-input v-model="jobSkillsText" placeholder="用逗号分隔，例如 Python, Django" />
            <el-button class="mt-8" size="small" :loading="extractingSkills" :disabled="!jobForm.description.trim()" @click="extractSkillsFromDescription">AI 抽取技能</el-button>
          </div>
        </el-form-item>
      </el-form>
      <template #footer><el-button @click="jobDialogVisible = false">取消</el-button><el-button type="primary" :loading="saving" @click="saveJob">保存</el-button></template>
    </el-dialog>

    <el-drawer v-model="jdDraftVisible" title="AI 职位描述草稿" size="640px">
      <div v-if="jdDraftLoading" v-loading="true" class="p-16" style="min-height: 200px" />
      <template v-else-if="jdDraftProposal">
        <div class="flex-between mb-16">
          <el-tag :type="proposalStatusTagType(jdDraftProposal.status)" size="small">
            {{ proposalStatusLabel(jdDraftProposal.status) }}
          </el-tag>
          <span class="color-secondary">{{ jdDraftProposal.create_time ? new Date(jdDraftProposal.create_time).toLocaleString() : '' }}</span>
        </div>
        <el-alert v-if="jdDraftProposal.payload.summary" :title="jdDraftProposal.payload.summary" type="info" :closable="false" class="mb-16" />
        <div class="ai-block">
          <div class="ai-title">建议职位名称</div>
          <div>{{ jdDraftProposal.payload.fields.name }}</div>
        </div>
        <div class="ai-block mt-16">
          <div class="ai-title">技能要求</div>
          <el-tag v-for="skill in jdDraftProposal.payload.fields.skill_requirements" :key="skill" class="mr-8" size="small">
            {{ skill }}
          </el-tag>
          <span v-if="!jdDraftProposal.payload.fields.skill_requirements.length" class="color-secondary">（沿用原职位技能要求）</span>
        </div>
        <div class="jd-grid mt-16">
          <div class="ai-block">
            <div class="ai-title">当前描述（未写入）</div>
            <pre class="jd-pre">{{ editingJob?.description || '(空)' }}</pre>
          </div>
          <div class="ai-block">
            <div class="ai-title">AI 草稿（采纳后写入）</div>
            <pre class="jd-pre">{{ jdDraftProposal.payload.fields.description }}</pre>
          </div>
        </div>
        <div v-if="jdDraftProposal.payload.sources?.length" class="ai-block mt-16">
          <div class="ai-title">依据来源</div>
          <ul class="ai-list">
            <li v-for="(source, idx) in jdDraftProposal.payload.sources" :key="idx">
              <el-tag :type="source.kind === 'knowledge' ? 'primary' : 'success'" size="small">
                {{ source.kind === 'knowledge' ? '知识库' : '相似职位' }}
              </el-tag>
              {{ source.ref }}<span v-if="source.note" class="color-secondary"> — {{ source.note }}</span>
            </li>
          </ul>
        </div>
        <div class="text-right mt-16">
          <el-button v-if="jdDraftProposal.status === 'PENDING' && isHrAdmin" type="primary" :loading="jdSaving" @click="acceptJdDraft">
            采纳写入职位
          </el-button>
          <el-button v-if="jdDraftProposal.status === 'PENDING' && isHrOperator" :loading="jdSaving" @click="dismissJdDraft">
            忽略
          </el-button>
          <el-button @click="jdDraftVisible = false">关闭</el-button>
        </div>
        <el-alert
          v-if="jdDraftProposal.status === 'PENDING' && !isHrAdmin"
          class="mt-16"
          type="warning"
          :closable="false"
          title="职位字段写入需要工作区管理员；如无权限可联系管理员处理。"
        />
      </template>
      <el-empty v-else description="暂无 JD 草稿，可在职位编辑中点击「AI 起草 JD」生成" />
    </el-drawer>


    <el-dialog v-model="sourcingScopeDialogVisible" title="选择 Sourcing 简历库范围" width="500px">
      <el-form label-width="96px">
        <el-form-item label="简历库">
          <el-select v-model="sourcingResumeDatabaseIds" multiple collapse-tags collapse-tags-tooltip clearable filterable :loading="resumeDatabaseLoading" placeholder="全部 ACTIVE 简历库" style="width: 100%">
            <el-option v-for="database in activeResumeDatabases" :key="database.id" :label="database.is_system ? database.name + '（总库）' : database.name" :value="database.id" />
          </el-select>
        </el-form-item>
      </el-form>
      <div class="color-secondary text-12">未选择范围时使用全部简历库；总库由服务端保持强制成员关系。</div>
      <template #footer>
        <el-button @click="sourcingScopeDialogVisible = false">取消</el-button>
        <el-button type="primary" :loading="sourcingRunning === sourcingScopeJob?.id" @click="confirmSourcing">生成激活清单</el-button>
      </template>
    </el-dialog>

    <el-drawer v-model="sourcingDrawerVisible" title="AI 人才库激活清单" size="620px">
      <div v-if="sourcingLoading" v-loading="true" class="p-16" style="min-height: 200px" />
      <template v-else-if="sourcingProposal">
        <div class="flex-between mb-16">
          <el-tag :type="proposalStatusTagType(sourcingProposal.status)" size="small">
            {{ proposalStatusLabel(sourcingProposal.status) }}
          </el-tag>
          <span class="color-secondary">内部清单，仅用于激活联系，不外发</span>
        </div>
        <el-alert v-if="sourcingProposal.payload.summary" :title="sourcingProposal.payload.summary" type="info" :closable="false" class="mb-16" />
        <div v-for="(candidate, idx) in sourcingProposal.payload.candidates || []" :key="candidate.candidate_id" class="ai-block mb-16">
          <div class="flex-between">
            <span class="ai-title">{{ idx + 1 }}. {{ candidate.name || '-' }}</span>
            <span class="color-secondary text-12">{{ candidate.current_city || '-' }} · {{ candidate.years_experience != null ? candidate.years_experience + ' 年' : '年限未知' }} · {{ candidate.highest_degree || '-' }}</span>
          </div>
          <div class="mt-8">
            <el-tag v-for="skill in candidate.skills || []" :key="skill" class="mr-8" size="small">{{ skill }}</el-tag>
          </div>
          <div class="mt-8">匹配理由：{{ candidate.match_reason || '-' }}</div>
          <div v-if="candidate.risk" class="mt-8 color-secondary">风险：{{ candidate.risk }}</div>
          <ul v-if="candidate.evidence?.length" class="ai-list mt-8">
            <li v-for="(ev, eIdx) in candidate.evidence" :key="eIdx">
              <span class="color-secondary">证据（相关度 {{ ev.relevance }}）：</span>{{ ev.excerpt }}
            </li>
          </ul>
        </div>
        <div class="text-right mt-16">
          <el-button v-if="sourcingProposal.status === 'PENDING' && isHrOperator" :loading="sourcingSaving" @click="dismissSourcingProposal">忽略清单</el-button>
          <el-button @click="sourcingDrawerVisible = false">关闭</el-button>
        </div>
      </template>
      <el-empty v-else description="暂无激活清单，可在职位行点击「AI 找人才」生成" />
    </el-drawer>

    <el-dialog v-model="draftDialogVisible" title="生成沟通草稿" width="520px">
      <el-form label-width="88px">
        <el-form-item label="场景" required>
          <el-select v-model="draftForm.scenario" style="width: 100%">
            <el-option label="婉拒/淘汰通知" value="REJECT" />
            <el-option label="进度通知" value="PROGRESS" />
            <el-option label="答疑" value="FAQ" />
            <el-option label="其他" value="OTHER" />
          </el-select>
        </el-form-item>
        <el-form-item v-if="draftForm.scenario === 'FAQ'" label="候选人问题">
          <el-input v-model="draftForm.context_note" type="textarea" :rows="3" maxlength="1000" placeholder="候选人提出的问题或需要回应的背景" />
        </el-form-item>
        <el-form-item v-else label="补充背景">
          <el-input v-model="draftForm.context_note" type="textarea" :rows="3" maxlength="1000" placeholder="可选：补充需要体现的背景信息" />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="draftDialogVisible = false">取消</el-button>
        <el-button type="primary" :loading="draftRunning" @click="confirmGenerateDraft">生成草稿</el-button>
      </template>
    </el-dialog>

    <el-drawer v-model="draftDrawerVisible" title="沟通草稿（外发前请人工审核）" size="620px">
      <div v-if="draftLoading" v-loading="true" class="p-16" style="min-height: 200px" />
      <template v-else-if="draftProposal">
        <div class="flex-between mb-16">
          <el-tag :type="proposalStatusTagType(draftProposal.status)" size="small">
            {{ proposalStatusLabel(draftProposal.status) }}
          </el-tag>
          <span class="color-secondary">{{ draftScenarioLabel(draftProposal.payload.scenario) }}</span>
        </div>
        <div class="ai-block">
          <div class="ai-title">话术草稿</div>
          <pre class="jd-pre">{{ draftProposal.payload.draft }}</pre>
        </div>
        <div v-if="draftProposal.payload.key_points?.length" class="ai-block mt-16">
          <div class="ai-title">要点</div>
          <ul class="ai-list"><li v-for="(item, idx) in draftProposal.payload.key_points" :key="idx">{{ item }}</li></ul>
        </div>
        <div v-if="draftProposal.payload.tone" class="ai-block mt-16">
          <div class="ai-title">语气与边界</div>
          {{ draftProposal.payload.tone }}
        </div>
        <div v-if="draftProposal.payload.sources?.length" class="ai-block mt-16">
          <div class="ai-title">依据来源</div>
          <ul class="ai-list">
            <li v-for="(source, idx) in draftProposal.payload.sources" :key="idx">{{ source.ref }}<span v-if="source.note" class="color-secondary"> — {{ source.note }}</span></li>
          </ul>
        </div>
        <div class="text-right mt-16">
          <el-button :loading="draftSaving" @click="copyDraft">复制草稿</el-button>
          <el-button v-if="draftProposal.status === 'PENDING' && isHrOperator" :loading="draftSaving" @click="dismissDraftProposal">忽略</el-button>
          <el-button @click="draftDrawerVisible = false">关闭</el-button>
        </div>
      </template>
      <el-empty v-else description="暂无草稿" />
    </el-drawer>

    <el-dialog v-model="interviewDrawerVisible" title="面试记录" width="640px">
      <div class="flex-between mb-16">
        <span>{{ interviewCandidateName }} · 申请 {{ interviewAssignment?.application_id?.slice(0, 8) }}</span>
        <el-button v-if="isHrOperator" type="primary" size="small" @click="addInterviewFormVisible = true">安排面试</el-button>
      </div>
      <el-form v-if="addInterviewFormVisible" label-width="88px" class="mb-16 p-16 border rounded">
        <el-row :gutter="16">
          <el-col :span="12">
            <el-form-item label="面试官">
              <el-select v-model="interviewForm.interviewer_user_id" filterable clearable placeholder="选择成员（可留空填临时面试官）" style="width: 100%">
                <el-option v-for="member in members" :key="member.id" :label="member.nick_name" :value="member.id" />
              </el-select>
            </el-form-item>
          </el-col>
          <el-col :span="12"><el-form-item label="面试时间"><el-date-picker v-model="interviewForm.scheduled_at" type="datetime" value-format="YYYY-MM-DDTHH:mm:ssZ" style="width: 100%" /></el-form-item></el-col>
        </el-row>
        <el-row :gutter="16">
          <el-col :span="12">
            <el-form-item label="反馈截止">
              <el-date-picker v-model="interviewForm.feedback_deadline" type="datetime" value-format="YYYY-MM-DDTHH:mm:ssZ" placeholder="可选" style="width: 100%" />
            </el-form-item>
          </el-col>
          <el-col :span="12"><el-form-item label="临时面试官"><el-input v-model="interviewForm.interviewer" placeholder="未选成员时使用" /></el-form-item></el-col>
        </el-row>
        <div class="text-right">
          <el-button size="small" @click="addInterviewFormVisible = false">取消</el-button>
          <el-button size="small" type="primary" @click="createInterviewRecord">保存</el-button>
        </div>
      </el-form>
      <el-table :data="interviewList" size="small">
        <el-table-column prop="round_no" label="轮次" width="60" />
        <el-table-column prop="interviewer" label="面试官" min-width="100" />
        <el-table-column prop="scheduled_at" label="时间" min-width="150">
          <template #default="{ row }">{{ row.scheduled_at ? new Date(row.scheduled_at).toLocaleString() : '-' }}</template>
        </el-table-column>
        <el-table-column label="反馈截止" min-width="170">
          <template #default="{ row }">
            <span v-if="row.feedback_deadline">
              {{ new Date(row.feedback_deadline).toLocaleString() }}
              <el-tag v-if="row.feedback_submitted_at" type="success" size="small">已提交</el-tag>
              <el-tag v-else-if="row.status === 'PENDING' && new Date(row.feedback_deadline) < new Date()" type="danger" size="small">逾期</el-tag>
            </span>
            <span v-else>-</span>
          </template>
        </el-table-column>
        <el-table-column label="结果" width="130">
          <template #default="{ row }">
            <el-select v-model="row.status" size="small" :disabled="!isHrOperator" @change="updateInterviewRecord(row)">
              <el-option label="待面试" value="PENDING" />
              <el-option label="通过" value="PASSED" />
              <el-option label="未通过" value="FAILED" />
              <el-option label="未到场" value="NO_SHOW" />
              <el-option label="取消" value="CANCELLED" />
            </el-select>
          </template>
        </el-table-column>
        <el-table-column label="反馈" min-width="160">
          <template #default="{ row }">
            <el-input v-model="row.feedback" size="small" :disabled="!isHrOperator" @change="updateInterviewRecord(row)" placeholder="填写反馈" />
          </template>
        </el-table-column>
      </el-table>
      <template #footer><el-button @click="interviewDrawerVisible = false">关闭</el-button></template>
    </el-dialog>

    <el-dialog v-model="offerDrawerVisible" title="Offer 管理" width="860px">
      <div class="flex-between mb-16">
        <span>{{ offerCandidateName }} · {{ offerJobName }}</span>
        <el-button v-if="isHrAdmin" type="primary" size="small" @click="addOfferFormVisible = true">新建版本</el-button>
      </div>
      <el-form v-if="addOfferFormVisible" label-width="88px" class="mb-16 p-16 border rounded">
        <el-row :gutter="16">
          <el-col :span="8"><el-form-item label="金额"><el-input-number v-model="offerForm.salary_amount" :min="0" :precision="2" style="width: 100%" /></el-form-item></el-col>
          <el-col :span="8"><el-form-item label="币种"><el-input v-model="offerForm.currency" maxlength="16" /></el-form-item></el-col>
          <el-col :span="8"><el-form-item label="备注"><el-input v-model="offerForm.note" /></el-form-item></el-col>
        </el-row>
        <div class="text-right">
          <el-button size="small" @click="addOfferFormVisible = false">取消</el-button>
          <el-button size="small" type="primary" @click="createOfferRecord">保存</el-button>
        </div>
      </el-form>
      <el-table :data="offerList" size="small">
        <el-table-column prop="version" label="版本" width="60" />
        <el-table-column label="金额" width="110">
          <template #default="{ row }">{{ row.salary_amount == null ? '-' : row.salary_amount + ' ' + row.currency }}</template>
        </el-table-column>
        <el-table-column label="审批" width="100">
          <template #default="{ row }">
            <el-tag :type="row.approval_status === 'APPROVED' ? 'success' : row.approval_status === 'REJECTED' ? 'danger' : 'info'" size="small">
              {{ row.approval_status === 'APPROVED' ? '已通过' : row.approval_status === 'REJECTED' ? '已驳回' : '待审批' }}
            </el-tag>
          </template>
        </el-table-column>
        <el-table-column label="状态" width="100">
          <template #default="{ row }"><el-tag :type="offerStatusTag(row.status)" size="small">{{ offerStatusLabels[row.status] }}</el-tag></template>
        </el-table-column>
        <el-table-column label="时间" min-width="160">
          <template #default="{ row }">{{ offerTimeText(row) }}</template>
        </el-table-column>
        <el-table-column label="附件" min-width="120">
          <template #default="{ row }">
            <template v-if="row.attachment_name">
              <el-button link type="primary" size="small" @click="downloadOfferAttachment(row)">{{ row.attachment_name }}</el-button>
              <el-button v-if="isHrAdmin" link type="danger" size="small" @click="removeOfferAttachment(row)">删除</el-button>
            </template>
            <el-upload v-else-if="isHrAdmin && row.status === 'DRAFT'" :show-file-list="false" :before-upload="(file: File) => uploadOfferAttachment(row, file)">
              <el-button link type="primary" size="small">上传</el-button>
            </el-upload>
          </template>
        </el-table-column>
        <el-table-column label="操作" width="240" fixed="right">
          <template #default="{ row }">
            <template v-if="isHrAdmin && row.status === 'DRAFT'">
              <el-button link type="primary" size="small" @click="openApproveOfferDialog(row)">审批</el-button>
              <el-button link type="primary" size="small" @click="sendOfferRecord(row)">发送</el-button>
            </template>
            <template v-else-if="isHrAdmin && row.status === 'SENT'">
              <el-button link type="success" size="small" @click="acceptOfferRecord(row)">接受</el-button>
              <el-button link type="danger" size="small" @click="rejectOfferRecord(row)">拒绝</el-button>
              <el-button link type="warning" size="small" @click="withdrawOfferRecord(row)">撤回</el-button>
            </template>
          </template>
        </el-table-column>
      </el-table>
      <template #footer><el-button @click="offerDrawerVisible = false">关闭</el-button></template>
    </el-dialog>

    <el-dialog v-model="approveOfferDialogVisible" title="Offer 审批" width="440px">
      <el-form label-width="88px">
        <el-form-item label="审批结果" required>
          <el-select v-model="approveForm.approval_status" style="width: 100%">
            <el-option label="通过" value="APPROVED" />
            <el-option label="驳回" value="REJECTED" />
          </el-select>
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="approveOfferDialogVisible = false">取消</el-button>
        <el-button type="primary" :disabled="!approveForm.approval_status" @click="approveOfferRecord">提交</el-button>
      </template>
    </el-dialog>

    <el-dialog v-model="closeDialogVisible" title="关闭职位" width="460px">
      <el-form label-width="96px">
        <el-form-item label="职位"><span>{{ closingJob?.name }}</span></el-form-item>
        <el-form-item label="在途申请">
          <el-tag :type="(closePreview?.active_application_count || 0) > 0 ? 'warning' : 'success'">{{ closePreview?.active_application_count || 0 }}</el-tag>
          <span class="ml-8 color-secondary">关闭后逐条写 CLOSED 事件，并自动撤回该申请下 DRAFT/SENT Offer</span>
        </el-form-item>
        <el-form-item v-if="closeMode === 'BULK'" label="批量确认">
          <el-checkbox v-model="bulkConfirmed">确认批量关闭 {{ closePreview?.active_application_count || 0 }} 条在途申请</el-checkbox>
        </el-form-item>
        <el-form-item label="关闭原因" required>
          <el-select v-model="closeReason" placeholder="选择关闭原因" style="width: 100%">
            <el-option v-for="(label, value) in jobCloseReasonLabels" :key="value" :label="label" :value="value" />
          </el-select>
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="closeDialogVisible = false">取消</el-button>
        <el-button type="primary" :disabled="!closeReason || hasActiveApplications && !bulkConfirmed" :loading="saving" @click="confirmCloseJob">确认关闭</el-button>
      </template>
    </el-dialog>


    <el-dialog v-model="statusDialogVisible" :title="isRestoreTransition ? '恢复申请' : '终止申请'" width="440px">
      <el-form label-width="96px">
        <el-form-item label="候选人"><span>{{ statusDialogAssignment?.candidate_name }}</span></el-form-item>
        <el-form-item v-if="!isRestoreTransition" label="操作"><span>{{ applicationActionLabels[statusDialogAction] || statusDialogAction }}</span></el-form-item>
        <el-form-item v-if="isRestoreTransition" label="恢复原因" required>
          <el-input v-model="statusDialogNote" placeholder="填写误淘汰恢复原因" />
        </el-form-item>
        <el-form-item v-else label="终止原因" required>
          <el-select v-model="statusDialogReason" placeholder="选择终止原因" style="width: 100%">
            <el-option v-for="reason in terminalReasonOptionsFor(statusDialogAction)" :key="reason" :label="terminationReasonLabels[reason]" :value="reason" />
          </el-select>
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="statusDialogVisible = false">取消</el-button>
        <el-button type="primary" :disabled="!isRestoreTransition && !statusDialogReason" :loading="saving" @click="confirmStatusChange">确认</el-button>
      </template>
    </el-dialog>

    <el-dialog v-model="aiDrawerVisible" title="AI 初筛评估" width="720px">
      <div class="flex-between mb-16">
        <span>{{ aiCandidateName }} · {{ aiJobName }}</span>
        <div class="flex align-center gap-12">
          <el-tag v-if="aiLatestProposal()" :type="proposalStatusTagType(aiLatestProposal().status)" size="small">
            {{ proposalStatusLabel(aiLatestProposal().status) }}
          </el-tag>
          <el-button v-if="isHrOperator" size="small" :loading="aiRunning" @click="runAiAssessment">运行评估</el-button>
        </div>
      </div>
      <el-form v-if="isHrOperator" inline class="mb-16">
        <el-form-item label="简历库范围" class="mb-0">
          <el-select
            v-model="aiResumeDatabaseIds"
            multiple
            collapse-tags
            collapse-tags-tooltip
            clearable
            filterable
            :loading="resumeDatabaseLoading"
            placeholder="全部简历库"
            style="width: 300px"
          >
            <el-option
              v-for="database in activeResumeDatabases"
              :key="database.id"
              :label="database.is_system ? database.name + '（总库）' : database.name"
              :value="database.id"
            />
          </el-select>
        </el-form-item>
      </el-form>
      <div v-loading="aiLoading">
        <template v-if="aiLatestProposal()">
          <el-alert
            :title="'建议动作：' + agentActionLabel(aiLatestProposal().action) + (aiLatestProposal().payload?.decision?.score != null ? '（评分 ' + aiLatestProposal().payload.decision.score + '，' + aiLatestProposal().payload.decision.score_version + '）' : '')"
            :type="aiLatestProposal().action === 'ADVANCE' ? 'success' : aiLatestProposal().action === 'DECLINE' ? 'error' : 'warning'"
            :closable="false"
            class="mb-16"
          >
            <template #default>
              <div>硬条件 {{ aiLatestProposal().payload?.decision?.hard_met ? '全部满足' : '未满足' }} · 证据充分性 {{ aiLatestProposal().payload?.decision?.evidence_ok ? '达标' : '不足' }}</div>
              <div v-if="aiLatestProposal().decision_note" class="color-secondary">审批备注：{{ aiLatestProposal().decision_note }}</div>
            </template>
          </el-alert>

          <div v-if="aiLatestProposal().payload?.hard_conditions?.length" class="ai-block">
            <h4>硬条件核对</h4>
            <ul class="ai-list">
              <li v-for="(condition, idx) in aiLatestProposal().payload.hard_conditions" :key="idx">
                <el-icon :color="condition.met ? 'var(--el-color-success)' : 'var(--el-color-danger)'">
                  <CircleCheck v-if="condition.met" /><CircleClose v-else />
                </el-icon>
                {{ condition.requirement }}<span class="color-secondary ml-8">{{ condition.detail }}</span>
              </li>
            </ul>
          </div>

          <div v-for="dimension in aiLatestProposal().payload?.dimensions || []" :key="dimension.name" class="ai-block">
            <h4>{{ dimension.name }} <el-tag size="small" :type="dimension.confidence >= 0.5 ? 'success' : 'warning'" effect="plain">置信度 {{ Math.round(dimension.confidence * 100) }}%</el-tag></h4>
            <p>{{ dimension.verdict }}</p>
            <ul class="ai-list" v-if="dimension.evidence?.length">
              <li v-for="(item, idx) in dimension.evidence" :key="idx" class="ai-evidence">
                <span class="color-secondary">[{{ item.relevance.toFixed(2) }}]</span> {{ item.excerpt }}
              </li>
            </ul>
            <span v-else class="color-secondary">无证据摘录</span>
          </div>

          <div v-if="aiLatestProposal().payload?.concerns?.length" class="ai-block">
            <h4>风险点</h4>
            <ul class="ai-list"><li v-for="(item, idx) in aiLatestProposal().payload.concerns" :key="idx">{{ item }}</li></ul>
          </div>
          <div v-if="aiLatestProposal().payload?.clarifying_questions?.length" class="ai-block">
            <h4>待澄清</h4>
            <ul class="ai-list"><li v-for="(item, idx) in aiLatestProposal().payload.clarifying_questions" :key="idx">{{ item }}</li></ul>
          </div>
          <div v-if="aiLatestProposal().status === 'PENDING'" class="text-right mt-16">
            <el-button type="primary" :loading="saving" @click="acceptAiProposal(aiLatestProposal())">
              接受并执行（{{ agentActionLabel(aiLatestProposal().action) }}）
            </el-button>
            <el-button :loading="saving" @click="dismissAiProposal(aiLatestProposal())">忽略</el-button>
          </div>
        </template>
        <el-empty v-else-if="!aiLoading" description="暂无 AI 评估结果，可点击「运行评估」生成" />
      </div>
      <template #footer><el-button @click="aiDrawerVisible = false">关闭</el-button></template>
    </el-dialog>

    <AiSettingDialog v-model="aiSettingVisible" />
  </div>
</template>

<script setup lang="ts">
import { computed, onMounted, reactive, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import AppTable from '@/components/app-table/index.vue'
import AiSettingDialog from '@/views/hr/components/AiSettingDialog.vue'
import HrApi from '@/api/hr/recruitment'
import {
  applicationActionLabels,
  applicationStatusLabels,
  applicationStatusTagType,
  applicationTerminalReasonOptions,
  channelLabels,
  jobCloseReasonLabels,
  jobStatusLabels,
  jobStatusTagType,
  offerStatusLabels,
  offerStatusTag,
  relationTypeLabels,
  terminationReasonLabels,
} from '@/views/hr/constants'
import type {
  AgentProposal,
  CommunicationDraftProposal,
  Interview,
  JDProposal,
  Job,
  SourcingProposal,
  JobApplication,
  JobClosePreview,
  JobCloseReason,
  JobDetail,
  JobMatchCandidate,
  JobMatchPage,
  JobStatus,
  Offer,
  RelationType,
  ResumeChannel,
  ResumeDatabase,
  TerminationReason,
} from '@/api/type/hr'
import useStore from '@/stores'
import { MsgConfirm, MsgError, MsgSuccess } from '@/utils/message'

interface WorkspaceMember {
  id: string
  nick_name: string
  roles: string[]
}

type ApplicationAction = 'reject' | 'withdraw' | 'close' | 'restore'

const statusOptions = computed(() => {
  if (!editingJob.value) {
    return Object.fromEntries(Object.entries(jobStatusLabels).filter(([value]) => value !== 'CLOSED'))
  }
  if (editingJob.value.status === 'CLOSED') return { CLOSED: jobStatusLabels.CLOSED }
  return jobStatusLabels
})

const loading = ref(false)
const saving = ref(false)
const jobs = ref<Job[]>([])
const members = ref<WorkspaceMember[]>([])
const filters = reactive({ name: '', status: '', owner_id: '' })
const pagination = reactive({ current_page: 1, page_size: 20, total: 0 })
const jobDetails = reactive<Record<string, JobDetail>>({})
const matches = reactive<Record<string, JobMatchPage>>({})
const detailLoading = ref('')
const expandTab = reactive<Record<string, string>>({})

const jobDialogVisible = ref(false)
const aiSettingVisible = ref(false)
const editingJob = ref<Job | null>(null)
const jobSkillsText = ref('')
const extractingSkills = ref(false)
const jobForm = reactive({
  name: '', department: '', city: '', level: '', headcount: 1, description: '',
  status: 'OPEN' as JobStatus, close_reason: null as JobCloseReason | null, owner_id: null as string | null,
})
const isHrAdmin = computed(() => user.getHrRole() === 'ADMIN')
const isHrOperator = computed(() => user.getHrRole() === 'OPERATOR' || user.getHrRole() === 'ADMIN')
const interviewDrawerVisible = ref(false)
const interviewList = ref<Interview[]>([])
const interviewAssignment = ref<JobApplication | null>(null)
const interviewCandidateName = ref('')
const addInterviewFormVisible = ref(false)
const interviewForm = reactive({
  interviewer: '',
  interviewer_user_id: null as string | null,
  feedback_deadline: null as string | null,
  scheduled_at: null as string | null,
})
const closeDialogVisible = ref(false)
const closingJob = ref<Job | null>(null)
const closePreview = ref<JobClosePreview | null>(null)
const closeMode = ref<'STRICT' | 'BULK'>('STRICT')
const bulkConfirmed = ref(false)
const closeReason = ref('')

const hasActiveApplications = computed(() => (closePreview.value?.active_application_count || 0) > 0)

const statusDialogVisible = ref(false)
const statusDialogAssignment = ref<JobApplication | null>(null)
const statusDialogJob = ref<Job | null>(null)
const statusDialogAction = ref<ApplicationAction>('reject')
const statusDialogReason = ref<TerminationReason | ''>('')
const statusDialogNote = ref('')
const { user } = useStore()
const route = useRoute()
const router = useRouter()

const isRestoreTransition = computed(() => statusDialogAction.value === 'restore')

function terminalReasonOptionsFor(action: ApplicationAction): string[] {
  return applicationTerminalReasonOptions[action] || []
}

function memberName(memberId: string | null) {
  if (!memberId) return ''
  return members.value.find((member) => member.id === memberId)?.nick_name || ''
}

function loadMembers() {
  HrApi.getMembers().then((response) => {
    members.value = response.data || []
  }).catch(() => {})
}

function resetJobForm(job?: Job) {
  jobForm.name = job?.name || ''
  jobForm.department = job?.department || ''
  jobForm.city = job?.city || ''
  jobForm.level = job?.level || ''
  jobForm.headcount = job?.headcount || 1
  jobForm.description = job?.description || ''
  jobForm.status = (job?.status || 'OPEN') as JobStatus
  jobForm.close_reason = job?.close_reason || null
  jobForm.owner_id = job?.owner_id || null
  jobSkillsText.value = job?.skill_requirements?.join(', ') || ''
}

function loadJobs() {
  loading.value = true
  HrApi.getJobs(pagination, filters).then((response) => {
    jobs.value = response.data.records
    pagination.total = response.data.total
  }).catch(() => {}).finally(() => { loading.value = false })
}

function handleExpand(job: Job, expandedRows: Job[]) {
  if (expandedRows.some((row) => row.id === job.id)) {
    if (!expandTab[job.id]) expandTab[job.id] = 'assignments'
    if (!jobDetails[job.id]) {
      loadJobDetail(job)
      loadMatches(job)
    }
  }
}

function handleExpandTab(job: Job, name: string) {
  if (name === 'matches' && !matches[job.id]) loadMatches(job)
}

function loadMatches(job: Job) {
  HrApi.getJobMatches(job.id, { current_page: 1, page_size: 50 }).then((response) => {
    matches[job.id] = response.data
  })
}

function refresh() {
  pagination.current_page = 1
  loadJobs()
}

function loadJobDetail(job: Job) {
  detailLoading.value = job.id
  return HrApi.getJob(job.id).then((response) => {
    jobDetails[job.id] = response.data
    return response.data
  }).finally(() => {
    if (detailLoading.value === job.id) detailLoading.value = ''
  })
}

function openJobDialog(job?: Job) {
  editingJob.value = job || null
  resetJobForm(job)
  jobDialogVisible.value = true
}

const jdDraftVisible = ref(false)
const jdDraftLoading = ref(false)
const jdDrafting = ref(false)
const jdSaving = ref(false)
const jdDraftProposal = ref<JDProposal | null>(null)
const jdDraftList = ref<JDProposal[]>([])

function loadJdProposals() {
  if (!editingJob.value) return
  jdDraftLoading.value = true
  HrApi.getJobProposals(editingJob.value.id)
    .then((response) => {
      jdDraftList.value = response.data || []
      jdDraftProposal.value = jdDraftList.value.find((p) => p.status === 'PENDING') || jdDraftList.value[0] || null
    })
    .catch(() => {})
    .finally(() => {
      jdDraftLoading.value = false
    })
}

function startJdDraft() {
  if (!editingJob.value) return
  MsgConfirm(
    'AI 起草 JD',
    '将基于职位信息、企业知识库模板与相似职位生成描述草稿；草稿不会直接写入职位，需人工确认后采纳。',
  )
    .then(() => {
      if (!editingJob.value) return
      jdDrafting.value = true
      HrApi.runJdDraftAgent(editingJob.value.id)
        .then(() => {
          MsgSuccess('草稿已生成')
          jdDraftVisible.value = true
          loadJdProposals()
        })
        .catch(() => {})
        .finally(() => {
          jdDrafting.value = false
        })
    })
    .catch(() => {})
}

function acceptJdDraft() {
  if (!jdDraftProposal.value) return
  MsgConfirm('采纳草稿', '确认将 AI 草稿写入职位（名称/描述/技能要求）？不会改变职位状态。', { confirmButtonClass: 'danger' })
    .then(() => {
      if (!jdDraftProposal.value) return
      jdSaving.value = true
      HrApi.acceptProposal(jdDraftProposal.value.id, { decision_note: 'HR 采纳 JD 草稿' })
        .then(() => {
          MsgSuccess('已写入职位')
          jdDraftVisible.value = false
          if (editingJob.value) loadJobDetail(editingJob.value)
          refresh()
        })
        .catch(() => {})
        .finally(() => {
          jdSaving.value = false
        })
    })
    .catch(() => {})
}

function dismissJdDraft() {
  if (!jdDraftProposal.value) return
  MsgConfirm('忽略草稿', '确定忽略这份 AI 草稿？')
    .then(() => {
      if (!jdDraftProposal.value) return
      jdSaving.value = true
      HrApi.dismissProposal(jdDraftProposal.value.id, { decision_note: 'HR 忽略草稿' })
        .then(() => {
          MsgSuccess('已忽略')
          loadJdProposals()
        })
        .catch(() => {})
        .finally(() => {
          jdSaving.value = false
        })
    })
    .catch(() => {})
}

const sourcingDrawerVisible = ref(false)
const sourcingScopeDialogVisible = ref(false)
const sourcingScopeJob = ref<Job | null>(null)
const sourcingResumeDatabaseIds = ref<string[]>([])
const sourcingLoading = ref(false)
const sourcingRunning = ref('')
const sourcingSaving = ref(false)
const sourcingProposal = ref<SourcingProposal | null>(null)
const sourcingJob = ref<Job | null>(null)

function loadSourcingProposals(job: Job) {
  sourcingLoading.value = true
  HrApi.getJobSourcingProposals(job.id)
    .then((response) => {
      const proposals = response.data || []
      sourcingProposal.value = proposals.find((p) => p.status === 'PENDING') || proposals[0] || null
      sourcingDrawerVisible.value = true
    })
    .catch(() => {})
    .finally(() => {
      sourcingLoading.value = false
    })
}

function startSourcing(job: Job) {
  MsgConfirm(
    'AI 人才库激活',
    '将检索人才库中未投递该职位的候选人，按硬条件核对与语义匹配生成内部激活清单（只出清单，不自动联系候选人）。',
  )
    .then(() => {
      sourcingScopeJob.value = job
      sourcingResumeDatabaseIds.value = []
      loadAgentResumeDatabases()
      sourcingScopeDialogVisible.value = true
    })
    .catch(() => {})
}

function confirmSourcing() {
  const job = sourcingScopeJob.value
  if (!job) return
  sourcingScopeDialogVisible.value = false
  sourcingRunning.value = job.id
  HrApi.runSourcingAgent(job.id, sourcingResumeDatabaseIds.value)
    .then((response) => {
      if (response.data?.status === 'SKIPPED' || response.data?.status === 'FAILED') {
        MsgConfirm('AI 暂不可用', (response.data?.error as string) || '生成未成功，请稍后重试。', {
          showCancelButton: false, confirmButtonText: '知道了',
        }).catch(() => {})
      } else {
        MsgSuccess('激活清单已生成')
        sourcingJob.value = job
        loadSourcingProposals(job)
      }
    })
    .catch(() => {})
    .finally(() => {
      sourcingRunning.value = ''
    })
}

function dismissSourcingProposal() {
  if (!sourcingProposal.value) return
  MsgConfirm('忽略清单', '确定忽略这份激活清单？')
    .then(() => {
      if (!sourcingProposal.value) return
      sourcingSaving.value = true
      HrApi.dismissProposal(sourcingProposal.value.id, { decision_note: 'HR 忽略激活清单' })
        .then(() => {
          MsgSuccess('已忽略')
          if (sourcingJob.value) loadSourcingProposals(sourcingJob.value)
        })
        .catch(() => {})
        .finally(() => {
          sourcingSaving.value = false
        })
    })
    .catch(() => {})
}

const draftDialogVisible = ref(false)
const draftDrawerVisible = ref(false)
const draftLoading = ref(false)
const draftRunning = ref(false)
const draftSaving = ref(false)
const draftProposal = ref<CommunicationDraftProposal | null>(null)
const draftTarget = ref<{ application_id: string; candidate_name: string; job: Job } | null>(null)
const draftForm = reactive({ scenario: 'PROGRESS' as string, context_note: '' })

function draftScenarioLabel(scenario: string) {
  const labels: Record<string, string> = { REJECT: '婉拒/淘汰', PROGRESS: '进度通知', FAQ: '答疑', OTHER: '其他' }
  return labels[scenario] || scenario
}

function openDraftDialog(job: Job, application: JobApplication) {
  draftTarget.value = { application_id: application.application_id, candidate_name: application.candidate_name, job }
  draftForm.scenario = 'PROGRESS'
  draftForm.context_note = ''
  draftDialogVisible.value = true
}

function loadDraftProposals(applicationId: string) {
  draftLoading.value = true
  HrApi.getCommunicationDrafts(applicationId)
    .then((response) => {
      const proposals = response.data || []
      draftProposal.value = proposals.find((p) => p.status === 'PENDING') || proposals[0] || null
      draftDrawerVisible.value = true
    })
    .catch(() => {})
    .finally(() => {
      draftLoading.value = false
    })
}

function confirmGenerateDraft() {
  if (!draftTarget.value) return
  draftRunning.value = true
  HrApi.runCommunicationDraft(draftTarget.value.application_id, {
    scenario: draftForm.scenario,
    context_note: draftForm.context_note.trim(),
  })
    .then((response) => {
      draftDialogVisible.value = false
      if (response.data?.status === 'SKIPPED' || response.data?.status === 'FAILED') {
        MsgConfirm('AI 暂不可用', (response.data?.error as string) || '生成未成功，请稍后重试。', {
          showCancelButton: false, confirmButtonText: '知道了',
        }).catch(() => {})
      } else {
        MsgSuccess('草稿已生成（外发前请人工审核）')
        loadDraftProposals(draftTarget.value!.application_id)
      }
    })
    .catch(() => {})
    .finally(() => {
      draftRunning.value = false
    })
}

function copyDraft() {
  if (!draftProposal.value?.payload.draft) return
  navigator.clipboard.writeText(draftProposal.value.payload.draft)
    .then(() => MsgSuccess('草稿已复制'))
    .catch(() => MsgError('复制失败，请手动选择复制'))
}

function dismissDraftProposal() {
  if (!draftProposal.value) return
  MsgConfirm('忽略草稿', '确定忽略这份沟通草稿？')
    .then(() => {
      if (!draftProposal.value || !draftTarget.value) return
      draftSaving.value = true
      HrApi.dismissProposal(draftProposal.value.id, { decision_note: 'HR 忽略沟通草稿' })
        .then(() => {
          MsgSuccess('已忽略')
          loadDraftProposals(draftTarget.value!.application_id)
        })
        .catch(() => {})
        .finally(() => {
          draftSaving.value = false
        })
    })
    .catch(() => {})
}

function extractSkillsFromDescription() {
  const description = jobForm.description.trim()
  if (!description) return
  extractingSkills.value = true
  HrApi.extractSkills(description)
    .then((response) => {
      jobSkillsText.value = response.data.skills.join(', ')
      MsgSuccess('技能已抽取，可编辑后随职位保存')
    })
    .catch(() => {})
    .finally(() => {
      extractingSkills.value = false
    })
}

function saveJob() {
  if (!jobForm.name.trim()) return
  if (jobForm.status === 'CLOSED' && !jobForm.close_reason) {
    MsgError('关闭职位需要选择关闭原因')
    return
  }
  if (editingJob.value && jobForm.status === 'CLOSED' && editingJob.value.status !== 'CLOSED') {
    // R2 两阶段关闭：先预览 STRICT/BULK，由确认窗决定关闭方式
    openCloseDialog(editingJob.value)
    return
  }
  saving.value = true
  const data = {
    ...jobForm,
    skill_requirements: jobSkillsText.value.split(',').map((skill) => skill.trim()).filter(Boolean),
  }
  const request = editingJob.value ? HrApi.updateJob(editingJob.value.id, data) : HrApi.createJob(data)
  request.then(() => {
    jobDialogVisible.value = false
    MsgSuccess('职位已保存')
    refresh()
  }).catch(() => {}).finally(() => { saving.value = false })
}

function toggleMyJobs() {
  filters.owner_id = filters.owner_id ? '' : user.userInfo?.id || ''
  refresh()
}

function resetJobFilters() {
  filters.name = ''
  filters.status = ''
  filters.owner_id = ''
  refresh()
}

function goPipeline(job: Job) {
  router.push({ path: '/hr/pipeline', query: { job: job.id } })
}

function openCloseDialog(job: Job) {
  closingJob.value = job
  closeReason.value = ''
  bulkConfirmed.value = false
  closePreview.value = null
  closeDialogVisible.value = true
  HrApi.getJobClosePreview(job.id).then((response) => {
    closePreview.value = response.data
    closeMode.value = response.data.active_application_count > 0 ? 'BULK' : 'STRICT'
  }).catch(() => { closeDialogVisible.value = false })
}

function confirmCloseJob() {
  if (!closingJob.value || !closeReason.value) return
  if (hasActiveApplications.value && !bulkConfirmed.value) {
    MsgError('存在在途申请，请先勾选批量确认')
    return
  }
  saving.value = true
  HrApi.closeJobV2(closingJob.value.id, {
    close_reason: closeReason.value as JobCloseReason,
    mode: closeMode.value,
    bulk_confirmed: bulkConfirmed.value || !hasActiveApplications.value,
  })
    .then((response) => {
      closeDialogVisible.value = false
      MsgSuccess(`职位已关闭，收尾 ${response.data.closed_count} 条在途申请`)
      refresh()
    })
    .catch(() => {})
    .finally(() => { saving.value = false })
}

function reopenJob(job: Job) {
  MsgConfirm('恢复招聘', `将把“${job.name}”重新开放，并清空关闭原因。`)
    .then(() => HrApi.reopenJob(job.id))
    .then(() => {
      MsgSuccess('职位已恢复')
      refresh()
    })
    .catch(() => {})
}


function isActiveApplication(application: JobApplication): boolean {
  return application.status === 'ACTIVE'
}

function isOfferStage(application: JobApplication): boolean {
  return application.status === 'ACTIVE' && application.current_stage?.key === 'OFFER'
}

/** 卡片菜单命令：终态走 terminal 命令 API，恢复走 restore 命令 API（不再直接改 status） */
function onCardCommand(cmd: string, job: Job, application: JobApplication) {
  if (cmd === 'ai') openAiDrawer(job, application)
  else if (cmd === 'ai-run') openAiDrawer(job, application)
  else if (cmd === 'draft') openDraftDialog(job, application)
  else if (cmd === 'reject') openStatusChangeDialog(application, 'reject', job)
  else if (cmd === 'withdraw') openStatusChangeDialog(application, 'withdraw', job)
  else if (cmd === 'close') openStatusChangeDialog(application, 'close', job)
  else if (cmd === 'restore') openStatusChangeDialog(application, 'restore', job)
}

function openStatusChangeDialog(application: JobApplication, action: ApplicationAction, job: Job) {
  statusDialogAssignment.value = application
  statusDialogJob.value = job
  statusDialogAction.value = action
  statusDialogReason.value = ''
  statusDialogNote.value = ''
  statusDialogVisible.value = true
}

function confirmStatusChange() {
  const application = statusDialogAssignment.value
  const job = statusDialogJob.value
  const action = statusDialogAction.value
  if (!application || !job || !action) return
  const applicationId = application.application_id
  if (action === 'restore') {
    if (!statusDialogNote.value.trim()) {
      MsgError('请填写恢复原因')
      return
    }
    saving.value = true
    HrApi.restoreApplication(applicationId, { reason_text: statusDialogNote.value.trim() })
      .then(() => {
        statusDialogVisible.value = false
        MsgSuccess('申请已恢复')
        loadJobDetail(job)
      })
      .catch(() => {})
      .finally(() => { saving.value = false })
    return
  }
  if (!statusDialogReason.value) {
    MsgError('请选择终止原因')
    return
  }
  saving.value = true
  HrApi.terminalApplication(applicationId, { action, termination_reason: statusDialogReason.value })
    .then(() => {
      statusDialogVisible.value = false
      MsgSuccess('操作成功')
      loadJobDetail(job)
    })
    .catch(() => {})
    .finally(() => { saving.value = false })
}

function addMatchToJob(job: Job, match: JobMatchCandidate) {
  HrApi.createApplication(job.id, match.candidate_id)
    .then(() => {
      MsgSuccess(`已将 ${match.name} 加入职位`)
      loadMatches(job)
      loadJobDetail(job)
      refresh()
    })
    .catch(() => {})
}

function resetInterviewForm() {
  interviewForm.interviewer = ''
  interviewForm.interviewer_user_id = null
  interviewForm.feedback_deadline = null
  interviewForm.scheduled_at = null
}

function openInterviewDrawer(job: Job, application: JobApplication) {
  interviewAssignment.value = application
  interviewCandidateName.value = application.candidate_name || ''
  interviewList.value = []
  addInterviewFormVisible.value = false
  resetInterviewForm()
  interviewDrawerVisible.value = true
  HrApi.getInterviewsByApplication(application.application_id).then((response) => {
    interviewList.value = response.data
  })
}

function reloadInterviewsByApplication() {
  const application = interviewAssignment.value
  if (application) {
    HrApi.getInterviewsByApplication(application.application_id).then((response) => {
      interviewList.value = response.data
    })
  }
}

function createInterviewRecord() {
  const application = interviewAssignment.value
  if (!application) return
  HrApi.createInterviewByApplication(application.application_id, { ...interviewForm })
    .then(() => {
      MsgSuccess('面试已安排')
      addInterviewFormVisible.value = false
      resetInterviewForm()
      reloadInterviewsByApplication()
    })
    .catch(() => {})
}

function updateInterviewRecord(interview: Interview) {
  HrApi.updateInterview(interview.id, { status: interview.status, feedback: interview.feedback })
    .then(() => MsgSuccess('面试记录已更新'))
    .catch(() => {})
}

const offerDrawerVisible = ref(false)
const addOfferFormVisible = ref(false)
const approveOfferDialogVisible = ref(false)
const offerAssignment = ref<JobApplication | null>(null)
const offerCandidateName = ref('')
const offerJobName = ref('')
const offerList = ref<Offer[]>([])
const offerForm = reactive({ salary_amount: null as number | null, currency: 'CNY', note: '' })
const approveForm = reactive({ approval_status: '' as string })
const approveTarget = ref<Offer | null>(null)

function offerTimeText(offer: Offer) {
  const time = offer.accepted_at || offer.rejected_at || offer.withdrawn_at || offer.sent_at || offer.approved_at
  return time ? new Date(time).toLocaleString() : '-'
}

function resetOfferForm() {
  offerForm.salary_amount = null
  offerForm.currency = 'CNY'
  offerForm.note = ''
}

function openOfferDrawer(job: Job, application: JobApplication) {
  offerAssignment.value = application
  offerCandidateName.value = application.candidate_name || ''
  offerJobName.value = job.name
  offerList.value = []
  addOfferFormVisible.value = false
  resetOfferForm()
  offerDrawerVisible.value = true
  HrApi.getOffersByApplication(application.application_id).then((response) => {
    offerList.value = response.data
  })
}

function createOfferRecord() {
  const application = offerAssignment.value
  if (!application) return
  HrApi.createOfferByApplication(application.application_id, {
    salary_amount: offerForm.salary_amount == null ? null : String(offerForm.salary_amount),
    currency: offerForm.currency || 'CNY',
    note: offerForm.note,
  })
    .then(() => {
      MsgSuccess('Offer 已创建')
      addOfferFormVisible.value = false
      resetOfferForm()
      reloadOffers()
    })
    .catch(() => {})
}

function reloadOffers() {
  const application = offerAssignment.value
  if (application) {
    HrApi.getOffersByApplication(application.application_id).then((response) => {
      offerList.value = response.data
    })
  }
}

function openApproveOfferDialog(offer: Offer) {
  approveTarget.value = offer
  approveForm.approval_status = 'APPROVED'
  approveOfferDialogVisible.value = true
}

function approveOfferRecord() {
  if (!approveTarget.value) return
  HrApi.approveOffer(approveTarget.value.id, { approval_status: approveForm.approval_status })
    .then(() => {
      MsgSuccess('审批已提交')
      approveOfferDialogVisible.value = false
      reloadOffers()
    })
    .catch(() => {})
}

function sendOfferRecord(offer: Offer) {
  HrApi.sendOffer(offer.id)
    .then(() => {
      MsgSuccess('Offer 已发送')
      reloadOffers()
    })
    .catch(() => {})
}

function acceptOfferRecord(offer: Offer) {
  MsgConfirm('接受 Offer', '确认接受第 ' + offer.version + ' 版 Offer？申请将自动进入「已入职」，并触发入职交接。', { confirmButtonClass: 'danger' })
    .then(() => HrApi.acceptOffer(offer.id))
    .then(() => {
      MsgSuccess('Offer 已接受，已触发入职交接')
      reloadOffers()
      refresh()
    })
    .catch(() => {})
}

function rejectOfferRecord(offer: Offer) {
  MsgConfirm('拒绝 Offer', '确认拒绝第 ' + offer.version + ' 版 Offer？拒绝原因请直接修改该版本备注。', { confirmButtonClass: 'danger' })
    .then(() => HrApi.rejectOffer(offer.id, { note: offer.note }))
    .then(() => {
      MsgSuccess('Offer 已标记拒绝')
      reloadOffers()
    })
    .catch(() => {})
}

function withdrawOfferRecord(offer: Offer) {
  MsgConfirm('撤回 Offer', '确认撤回第 ' + offer.version + ' 版 Offer？', { confirmButtonClass: 'danger' })
    .then(() => HrApi.withdrawOffer(offer.id))
    .then(() => {
      MsgSuccess('Offer 已撤回')
      reloadOffers()
    })
    .catch(() => {})
}

function uploadOfferAttachment(offer: Offer, file: File) {
  HrApi.uploadOfferAttachment(offer.id, file)
    .then(() => {
      MsgSuccess('附件已上传')
      reloadOffers()
    })
    .catch(() => {})
  return false
}

function removeOfferAttachment(offer: Offer) {
  HrApi.deleteOfferAttachment(offer.id)
    .then(() => {
      MsgSuccess('附件已删除')
      reloadOffers()
    })
    .catch(() => {})
}

function downloadOfferAttachment(offer: Offer) {
  HrApi.downloadOfferAttachment(offer.id, offer.attachment_name || 'offer.pdf')
}

// ---------- AI 初筛评估（D1 报告卡） ----------
const aiDrawerVisible = ref(false)
const aiApplication = ref<JobApplication | null>(null)
const aiJob = ref<Job | null>(null)
const aiCandidateName = ref('')
const aiJobName = ref('')
const aiProposals = ref<AgentProposal[]>([])
const aiLoading = ref(false)
const aiRunning = ref(false)
const resumeDatabases = ref<ResumeDatabase[]>([])
const resumeDatabaseLoading = ref(false)
const aiResumeDatabaseIds = ref<string[]>([])
const activeResumeDatabases = computed(() => resumeDatabases.value.filter((database) => database.status === 'ACTIVE'))

function agentActionLabel(action: string) {
  return ({ ADVANCE: '建议推进', DECLINE: '建议婉拒', HOLD: '建议人工' } as Record<string, string>)[action] || action
}

function agentActionTagType(action: string) {
  if (action === 'ADVANCE') return 'success'
  if (action === 'DECLINE') return 'danger'
  return 'warning'
}

function proposalStatusLabel(status: string) {
  return ({ PENDING: '待审批', ACCEPTED: '已接受', DISMISSED: '已忽略', EXPIRED: '已过期' } as Record<string, string>)[status] || status
}

function proposalStatusTagType(status: string) {
  if (status === 'PENDING') return 'warning'
  if (status === 'ACCEPTED') return 'success'
  return 'info'
}

function aiLatestProposal() {
  return aiProposals.value[0] || null
}

function loadAgentResumeDatabases() {
  if (resumeDatabases.value.length || resumeDatabaseLoading.value) return
  resumeDatabaseLoading.value = true
  HrApi.getResumeDatabases()
    .then((response) => { resumeDatabases.value = response.data || [] })
    .catch(() => {})
    .finally(() => { resumeDatabaseLoading.value = false })
}

function openAiDrawer(job: Job, application: JobApplication) {
  aiResumeDatabaseIds.value = []
  loadAgentResumeDatabases()
  aiApplication.value = application
  aiJob.value = job
  aiCandidateName.value = application.candidate_name || ''
  aiJobName.value = job.name
  aiDrawerVisible.value = true
  loadAiProposals(application.application_id)
}

function loadAiProposals(applicationId: string) {
  aiLoading.value = true
  HrApi.getApplicationProposals(applicationId)
    .then((response) => { aiProposals.value = response.data })
    .catch(() => {})
    .finally(() => { aiLoading.value = false })
}

function runAiAssessment() {
  const application = aiApplication.value
  const job = aiJob.value
  if (!application) return
  aiRunning.value = true
  HrApi.runScreeningAgent(application.application_id, aiResumeDatabaseIds.value)
    .then((response) => {
      const status = (response.data as Record<string, unknown>)?.status
      MsgSuccess(status === 'SUCCEEDED' ? 'AI 评估完成' : 'AI 评估未生成提案（' + String(status) + '）')
      loadAiProposals(application.application_id)
      if (job) { loadJobDetail(job); refresh() }
    })
    .catch(() => {})
    .finally(() => { aiRunning.value = false })
}

function acceptAiProposal(proposal: AgentProposal) {
  MsgConfirm('接受建议', `确认执行「${agentActionLabel(proposal.action)}」？将调用 ATS 命令更新流程。`, { confirmButtonClass: 'danger' })
    .then(() => HrApi.acceptProposal(proposal.id, { decision_note: 'HR 确认执行' }))
    .then(() => {
      MsgSuccess('已接受并执行')
      const application = aiApplication.value
      const job = aiJob.value
      if (application) loadAiProposals(application.application_id)
      if (job) { loadJobDetail(job); refresh() }
    })
    .catch(() => {})
}

function dismissAiProposal(proposal: AgentProposal) {
  MsgConfirm('忽略建议', '确认忽略该建议？流程保持现状，由人工处理。')
    .then(() => HrApi.dismissProposal(proposal.id, { decision_note: 'HR 忽略' }))
    .then(() => {
      MsgSuccess('已忽略')
      const application = aiApplication.value
      const job = aiJob.value
      if (application) loadAiProposals(application.application_id)
      if (job) loadJobDetail(job)
    })
    .catch(() => {})
}


function openJobFromQuery() {
  if (route.query.new === '1') {
    openJobDialog()
  }
}

onMounted(() => {
  loadMembers()
  loadJobs()
  openJobFromQuery()
})
watch(() => route.query.new, (isNew) => {
  if (isNew === '1') openJobDialog()
})
</script>


<style scoped>
.hr-page { min-width: 0; }
.gap-12 { gap: 12px; }
.assignment-panel { padding: 12px 32px; }

.kanban-board {
  display: flex;
  gap: 12px;
  align-items: flex-start;
  overflow-x: auto;
  padding-bottom: 4px;
}

.kanban-col {
  flex: 1 1 0;
  min-width: 190px;
  max-width: 250px;
  background: var(--el-fill-color-light);
  border-radius: 8px;
  padding: 8px;
  display: flex;
  flex-direction: column;
  max-height: 520px;

  &--readonly {
    background: var(--el-fill-color-lighter);
  }
}

.kanban-col__header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 2px 6px 10px;
  font-size: 13px;
}

.kanban-col__title {
  font-weight: 600;
}

.kanban-col__body {
  display: flex;
  flex-direction: column;
  gap: 8px;
  overflow-y: auto;
  min-height: 48px;
  flex: 1;
  padding-bottom: 4px;
}

.kanban-card {
  background: var(--el-bg-color);
  border: 1px solid var(--el-border-color-lighter);
  border-radius: 6px;
  padding: 8px 10px;
  box-shadow: 0 1px 2px rgba(0, 0, 0, 0.04);
  transition: border-color 0.15s;

  &:hover {
    border-color: var(--el-color-primary-light-5);
  }

  &--ghost {
    opacity: 0.4;
  }
}

.kanban-card__header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 6px;
  gap: 6px;
}

.kanban-card__name {
  font-weight: 600;
  font-size: 13px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.kanban-card__drag {
  cursor: grab;
  color: var(--el-text-color-placeholder);
  margin-right: 6px;
  flex-shrink: 0;
}

.kanban-card__meta {
  display: flex;
  gap: 4px;
  flex-wrap: wrap;
  margin-bottom: 6px;
}

.kanban-card__footer {
  display: flex;
  justify-content: space-between;
  align-items: center;
  gap: 6px;
  font-size: 12px;
}

.ai-block {
  border: 1px solid var(--el-border-color-lighter);
  border-radius: 8px;
  padding: 12px 16px;
  background: var(--el-fill-color-lighter);
}

.ai-title {
  font-weight: 600;
  font-size: 13px;
  margin-bottom: 8px;
  color: var(--el-text-color-primary);
}

.ai-list {
  margin: 0;
  padding-left: 18px;
  color: var(--el-text-color-regular);
  line-height: 1.9;
}

.jd-grid {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 12px;
}

.jd-pre {
  max-height: 320px;
  overflow: auto;
  white-space: pre-wrap;
  word-break: break-word;
  font-size: 12px;
  line-height: 1.7;
  margin: 0;
}
</style>
