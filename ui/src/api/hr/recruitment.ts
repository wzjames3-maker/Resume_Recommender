import type { Result } from '@/request/Result'
import { del, get, post, put } from '@/request'
import type {
  AiConditions,
  Assignment,
  Candidate,
  CandidateDetail,
  HrConfig,
  Interview,
  Job,
  JobDetail,
  JobMatchPage,
  PageResult,
  ResumeFile,
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

const getJobs = (page: pageRequest, params?: Record<string, unknown>) =>
  get(`${prefix.value}/jobs/${page.current_page}/${page.page_size}`, params) as Promise<Result<PageResult<Job>>>

const createJob = (data: Partial<Job>) => post(`${prefix.value}/jobs`, data) as Promise<Result<Job>>

const getJob = (jobId: string) => get(`${prefix.value}/jobs/${jobId}`) as Promise<Result<JobDetail>>

const updateJob = (jobId: string, data: Partial<Job>) =>
  put(`${prefix.value}/jobs/${jobId}`, data) as Promise<Result<Job>>

const createAssignment = (jobId: string, candidateId: string, note = '') =>
  post(`${prefix.value}/jobs/${jobId}/assignments`, { candidate_id: candidateId, note }) as Promise<Result<Assignment>>

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

const getAiConfig = () => get(`${prefix.value}/ai/config`) as Promise<Result<HrConfig>>

const putAiConfig = (data: Record<string, unknown>) =>
  put(`${prefix.value}/ai/config`, data) as Promise<Result<HrConfig>>

const parseSearch = (query: string) =>
  post(`${prefix.value}/ai/search-parse`, { query }) as Promise<Result<{ conditions: AiConditions }>>

const extractSkills = (description: string) =>
  post(`${prefix.value}/ai/extract-skills`, { description }) as Promise<Result<{ skills: string[] }>>

export default {
  archiveCandidate,
  createAssignment,
  createCandidate,
  createInterview,
  createJob,
  deleteResume,
  extractSkills,
  getAiConfig,
  getCandidate,
  getCandidateResumes,
  getCandidates,
  getInterviews,
  getJob,
  getJobMatches,
  getJobs,
  parseSearch,
  putAiConfig,
  updateAssignment,
  updateCandidate,
  updateInterview,
  updateJob,
  uploadResumes,
}
