import { useEffect, useState } from "react";
import { Link, useParams, useSearchParams } from "react-router-dom";
import { Button, Descriptions, Input, Select, Space, Table, Tabs, Tag, Typography, message } from "antd";
import { getJob, jobMatches, listJobRevisions, overrideJobRequirement, updateJob } from "../api/jobs";
import { assignCandidate, hireAssignment, jobBoard, transitionAssignment } from "../api/assignments";
import { scheduleRound, submitFeedback, summarizeRound } from "../api/interviews";
import * as wsApi from "../api/workspaces";

export default function JobDetailPage() {
  const { id } = useParams();
  const [searchParams] = useSearchParams();
  const [wsId, setWsId] = useState<number | null>(searchParams.get("ws") ? Number(searchParams.get("ws")) : null);
  const [job, setJob] = useState<Record<string, unknown> | null>(null);
  const [requirement, setRequirement] = useState<Record<string, unknown> | null>(null);
  const [revisions, setRevisions] = useState<Record<string, unknown>[]>([]);
  const [matches, setMatches] = useState<Record<string, unknown>[]>([]);
  const [board, setBoard] = useState<Record<string, unknown>>({});
  const [assignId, setAssignId] = useState("");
  const [fieldPath, setFieldPath] = useState("skills");
  const [overrideAction, setOverrideAction] = useState("override");
  const [afterValue, setAfterValue] = useState("");
  const [error, setError] = useState("");

  const load = async (curWs: number) => {
    if (!id) return;
    try {
      const data = await getJob(curWs, Number(id));
      setJob(data.job);
      setRequirement(data.requirement);
      const revs = await listJobRevisions(curWs, Number(id));
      setRevisions(revs.items);
      const ms = await jobMatches(curWs, Number(id), 20);
      setMatches(ms.items);
      const bd = await jobBoard(curWs, Number(id));
      setBoard(bd.groups ?? {});
      setError("");
    } catch {
      setError("职位不存在或无权访问");
    }
  };

  useEffect(() => {
    if (wsId != null) { load(wsId); return; }
    wsApi.list().then((rows) => {
      if (rows.length > 0) { setWsId(rows[0].id); load(rows[0].id); }
    });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [id, wsId]);

  const doAssign = async () => {
    if (wsId == null || !assignId || Number(assignId) <= 0) return;
    try {
      await assignCandidate(wsId, Number(id), { candidate_id: Number(assignId), idempotency_key: `assign-${Date.now()}` });
      setAssignId("");
      await load(wsId);
    } catch {
      message.error("指派失败（职位已关闭/HC 已满/候选人在流程中）");
    }
  };

  const doTransition = async (assignmentId: number, toState: string, reason?: string) => {
    if (wsId == null) return;
    try {
      await transitionAssignment(wsId, assignmentId, { to_state: toState, reject_reason: reason });
      await load(wsId);
    } catch {
      message.error("流转失败");
    }
  };

  const doHire = async (assignmentId: number) => {
    if (wsId == null) return;
    try {
      await hireAssignment(wsId, assignmentId);
      await load(wsId);
    } catch {
      message.error("入职失败");
    }
  };

  const doSummarize = async () => {
    if (wsId == null) return;
    const roundId = window.prompt("面试轮 ID（提交反馈后生成）");
    if (!roundId) return;
    try {
      const res = await summarizeRound(wsId, Number(roundId));
      message.success(`AI 总结：${(res.ai_summary?.advantages ?? []).join("、")}`);
    } catch {
      message.error("AI 总结失败（工作区未配置 LLM 或评语为空）");
    }
  };

  const doSchedule = async (assignmentId: number) => {
    if (wsId == null) return;
    const interviewerId = window.prompt("面试官用户 ID");
    if (!interviewerId) return;
    try {
      await scheduleRound(wsId, assignmentId, {
        interviewer_id: Number(interviewerId),
        scheduled_at: new Date().toISOString(),
      });
      await load(wsId);
    } catch {
      message.error("安排面试失败（仅初筛通过/面试中可安排）");
    }
  };

  const doFeedback = async () => {
    if (wsId == null) return;
    const input = window.prompt('提交反馈（评分/结论/评语），如 5,recommend,技术扎实');
    if (!input) return;
    try {
      const [score, conclusion, ...rest] = input.split(",");
      const roundId = Number(window.prompt("面试轮 ID"));
      if (!roundId) return;
      await submitFeedback(wsId, roundId, { score: Number(score), conclusion, comment: rest.join(",") });
      message.success("反馈已提交；recommend 后可发 offer，advance 需安排下一轮");
      await load(wsId);
    } catch {
      message.error("提交反馈失败");
    }
  };

  const doClose = async () => {
    if (wsId == null || !job) return;
    try {
      const target = job.status === "open" ? "closed" : "open";
      const res = await updateJob(wsId, Number(id), { base_revision_id: job.latest_revision_id, status: target });
      setJob(res.job);
    } catch {
      message.error("操作失败（仅管理员可编辑/关闭职位）");
    }
  };

  if (!job) return <div data-testid="error">{error || "加载中…"}</div>;

  const conditions = (requirement?.conditions ?? []) as Record<string, unknown>[];
  const evidence = (requirement?.evidence ?? {}) as Record<string, unknown>;

  const boardRows: Record<string, unknown>[] = Object.entries(board).flatMap(([state, rows]) =>
    (rows as Record<string, unknown>[]).map((r) => ({ ...r, group: state }))
  );

  const boardColumns = [
    { title: "候选人", dataIndex: "name", key: "name" },
    { title: "状态", dataIndex: "group", key: "group", width: 120, render: (v: string) => <Tag>{v}</Tag> },
    { title: "拒绝原因", dataIndex: "reject_reason", key: "reject_reason", render: (v: unknown) => v ? String(v) : "—" },
    { title: "更新时间", dataIndex: "updated_at", key: "updated_at", width: 180, render: (v: unknown) => String(v ?? "").slice(0, 16) },
    { title: "操作", key: "actions", width: 380, render: (_: unknown, r: Record<string, unknown>) => (
      <Space wrap>
        {r.group === "pending_screen" && (
          <Button size="small" onClick={() => doTransition(Number(r.assignment_id), "screen_passed")}>初筛通过</Button>
        )}
        {r.group === "screen_passed" && (
          <>
            <Button size="small" onClick={() => doTransition(Number(r.assignment_id), "interviewing")}>安排面试</Button>
            <Button size="small" onClick={() => doSchedule(Number(r.assignment_id))}>创建面试轮</Button>
          </>
        )}
        {r.group === "interviewing" && (
          <>
            <Button size="small" onClick={doFeedback}>提交反馈</Button>
            <Button size="small" onClick={doSummarize}>AI 总结</Button>
            <Button size="small" onClick={() => doTransition(Number(r.assignment_id), "offer")}>发 offer</Button>
          </>
        )}
        {r.group === "offer" && (
          <Button size="small" type="primary" onClick={() => doHire(Number(r.assignment_id))}>入职</Button>
        )}
        {!["hired", "offer_rejected", "rejected", "closed_after_hire", "closed_by_job"].includes(String(r.group)) && (
          <Button size="small" danger onClick={() => {
            const reason = window.prompt("淘汰原因");
            if (reason) doTransition(Number(r.assignment_id), "rejected", reason);
          }}>淘汰</Button>
        )}
      </Space>
    )},
  ];

  const matchColumns = [
    { title: "姓名", dataIndex: "name", key: "name", width: 120, render: (v: unknown) => String(v ?? "—") },
    { title: "城市", dataIndex: "city", key: "city", width: 100, render: (v: unknown) => String(v ?? "—") },
    { title: "命中条件", dataIndex: "matched_conditions", key: "matched_conditions", render: (v: unknown) => (
      <Space wrap>{Array.isArray(v) ? v.map((m) => <Tag key={String(m)} color="blue">{String(m)}</Tag>) : "—"}</Space>
    )},
  ];

  const doOverride = async () => {
    if (wsId == null || !job) return;
    try {
      const body: Record<string, unknown> = {
        base_revision_id: job.latest_revision_id,
        field_path: fieldPath,
        action: overrideAction,
      };
      if (overrideAction === "override") {
        body.after_value = JSON.parse(afterValue);
      }
      const res = await overrideJobRequirement(wsId, Number(id), body);
      setRequirement((prev) => ({ ...prev, conditions: res.conditions }));
      message.success("职位要求已修正");
    } catch (err: any) {
      message.error(err?.response?.data?.message ?? "修正失败（请检查条件 JSON 或岗位要求已被修改）");
    }
  };

  return (
    <div>
      <Typography.Title level={3} data-testid="name">职位：{String(job.name)}</Typography.Title>
      <Link to={`/jobs?ws=${wsId}`}>返回列表</Link>
      {error && <Typography.Text type="danger" data-testid="error" style={{ display: "block", marginTop: 8 }}>{error}</Typography.Text>}
      <Descriptions style={{ marginTop: 16, marginBottom: 16 }} column={3} bordered size="small">
        <Descriptions.Item label="状态"><Tag data-testid="status" color={job.status === "open" ? "green" : "default"}>{String(job.status)}</Tag></Descriptions.Item>
        <Descriptions.Item label="城市">{String(job.city ?? "—")}</Descriptions.Item>
        <Descriptions.Item label="招聘人数">{String(job.headcount)} 人</Descriptions.Item>
        <Descriptions.Item label="薪资">{String(job.salary_range ?? "—")}</Descriptions.Item>
        <Descriptions.Item label="岗位要求" span={2}>{String(job.description)}</Descriptions.Item>
      </Descriptions>
      <Button data-testid="toggle-status" onClick={doClose} style={{ marginBottom: 16 }}>
        {job.status === "open" ? "关闭职位" : "重新开放"}
      </Button>
      <Tabs
        items={[
          {
            key: "board",
            label: "待面试看板",
            children: (
              <div>
                <Space style={{ marginBottom: 16 }}>
                  <Input data-testid="assign-id" placeholder="候选人 ID" value={assignId} onChange={(e) => setAssignId(e.target.value)} style={{ width: 160 }} />
                  <Button data-testid="assign" type="primary" onClick={doAssign}>加入待面试</Button>
                </Space>
                <Table rowKey={(r) => String(r.assignment_id)} columns={boardColumns} dataSource={boardRows} pagination={false} />
              </div>
            ),
          },
          {
            key: "matches",
            label: "匹配候选人",
            children: <Table rowKey={(r) => String(r.candidate_id)} columns={matchColumns} dataSource={matches} pagination={false} />,
          },
          {
            key: "conditions",
            label: "岗位要求条件（有效 AST）",
            children: (
              <div>
                {conditions.map((c, i) => {
                  const cFields = (c as Record<string, unknown>).fields as string[] | undefined;
                  const key = String((c as Record<string, unknown>).field ?? cFields?.[0] ?? "");
                  const ev = evidence[key] as Record<string, unknown> | undefined;
                  return (
                    <p key={i} data-testid="condition">
                      {JSON.stringify(c)} — 依据：{String(ev?.locator ?? "")}
                    </p>
                  );
                })}
                <h4>人工修正（admin）</h4>
                <Space wrap>
                  <Input data-testid="field-path" placeholder="字段（skills/city/years_experience 等）" value={fieldPath}
                    onChange={(e) => setFieldPath(e.target.value)} style={{ width: 220 }} />
                  <Select data-testid="override-action" style={{ width: 110 }} value={overrideAction}
                    onChange={(v) => setOverrideAction(v)}>
                    <Select.Option value="override">override</Select.Option>
                    <Select.Option value="clear">clear</Select.Option>
                  </Select>
                  {overrideAction === "override" && (
                    <Input data-testid="after-value" placeholder='条件 JSON，如 {"field":"skills","op":"contains","value":["Vue"]}'
                      value={afterValue} onChange={(e) => setAfterValue(e.target.value)} style={{ width: 360 }} />
                  )}
                  <Button type="primary" data-testid="apply" onClick={doOverride}>应用修正</Button>
                </Space>
              </div>
            ),
          },
          {
            key: "revisions",
            label: "版本历史",
            children: (
              <ul>
                {revisions.map((r, i) => (
                  <li key={i} data-testid="revision">v{String(r.revision)} · {String(r.description)} · {String(r.created_at ?? "")}</li>
                ))}
              </ul>
            ),
          },
        ]}
      />
    </div>
  );
}