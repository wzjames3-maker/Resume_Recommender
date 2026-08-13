from django.urls import path

from hr import views

app_name = "hr"

urlpatterns = [
    path("workspace/<str:workspace_id>/hr/candidates", views.CandidateAPI.as_view()),
    path("workspace/<str:workspace_id>/hr/candidates/resumes", views.ResumeAPI.as_view()),
    path("workspace/<str:workspace_id>/hr/candidates/<int:current_page>/<int:page_size>", views.CandidateAPI.Page.as_view()),
    path("workspace/<str:workspace_id>/hr/candidates/<str:candidate_id>", views.CandidateDetailAPI.as_view()),
    path("workspace/<str:workspace_id>/hr/candidates/<str:candidate_id>/archive", views.CandidateDetailAPI.Archive.as_view()),
    path("workspace/<str:workspace_id>/hr/candidates/<str:candidate_id>/resumes", views.ResumeListAPI.as_view()),
    path("workspace/<str:workspace_id>/hr/jobs", views.JobAPI.as_view()),
    path("workspace/<str:workspace_id>/hr/jobs/<int:current_page>/<int:page_size>", views.JobAPI.Page.as_view()),
    path("workspace/<str:workspace_id>/hr/jobs/<str:job_id>", views.JobDetailAPI.as_view()),
    path("workspace/<str:workspace_id>/hr/jobs/<str:job_id>/assignments", views.JobAPI.Assignment.as_view()),
    path("workspace/<str:workspace_id>/hr/assignments/<str:assignment_id>", views.AssignmentAPI.as_view()),
    path("workspace/<str:workspace_id>/hr/resumes/<str:resume_id>", views.ResumeDetailAPI.as_view()),
]
