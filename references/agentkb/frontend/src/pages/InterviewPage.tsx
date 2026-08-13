import { useEffect, useState } from "react";
import { Alert, Button, Card, Drawer, Input, Select, Space, Table, Tabs, Tag, Typography, message } from "antd";
import { listOverdue, listRounds, submitFeedback, summarizeRound, updateInterviewResult } from "../api/interviews";
import { hireAssignment, transitionAssignment } from "../api/assignments";
import { listJobs } from "../api/jobs";
import { jobBoard } from "../api/assignments";
import * as wsApi from "../api/workspaces";

interface BoardRow {
  assignment_id: number;
  candidate_id: number;
  name: string;
  status: string;
  reject_reason?: string;
  interview_result?: string | null;
  has_pending_interview?: boolean;
  has_completed_interview?: boolean;
  updated_at?: string;
  job_id?: number;
  job_name?: string;
}

const STATUS_LABEL: Record<string, string> = {
  pending_screen: "待面试",
  screen_passed: "初筛通过",
  interviewing: "面试中",
  offer: "已发 offer",
  hired: "已入职",
  rejected: "已淘汰",
  offer_rejected: "offer 已拒绝",
  closed_after_hire: "入职后关闭",
  closed_by_job: "职位关闭",
};

const RESULT_LABEL: Record<string, string> = {
  passed: "面试通过",
  failed: "面试不通过",
  no_show: "未履行面试",
  cancelled: "取消面试",
};

export default function InterviewPage() {
  const [workspaces, setWorkspaces] = useState<{ id: number; name: string }[]>([]);
  const [wsId, setWsId] = useState<number | null>(null);
  const [rows, setRows] = useState<BoardRow[]>([]);
  const [overdue, setOverdue] = useState<Record<string, unknown>[]>([]);
  const [loading, setLoading] = useState(false);
  const [activeTab, setActiveTab] = useState("pending");
  const [rounds, setRounds] = useState<Record<string, unknown>[]>([]);
  const [roundsOpen, setRoundsOpen] = useState(false);
  const [currentAssignment, setCurrentAssignment] = useState<BoardRow | null>(null);
  const [feedbackOpen, setFeedbackOpen] = useState(false);
  const [currentRound, setCurrentRound] = useState<Record<string, unknown> | null>(null);
  const [score, setScore] = useState("3");
  const [conclusion, setConclusion] = useState("hold");
  const [comment, setComment] = useState("");
  const [summaries, setSummaries] = useState<Record<string, string>>({});

  const loadOverdue = async (curWs: number) => {
    try {
      const data = await listOverdue(curWs);
      setOverdue(data.items ?? []);
    } catch {
      setOverdue([]);
    }
  };

  const loadBoard = async (curWs: number) => {
    setLoading(true);
    try {
      const jobs = await listJobs(curWs, { page: 1, page_size: 100 });
      const all: BoardRow[] = [];
      for (const j of (jobs.items ?? [])) {
        try {
          const board = await jobBoard(curWs, Number(j.job_id));
          const groups = (board.groups ?? {}) as Record<string, unknown[]>;
          for (const items of Object.values(groups)) {
            for (const it of items as Record<string, unknown>[]) {
              all.push({ ...(it as unknown as BoardRow), job_id: Number(j.job_id), job_name: String(j.name) });
            }
          }
        } catch {
          // 单个职位 board 失败不阻塞
        }
      }
      setRows(all);
    } catch {
      message.error("加载面试看板失败");
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    wsApi.list().then((r) => {
      setWorkspaces(r);
      if (r.length > 0) {
        setWsId(r[0].id);
        loadOverdue(r[0].id);
        loadBoard(r[0].id);
      }
    });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const loadRounds = async (row: BoardRow) => {
    if (wsId == null) return;
    try {
      const data = await listRounds(wsId, row.assignment_id);
      setRounds(data.items ?? []);
      setCurrentAssignment(row);
      setRoundsOpen(true);
    } catch {
      message.error("加载面试轮次失败");
    }
  };

  const doFeedback = async () => {
    if (wsId == null || currentRound == null) return;
    try {
      await submitFeedback(wsId, Number(currentRound.round_id), {
        score: Number(score),
        conclusion,
        comment,
        reject_reason: conclusion === "reject" ? comment : undefined,
      });
      message.success("反馈已提交；recommend 后可发 offer，advance 需安排下一轮");
      setFeedbackOpen(false);
      setComment("");
      if (currentAssignment) await loadRounds(currentAssignment);
      await loadOverdue(wsId);
      await loadBoard(wsId);
    } catch {
      message.error("提交反馈失败");
    }
  };

  const setResult = async (row: BoardRow, result: string) => {
    if (wsId == null) return;
    try {
      await updateInterviewResult(wsId, row.assignment_id, { result, reason: result === "failed" ? "面试不通过" : undefined });
      message.success(`已记录${RESULT_LABEL[result] ?? "面试结果"}`);
      await loadBoard(wsId);
    } catch {
      message.error("更新面试结果失败");
    }
  };

  const transition = async (row: BoardRow, toState: string) => {
    if (wsId == null) return;
    try {
      if (toState === "hired") await hireAssignment(wsId, row.assignment_id);
      else await transitionAssignment(wsId, row.assignment_id, { to_state: toState });
      message.success(toState === "offer" ? "Offer 已发出" : toState === "hired" ? "已标记入职" : "Offer 已拒绝");
      await loadBoard(wsId);
    } catch {
      message.error("更新招聘状态失败，请确认前置条件和 HC");
    }
  };

  const doSummarize = async (round: Record<string, unknown>) => {
    if (wsId == null) return;
    try {
      const res = await summarizeRound(wsId, Number(round.round_id));
      setSummaries((prev) => ({ ...prev, [String(round.round_id)]: res.ai_summary ?? "" }));
    } catch {
      message.error("AI 总结失败（工作区未配置 LLM 或评语为空）");
    }
  };

  const renderTable = (rowsForTab: BoardRow[]) => (
    <Table
      rowKey={(r) => String(r.assignment_id)}
      loading={loading}
      pagination={false}
      dataSource={rowsForTab}
      locale={{ emptyText: "暂无数据" }}
      columns={[
        { title: "候选人", dataIndex: "name", key: "name", render: (v: unknown) => String(v ?? "—") },
        { title: "职位", dataIndex: "job_name", key: "job_name", render: (v: unknown) => String(v ?? "—") },
        { title: "面试结果", dataIndex: "interview_result", key: "interview_result", width: 110, render: (v: string | null) => v ? <Tag color={v === "passed" ? "green" : "red"}>{RESULT_LABEL[v] ?? v}</Tag> : "—" },
        { title: "招聘状态", dataIndex: "status", key: "status", width: 110, render: (v: string) => <Tag color={v === "interviewing" ? "blue" : v === "offer" || v === "hired" ? "green" : v === "rejected" || v === "offer_rejected" ? "red" : "default"}>{STATUS_LABEL[v] ?? v}</Tag> },
        { title: "拒绝原因", dataIndex: "reject_reason", key: "reject_reason", ellipsis: true, render: (v: unknown) => v ? String(v) : "—" },
        { title: "更新时间", dataIndex: "updated_at", key: "updated_at", width: 170, render: (v: unknown) => String(v ?? "").slice(0, 16) },
        { title: "操作", key: "actions", width: 310, render: (_: unknown, r: BoardRow) => (
          <Space wrap>
            <Button size="small" data-testid="rounds" onClick={() => loadRounds(r)}>面试轮次</Button>
            {activeTab === "pending" && <>
              <Button size="small" type="primary" onClick={() => setResult(r, "passed")}>面试通过</Button>
              <Button size="small" danger onClick={() => setResult(r, "failed")}>面试不通过</Button>
              <Button size="small" onClick={() => setResult(r, "no_show")}>未履行</Button>
              <Button size="small" onClick={() => setResult(r, "cancelled")}>取消面试</Button>
            </>}
            {activeTab === "passed" && r.status === "interviewing" && <Button size="small" type="primary" onClick={() => transition(r, "offer")}>发 Offer</Button>}
            {activeTab === "passed" && r.status === "offer" && <>
              <Button size="small" type="primary" onClick={() => transition(r, "hired")}>标记入职</Button>
              <Button size="small" danger onClick={() => transition(r, "offer_rejected")}>拒绝 Offer</Button>
            </>}
          </Space>
        )},
      ]}
    />
  );

  const groupRows = (key: string) => rows.filter((r) => {
    if (key === "pending") return ["pending_screen", "screen_passed"].includes(r.status) || Boolean(r.has_pending_interview);
    if (key === "interviewing") return r.status === "interviewing" && Boolean(r.has_completed_interview) && !r.has_pending_interview && !r.interview_result;
    if (key === "passed") return r.interview_result === "passed" || ["offer", "hired"].includes(r.status);
    return ["failed", "no_show", "cancelled"].includes(r.interview_result ?? "") || r.status === "rejected" || r.status === "offer_rejected";
  }).sort((a, b) => String(b.updated_at ?? "").localeCompare(String(a.updated_at ?? "")));

  const tabItems = [
    { key: "pending", label: `待面试 (${groupRows("pending").length})`, children: renderTable(groupRows("pending")) },
    { key: "interviewing", label: `已面试 (${groupRows("interviewing").length})`, children: renderTable(groupRows("interviewing")) },
    { key: "passed", label: `面试通过 (${groupRows("passed").length})`, children: renderTable(groupRows("passed")) },
    { key: "rejected", label: `面试不通过 (${groupRows("rejected").length})`, children: renderTable(groupRows("rejected")) },
  ];

  return (
    <div>
      <Typography.Title level={3}>面试管理</Typography.Title>
      <Card style={{ marginBottom: 16 }}>
        <Space wrap>
          <Select data-testid="workspace" style={{ width: 180 }} value={wsId ?? undefined}
            onChange={(v) => { setWsId(v); loadOverdue(v); loadBoard(v); }}>
            {workspaces.map((w) => <Select.Option key={w.id} value={w.id}>{w.name}</Select.Option>)}
          </Select>
        </Space>
        {overdue.length > 0 && (
          <Alert
            style={{ marginTop: 12 }}
            type="warning"
            showIcon
            message={`您有 ${overdue.length} 个面试超 48 小时未反馈`}
            description={
              <Space wrap>
                {overdue.map((o) => (
                  <Tag key={String(o.round_id)} color="orange" data-testid="overdue">
                    指派 #{String(o.assignment_id)} · 第 {String(o.round_no)} 轮 · {String(o.scheduled_at ?? "").slice(0, 16)}
                  </Tag>
                ))}
              </Space>
            }
          />
        )}
      </Card>
      <Tabs activeKey={activeTab} onChange={setActiveTab} items={tabItems} />

      <Drawer title={currentAssignment ? `面试轮次 · ${currentAssignment.name}` : "面试轮次"} open={roundsOpen}
        onClose={() => setRoundsOpen(false)} width={760}>
        <Table
          rowKey={(r) => String(r.round_id)}
          pagination={false}
          dataSource={rounds}
          locale={{ emptyText: "该指派暂无面试轮次" }}
          columns={[
            { title: "轮次", dataIndex: "round_no", key: "round_no", width: 70, render: (v: unknown) => `第 ${v} 轮` },
            { title: "面试官", dataIndex: "interviewer_id", key: "interviewer_id", width: 80, render: (v: unknown) => `#${v}` },
            { title: "时间", dataIndex: "scheduled_at", key: "scheduled_at", width: 160, render: (v: unknown) => String(v ?? "—").slice(0, 16) },
            { title: "评分", dataIndex: "score", key: "score", width: 60, render: (v: unknown) => v != null ? `${v}/5` : "—" },
            { title: "结论", dataIndex: "conclusion", key: "conclusion", width: 90, render: (v: unknown) => v ? <Tag color={String(v) === "recommend" ? "green" : String(v) === "reject" ? "red" : "blue"}>{String(v)}</Tag> : "—" },
            { title: "评语", dataIndex: "comment", key: "comment", ellipsis: true, render: (v: unknown) => v ? String(v) : "—" },
            { title: "操作", key: "actions", width: 200, render: (_: unknown, r: Record<string, unknown>) => (
              <Space>
                {r.feedback_at == null && (
                  <Button size="small" type="primary" data-testid="feedback" onClick={() => { setCurrentRound(r); setFeedbackOpen(true); }}>
                    提交反馈
                  </Button>
                )}
                <Button size="small" data-testid="summarize" onClick={() => doSummarize(r)}>AI 总结</Button>
              </Space>
            )},
          ]}
        />
        {Object.keys(summaries).length > 0 && (
          <div style={{ marginTop: 16 }}>
            {Object.entries(summaries).map(([rid, s]) => (
              <Card key={rid} size="small" title={`轮次 #${rid} AI 总结`} style={{ marginBottom: 8 }}>
                <pre data-testid="ai-summary" style={{ whiteSpace: "pre-wrap", margin: 0 }}>{s || "暂无总结"}</pre>
              </Card>
            ))}
          </div>
        )}
      </Drawer>
      <Drawer title={currentRound ? `第 ${String(currentRound.round_no)} 轮反馈` : "提交反馈"} open={feedbackOpen}
        onClose={() => setFeedbackOpen(false)} width={420}>
        <Space direction="vertical" style={{ width: "100%" }}>
          <Space>
            <span>评分：</span>
            <Select data-testid="score" style={{ width: 80 }} value={score} onChange={(v) => setScore(v)}>
              {["1", "2", "3", "4", "5"].map((s) => <Select.Option key={s} value={s}>{s}</Select.Option>)}
            </Select>
          </Space>
          <Space>
            <span>结论：</span>
            <Select data-testid="conclusion" style={{ width: 160 }} value={conclusion} onChange={(v) => setConclusion(v)}>
              <Select.Option value="advance">advance（进下一轮）</Select.Option>
              <Select.Option value="reject">reject（淘汰）</Select.Option>
              <Select.Option value="hold">hold（待定）</Select.Option>
              <Select.Option value="recommend">recommend（推荐 offer）</Select.Option>
            </Select>
          </Space>
          <Input.TextArea data-testid="comment" rows={4} placeholder="面试评语（可留空后 AI 总结）" value={comment}
            onChange={(e) => setComment(e.target.value)} />
          <Button type="primary" data-testid="submit" onClick={doFeedback}>提交反馈</Button>
        </Space>
      </Drawer>
    </div>
  );
}
