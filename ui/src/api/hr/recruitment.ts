import type { Result } from '@/request/Result'
import { del, get, post, put } from '@/request'
import type {
  Assignment,
  Candidate,
  CandidateDetail,
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

export default {
  archiveCandidate,
  createAssignment,
  createCandidate,
  createJob,
  deleteResume,
  getCandidate,
  getCandidateResumes,
  getCandidates,
  getJob,
  getJobMatches,
  getJobs,
  updateAssignment,
  updateCandidate,
  updateJob,
  uploadResumes,
}
