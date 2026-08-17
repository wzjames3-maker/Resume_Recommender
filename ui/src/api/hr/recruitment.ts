import type { Result } from '@/request/Result'
import { exportFile, exportFilePost, del, get, post, put } from '@/request'
import type {
  AgentStats,
  AiConditions,
  AgentProposal,
  Application,
  ApplicationEvent,
  Assignment,
  Candidate,
  CandidateDetail,
  CommunicationDraftProposal,
  CopilotProposal,
  DuplicateCheckCandidate,
  JDProposal,
  SourcingProposal,
  HrAccessMember,
  HrAccessSetItem,
  HrAuditAction,
  HrAuditLogPage,
  HrAuditObjectType,
  HrConfig,
  HrRole,
  HandoffRecord,
  ImportReport,
  Interview,
  Job,
  JobClosePreview,
  JobCloseReason,
  JobCloseResult,
  JobDetail,
  JobMatchPage,
  JobStage,
  MyInterview,
  Offer,
  PageResult,
  ResumeBatchStatus,
  ResumeFile,
  ResumeFlowLog,
  ResumeSearchMode,
  ResumeSearchResponse,
  ResumeUploadResult,
} from '@/api/type/hr'
import type { pageRequest } from '@/api/type/common'
import useStore from '@/stores'

const prefix: any = { _value: '/workspace/' }
Object.defineProperty(prefix, 'value', {
  get: function () {
    const { user } = useStore()
    return `${this._value}${user.getWorkspaceId()}/hr`
  },
})

const getCandidates = (page: pageRequest, params?: Record<string, unknown>) =>
  get(`${prefix.value}/candidates/${page.current_page}/${page.page_size}`, params) as Promise<Result<PageResult<Candidate>>>

const createCandidate = (data: Partial<Candidate>) =>
  post(`${prefix.value}/candidates`, data) as Promise<Result<Candidate>>

const getCandidate = (candidateId: string) =>
  get(`${prefix.value}/candidates/${candidateId}`) as Promise<Result<CandidateDetail>>

const updateCandidate = (candidateId: string, data: Partial<Candidate>) =>
  put(`${prefix.value}/candidates/${candidateId}`, data) as Promise<Result<Candidate>>

const archiveCandidate = (candidateId: string) =>
  put(`${prefix.value}/candidates/${candidateId}/archive`) as Promise<Result<Candidate>>

const restoreCandidate = (candidateId: string) =>
  put(`${prefix.value}/candidates/${candidateId}/restore`) as Promise<Result<Candidate>>

const deleteCandidate = (candidateId: string) =>
  put(`${prefix.value}/candidates/${candidateId}/delete`) as Promise<Result<Candidate>>

const exportCandidates = (filters: Record<string, unknown>) =>
  exportFilePost('candidates.csv', `${prefix.value}/export/candidates`, {}, { filters })

const importCandidates = (file: File) => {
  const formData = new FormData()
  formData.append('file', file)
  return post(`${prefix.value}/import/candidates`, formData) as Promise<Result<ImportReport>>
}

const downloadImportTemplate = () =>
  exportFile('candidates_import_template.csv', `${prefix.value}/import/candidates/template`, {}, undefined)

const getJobs = (page: pageRequest, params?: Record<string, unknown>) =>
  get(`${prefix.value}/jobs/${page.current_page}/${page.page_size}`, params) as Promise<Result<PageResult<Job>>>

const createJob = (data: Partial<Job>) => post(`${prefix.value}/jobs`, data) as Promise<Result<Job>>

const getJob = (jobId: string) => get(`${prefix.value}/jobs/${jobId}`) as Promise<Result<JobDetail>>

const updateJob = (jobId: string, data: Partial<Job>) =>
  put(`${prefix.value}/jobs/${jobId}`, data) as Promise<Result<Job>>

const closeJob = (jobId: string, closeReason: JobCloseReason) =>
  put(`${prefix.value}/jobs/${jobId}/close`, { close_reason: closeReason }) as Promise<Result<{ closed_count: number }>>

const reopenJob = (jobId: string) => put(`${prefix.value}/jobs/${jobId}/reopen`) as Promise<Result<Job>>

const getJobStages = (jobId: string) =>
  get(`${prefix.value}/jobs/${jobId}/stages`) as Promise<Result<JobStage[]>>

const getJobClosePreview = (jobId: string) =>
  get(`${prefix.value}/jobs/${jobId}/close-preview`) as Promise<Result<JobClosePreview>>

const closeJobV2 = (
  jobId: string,
  data: { close_reason: JobCloseReason; mode: 'STRICT' | 'BULK'; bulk_confirmed?: boolean },
) => post(`${prefix.value}/jobs/${jobId}/close`, data) as Promise<Result<JobCloseResult>>

const createApplication = (jobId: string, candidateId: string, extra: Record<string, unknown> = {}) =>
  post(`${prefix.value}/applications`, {
    job_id: jobId,
    candidate_id: candidateId,
    ...extra,
  }) as Promise<Result<Application>>

const getApplications = (page: pageRequest, params?: Record<string, unknown>) =>
  get(`${prefix.value}/applications/page/${page.current_page}/${page.page_size}`, params) as Promise<Result<PageResult<Application>>>

const moveApplicationStage = (applicationId: string, data: Record<string, unknown>) =>
  post(`${prefix.value}/applications/${applicationId}/move-stage`, data) as Promise<Result<Application>>

const terminalApplication = (applicationId: string, data: Record<string, unknown>) =>
  post(`${prefix.value}/applications/${applicationId}/terminal`, data) as Promise<Result<Application>>

const restoreApplication = (applicationId: string, data: Record<string, unknown>) =>
  post(`${prefix.value}/applications/${applicationId}/restore`, data) as Promise<Result<Application>>

const getApplicationEvents = (applicationId: string) =>
  get(`${prefix.value}/applications/${applicationId}/events`) as Promise<Result<ApplicationEvent[]>>

const createInterviewByApplication = (applicationId: string, data: Record<string, unknown>) =>
  post(`${prefix.value}/applications/${applicationId}/interviews`, data) as Promise<Result<Interview>>

const getInterviewsByApplication = (applicationId: string) =>
  get(`${prefix.value}/applications/${applicationId}/interviews`) as Promise<Result<Interview[]>>

const createOfferByApplication = (applicationId: string, data: Partial<Offer>) =>
  post(`${prefix.value}/applications/${applicationId}/offers`, data) as Promise<Result<Offer>>

const getOffersByApplication = (applicationId: string) =>
  get(`${prefix.value}/applications/${applicationId}/offers`) as Promise<Result<Offer[]>>

const getApplicationProposals = (applicationId: string) =>
  get(`${prefix.value}/applications/${applicationId}/proposals`) as Promise<Result<AgentProposal[]>>

const acceptProposal = (proposalId: string, data: Record<string, unknown>) =>
  post(`${prefix.value}/proposals/${proposalId}/accept`, data) as Promise<Result<AgentProposal>>

const dismissProposal = (proposalId: string, data: Record<string, unknown>) =>
  post(`${prefix.value}/proposals/${proposalId}/dismiss`, data) as Promise<Result<AgentProposal>>

const runScreeningAgent = (applicationId: string) =>
  post(`${prefix.value}/agents/SCREENING/run`, { application_id: applicationId }) as Promise<Result<Record<string, unknown>>>

const runJdDraftAgent = (jobId: string) =>
  post(`${prefix.value}/agents/JD_DRAFT/run`, { job_id: jobId }) as Promise<Result<Record<string, unknown>>>

const runInterviewCopilot = (interviewId: string, data: Record<string, unknown>) =>
  post(`${prefix.value}/agents/INTERVIEW_COPILOT/run`, { interview_id: interviewId, ...data }) as Promise<Result<Record<string, unknown>>>

const getJobProposals = (jobId: string) =>
  get(`${prefix.value}/jobs/${jobId}/proposals`) as Promise<Result<JDProposal[]>>

const getInterviewProposals = (interviewId: string) =>
  get(`${prefix.value}/interviews/${interviewId}/proposals`) as Promise<Result<CopilotProposal[]>>

const getJobSourcingProposals = (jobId: string) =>
  get(`${prefix.value}/jobs/${jobId}/proposals`) as Promise<Result<SourcingProposal[]>>

const runSourcingAgent = (jobId: string) =>
  post(`${prefix.value}/agents/SOURCING/run`, { job_id: jobId }) as Promise<Result<Record<string, unknown>>>

const runCommunicationDraft = (applicationId: string, data: Record<string, unknown>) =>
  post(`${prefix.value}/agents/COMMUNICATION_DRAFT/run`, { application_id: applicationId, ...data }) as Promise<Result<Record<string, unknown>>>

const getCommunicationDrafts = (applicationId: string) =>
  get(`${prefix.value}/applications/${applicationId}/proposals`) as Promise<Result<CommunicationDraftProposal[]>>

const getAgentStats = () => get(`${prefix.value}/agents/stats`) as Promise<Result<AgentStats>>

const createAssignment = (jobId: string, candidateId: string, note = '', extra: Partial<Assignment> = {}) =>
  post(`${prefix.value}/jobs/${jobId}/assignments`, {
    candidate_id: candidateId,
    note,
    ...extra,
  }) as Promise<Result<Assignment>>

const updateAssignment = (assignmentId: string, data: Partial<Assignment>) =>
  put(`${prefix.value}/assignments/${assignmentId}`, data) as Promise<Result<Assignment>>

const uploadResumes = (files: File[], sourceChannel: string) => {
  const formData = new FormData()
  files.forEach((file) => formData.append('files', file))
  formData.append('source_channel', sourceChannel)
  return post(`${prefix.value}/candidates/resumes`, formData) as Promise<Result<ResumeUploadResult[]>>
}

const getCandidateResumes = (candidateId: string) =>
  get(`${prefix.value}/candidates/${candidateId}/resumes`) as Promise<Result<ResumeFile[]>>

const deleteResume = (resumeId: string) => del(`${prefix.value}/resumes/${resumeId}`) as Promise<Result<boolean>>

const getJobMatches = (jobId: string, page: pageRequest) =>
  get(`${prefix.value}/jobs/${jobId}/matches/${page.current_page}/${page.page_size}`) as Promise<Result<JobMatchPage>>

const createInterview = (assignmentId: string, data: Record<string, unknown>) =>
  post(`${prefix.value}/assignments/${assignmentId}/interviews`, data) as Promise<Result<Interview>>

const getInterviews = (assignmentId: string) =>
  get(`${prefix.value}/assignments/${assignmentId}/interviews`) as Promise<Result<Interview[]>>

const updateInterview = (interviewId: string, data: Partial<Interview>) =>
  put(`${prefix.value}/interviews/${interviewId}`, data) as Promise<Result<Interview>>

const getMyInterviews = () =>
  get(`${prefix.value}/interviews/mine`) as Promise<Result<MyInterview[]>>

const submitInterviewFeedback = (interviewId: string, data: Record<string, unknown>) =>
  put(`${prefix.value}/interviews/${interviewId}/feedback`, data) as Promise<Result<Interview>>

const getOffers = (assignmentId: string) =>
  get(`${prefix.value}/assignments/${assignmentId}/offers`) as Promise<Result<Offer[]>>

const getAllOffers = (page: pageRequest, params?: Record<string, unknown>) =>
  get(`${prefix.value}/offers/page/${page.current_page}/${page.page_size}`, params) as Promise<Result<PageResult<Offer>>>

const createOffer = (assignmentId: string, data: Partial<Offer>) =>
  post(`${prefix.value}/assignments/${assignmentId}/offers`, data) as Promise<Result<Offer>>

const getOffer = (offerId: string) => get(`${prefix.value}/offers/${offerId}`) as Promise<Result<Offer>>

const updateOffer = (offerId: string, data: Partial<Offer>) =>
  put(`${prefix.value}/offers/${offerId}`, data) as Promise<Result<Offer>>

const approveOffer = (offerId: string, data: Record<string, unknown>) =>
  put(`${prefix.value}/offers/${offerId}/approve`, data) as Promise<Result<Offer>>

const sendOffer = (offerId: string) => put(`${prefix.value}/offers/${offerId}/send`) as Promise<Result<Offer>>

const acceptOffer = (offerId: string) =>
  put(`${prefix.value}/offers/${offerId}/accept`) as Promise<Result<Offer>>

const rejectOffer = (offerId: string, data: Record<string, unknown>) =>
  put(`${prefix.value}/offers/${offerId}/reject`, data) as Promise<Result<Offer>>

const withdrawOffer = (offerId: string) =>
  put(`${prefix.value}/offers/${offerId}/withdraw`) as Promise<Result<Offer>>

const uploadOfferAttachment = (offerId: string, file: File) => {
  const formData = new FormData()
  formData.append('file', file)
  return post(`${prefix.value}/offers/${offerId}/attachment`, formData) as Promise<Result<Offer>>
}

const deleteOfferAttachment = (offerId: string) =>
  del(`${prefix.value}/offers/${offerId}/attachment`) as Promise<Result<Offer>>

const downloadOfferAttachment = (offerId: string, fileName: string) =>
  exportFile(fileName, `${prefix.value}/offers/${offerId}/attachment/download`, {}, undefined)

const getHandoffs = (page: pageRequest) =>
  get(`${prefix.value}/handoffs/${page.current_page}/${page.page_size}`) as Promise<Result<PageResult<HandoffRecord>>>

const retryHandoff = (handoffId: string) =>
  post(`${prefix.value}/handoffs/${handoffId}/retry`) as Promise<Result<HandoffRecord>>

const getHandoffConfig = () => get(`${prefix.value}/handoff/config`) as Promise<Result<{ target_type: string; webhook_url: string }>>

const putHandoffConfig = (data: Record<string, unknown>) =>
  put(`${prefix.value}/handoff/config`, data) as Promise<Result<{ target_type: string; webhook_url: string }>>

const getAiConfig = () => get(`${prefix.value}/ai/config`) as Promise<Result<HrConfig>>

const putAiConfig = (data: Record<string, unknown>) =>
  put(`${prefix.value}/ai/config`, data) as Promise<Result<HrConfig>>

const parseSearch = (query: string) =>
  post(`${prefix.value}/ai/search-parse`, { query }) as Promise<Result<{ conditions: AiConditions }>>

const extractSkills = (description: string) =>
  post(`${prefix.value}/ai/extract-skills`, { description }) as Promise<Result<{ skills: string[] }>>

const getResumeBatchStatus = (ids: string[]) =>
  get(`${prefix.value}/resumes/batch-status`, { ids: ids.join(',') }) as Promise<Result<ResumeBatchStatus[]>>

const getResumeContent = (resumeId: string) =>
  get(`${prefix.value}/resumes/${resumeId}/content`) as Promise<Result<{ content: string }>>

const getResumeFlowLogs = (resumeId: string) =>
  get(`${prefix.value}/resumes/${resumeId}/flow-logs`) as Promise<Result<ResumeFlowLog[]>>

const searchResumes = (data: {
  query: string
  top_k?: number
  recall_k?: number
  similarity?: number
  mode?: ResumeSearchMode
}) =>
  post(`${prefix.value}/resumes/search`, data) as Promise<Result<ResumeSearchResponse>>

const downloadResume = (resumeId: string, fileName: string) =>
  exportFile(fileName, `${prefix.value}/resumes/${resumeId}/download`, {}, undefined)

const checkDuplicate = (data: Record<string, unknown>) =>
  post(`${prefix.value}/candidates/check-duplicate`, data) as Promise<Result<{ candidates: DuplicateCheckCandidate[] }>>

const mergeCandidates = (primaryId: string, secondaryId: string) =>
  post(`${prefix.value}/candidates/${primaryId}/merge`, { secondary_id: secondaryId }) as Promise<Result<CandidateDetail>>

const getAccess = () => get(`${prefix.value}/access`) as Promise<Result<HrAccessMember[]>>

const updateAccess = (items: HrAccessSetItem[]) =>
  put(`${prefix.value}/access`, { items }) as Promise<Result<HrAccessMember[]>>

const getMyHrRole = () => get(`${prefix.value}/access/me`) as Promise<Result<{ role: HrRole }>>

const getAuditLogs = (params: {
  current_page: number
  page_size: number
  user_id?: string
  action?: HrAuditAction
  object_type?: HrAuditObjectType
  start_time?: string
  end_time?: string
}) => get(`${prefix.value}/audit-logs`, params) as Promise<Result<HrAuditLogPage>>

export default {
  acceptOffer,
  acceptProposal,
  approveOffer,
  archiveCandidate,
  checkDuplicate,
  closeJob,
  closeJobV2,
  createApplication,
  createInterviewByApplication,
  createOfferByApplication,
  getApplicationEvents,
  getApplicationProposals,
  getAgentStats,
  getApplications,
  getCommunicationDrafts,
  getInterviewsByApplication,
  getInterviewProposals,
  getJobClosePreview,
  getJobProposals,
  getJobSourcingProposals,
  getJobStages,
  getOffersByApplication,
  dismissProposal,
  moveApplicationStage,
  restoreApplication,
  runCommunicationDraft,
  runInterviewCopilot,
  runJdDraftAgent,
  runScreeningAgent,
  runSourcingAgent,
  terminalApplication,
  createAssignment,
  createCandidate,
  createInterview,
  createJob,
  createOffer,
  deleteCandidate,
  deleteOfferAttachment,
  deleteResume,
  downloadOfferAttachment,
  downloadResume,
  exportCandidates,
  extractSkills,
  importCandidates,
  downloadImportTemplate,
  getAccess,
  getAiConfig,
  getAuditLogs,
  getCandidate,
  getCandidateResumes,
  getCandidates,
  getHandoffConfig,
  getHandoffs,
  getInterviews,
  getJob,
  getJobMatches,
  getJobs,
  getMyHrRole,
  getMyInterviews,
  getOffer,
  getAllOffers,
  getOffers,
  getResumeBatchStatus,
  getResumeContent,
  getResumeFlowLogs,
  mergeCandidates,
  searchResumes,
  parseSearch,
  putAiConfig,
  putHandoffConfig,
  rejectOffer,
  reopenJob,
  restoreCandidate,
  retryHandoff,
  sendOffer,
  submitInterviewFeedback,
  updateAccess,
  updateAssignment,
  updateCandidate,
  updateInterview,
  updateJob,
  updateOffer,
  uploadOfferAttachment,
  uploadResumes,
  withdrawOffer,
}
