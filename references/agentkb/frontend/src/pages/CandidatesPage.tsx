import { useEffect, useState } from "react";
import { Button, Card, Col, Input, Row, Select, Table, Typography, message } from "antd";
import { Link } from "react-router-dom";
import { listCandidates } from "../api/candidates";
import { assignCandidate } from "../api/assignments";
import { listJobs } from "../api/jobs";
import * as wsApi from "../api/workspaces";

export default function CandidatesPage() {
  const [workspaces, setWorkspaces] = useState<{ id: number; name: string }[]>([]);
  const [wsId, setWsId] = useState<number | null>(null);
  const [jobs, setJobs] = useState<{ job_id: number; name: string }[]>([]);
  const [jobId, setJobId] = useState<number | null>(null);
  const [items, setItems] = useState<Record<string, unknown>[]>([]);
  const [total, setTotal] = useState(0);
  const [loading, setLoading] = useState(false);
  const [filters, setFilters] = useState<Record<string, string>>({});

  const loadJobs = async (curWs: number) => {
    try {
      const data = await listJobs(curWs, { status: "open", page: 1, page_size: 50 });
      setJobs(data.items);
      if (data.items.length > 0) setJobId((prev) => prev ?? data.items[0].job_id);
    } catch {
      setJobs([]);
    }
  };

  const doAssign = async (candidateId: number) => {
    if (wsId == null || jobId == null) return;
    try {
      await assignCandidate(wsId, jobId, { candidate_id: candidateId, idempotency_key: `assign-${Date.now()}` });
      message.success("已加入待面试");
    } catch {
      message.error("加入待面试失败");
    }
  };

  const load = async (curWs: number, f: Record<string, string> = filters) => {
    setLoading(true);
    try {
      const data = await listCandidates(curWs, {
        status: f.status || undefined,
        skills: f.skills || undefined,
        city: f.city || undefined,
        degree_at_least: f.degree || undefined,
        years_min: f.years ? Number(f.years) : undefined,
        referrer: f.referrer || undefined,
        interview_result: f.interview_result || undefined,
        page: 1,
        page_size: 50,
      });
      setItems(data.items);
      setTotal(data.total);
    } catch {
      message.error("加载候选人失败");
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    wsApi.list().then((rows) => {
      setWorkspaces(rows);
      if (rows.length > 0) {
        setWsId(rows[0].id);
        load(rows[0].id, {});
        loadJobs(rows[0].id);
      }
    });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const columns = [
    { title: "姓名", dataIndex: "name", key: "name", render: (_: unknown, r: Record<string, unknown>) => (
      <Link to={`/candidates/${r.candidate_id}?ws=${wsId}`}>{String(r.name ?? "无姓名")}</Link>
    )},
    { title: "状态", dataIndex: "status", key: "status", width: 120 },
    { title: "城市", dataIndex: "city", key: "city", width: 120, render: (v: unknown) => v ? String(v) : "—" },
    { title: "学历", dataIndex: "highest_degree", key: "highest_degree", width: 100, render: (v: unknown) => v ? String(v) : "—" },
    { title: "年限", dataIndex: "years_experience", key: "years_experience", width: 80, render: (v: unknown) => v != null ? `${v} 年` : "—" },
    { title: "创建时间", dataIndex: "created_at", key: "created_at", width: 180, render: (v: unknown) => String(v ?? "").slice(0, 16) },
    { title: "操作", key: "actions", width: 140, render: (_: unknown, r: Record<string, unknown>) => (
      <Button size="small" type="link" data-testid="assign" onClick={() => doAssign(Number(r.candidate_id))}>加入待面试</Button>
    )},
  ];

  return (
    <div>
      <Typography.Title level={3}>候选人管理</Typography.Title>
      <Card style={{ marginBottom: 16 }}>
        <Row gutter={8}>
          <Col span={4}>
            <Select data-testid="workspace" style={{ width: "100%" }} value={wsId ?? undefined}
              onChange={(v) => { setWsId(v); load(v, {}); loadJobs(v); }}>
              {workspaces.map((w) => <Select.Option key={w.id} value={w.id}>{w.name}</Select.Option>)}
            </Select>
          </Col>
          <Col span={4}>
            <Select data-testid="status" style={{ width: "100%" }} value={filters.status ?? ""} placeholder="全部状态"
              onChange={(v) => { const f = { ...filters, status: v }; setFilters(f); if (wsId != null) load(wsId, f); }}>
              <Select.Option value="">全部状态</Select.Option>
              <Select.Option value="active">在职库</Select.Option>
              <Select.Option value="pending_review">待确认</Select.Option>
              <Select.Option value="rejected">已面试未通过</Select.Option>
              <Select.Option value="hired">入职员工</Select.Option>
              <Select.Option value="deleted">已删除</Select.Option>
            </Select>
          </Col>
          <Col span={4}>
            <Select data-testid="interview-status" style={{ width: "100%" }} value={filters.interview_result ?? ""} placeholder="面试状态"
              onChange={(v) => { const f = { ...filters, interview_result: v }; setFilters(f); if (wsId != null) load(wsId, f); }}>
              <Select.Option value="">全部面试状态</Select.Option>
              <Select.Option value="passed">面试通过</Select.Option>
              <Select.Option value="failed">面试不通过</Select.Option>
              <Select.Option value="no_show">未履行面试</Select.Option>
            </Select>
          </Col>
          <Col span={3}>
            <Input data-testid="skills" placeholder="技能" value={filters.skills ?? ""}
              onChange={(e) => { const f = { ...filters, skills: e.target.value }; setFilters(f); if (wsId != null) load(wsId, f); }} />
          </Col>
          <Col span={3}>
            <Input data-testid="city" placeholder="城市" value={filters.city ?? ""}
              onChange={(e) => { const f = { ...filters, city: e.target.value }; setFilters(f); if (wsId != null) load(wsId, f); }} />
          </Col>
          <Col span={3}>
            <Input data-testid="degree" placeholder="学历" value={filters.degree ?? ""}
              onChange={(e) => { const f = { ...filters, degree: e.target.value }; setFilters(f); if (wsId != null) load(wsId, f); }} />
          </Col>
          <Col span={3}>
            <Input data-testid="years" placeholder="年限≥" value={filters.years ?? ""}
              onChange={(e) => { const f = { ...filters, years: e.target.value }; setFilters(f); if (wsId != null) load(wsId, f); }} />
          </Col>
          <Col span={4}>
            <Select data-testid="assign-job" style={{ width: "100%" }} value={jobId ?? undefined} placeholder="指派到职位"
              onChange={(v) => setJobId(v)}>
              {jobs.map((j) => <Select.Option key={j.job_id} value={j.job_id}>{j.name}</Select.Option>)}
            </Select>
          </Col>
        </Row>
      </Card>
      <Table
        rowKey={(r) => String(r.candidate_id)}
        columns={columns}
        dataSource={items}
        loading={loading}
        pagination={{ total, pageSize: 50, showTotal: (t) => `共 ${t} 人` }}
      />
    </div>
  );
}
