import { useEffect, useState } from "react";
import { Button, Card, Drawer, Input, Modal, Select, Space, Table, Tag, Typography, Upload, message } from "antd";
import { UploadOutlined } from "@ant-design/icons";
import { listRuns, retryRun, uploadResumes, getRun, getRunIr, importResumes } from "../api/resumes";
import * as wsApi from "../api/workspaces";

const CHANNELS = ["referral", "job_site", "headhunter", "campus", "other"];
const STATUS_COLOR: Record<string, string> = {
  pending: "orange", processing: "blue", success: "green", succeeded: "green",
  failed: "red", dead_letter: "red",
};

export default function ResumesPage() {
  const [workspaces, setWorkspaces] = useState<{ id: number; name: string }[]>([]);
  const [wsId, setWsId] = useState<number | null>(null);
  const [channel, setChannel] = useState("referral");
  const [templateVersion, setTemplateVersion] = useState("");
  const [runs, setRuns] = useState<Record<string, unknown>[]>([]);
  const [total, setTotal] = useState(0);
  const [msg, setMsg] = useState("");
  const [drawerOpen, setDrawerOpen] = useState(false);
  const [runDetail, setRunDetail] = useState<Record<string, unknown> | null>(null);
  const [ir, setIr] = useState("");
  const [importOpen, setImportOpen] = useState(false);
  const [importJson, setImportJson] = useState("");
  const [importTemplate, setImportTemplate] = useState("");
  const [importChannel, setImportChannel] = useState("referral");

  const load = async (curWs: number) => {
    try {
      const data = await listRuns(curWs, { page: 1, page_size: 50 });
      setRuns(data.items);
      setTotal(data.total);
      setMsg("");
    } catch {
      setMsg("加载解析任务失败");
    }
  };

  useEffect(() => {
    wsApi.list().then((rows) => {
      setWorkspaces(rows);
      if (rows.length > 0) {
        setWsId(rows[0].id);
        load(rows[0].id);
      }
    });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const doUpload = async (file: File) => {
    if (wsId == null) return false;
    try {
      const res = await uploadResumes(wsId, [file], {
        uploadId: `fe-${Date.now()}`,
        sourceChannel: channel,
        templateVersion: templateVersion || undefined,
      });
      setMsg(`上传成功：${res.runs.length} 个任务（重复 ${res.duplicate ? "是" : "否"}）`);
      await load(wsId);
    } catch (err: any) {
      message.error(err?.message ?? "上传失败");
    }
    return false;
  };

  const doImport = async () => {
    if (wsId == null) return;
    try {
      const body = JSON.parse(importJson);
      const envelope = {
        schema_version: "resume-import/v1",
        upload_id: `fe-import-${Date.now()}`,
        template_version: importTemplate,
        source_channel: importChannel,
        referrer: null,
        ...body,
      };
      const res = await importResumes(wsId, envelope);
      setMsg(`导入成功：${res.runs.length} 个任务`);
      setImportOpen(false);
      setImportJson("");
      await load(wsId);
    } catch (err: any) {
      message.error(err?.response?.data?.message ?? err?.message ?? "导入失败（JSON 格式错误）");
    }
  };

  const doRetry = async (runId: string) => {
    if (wsId == null) return;
    try {
      await retryRun(runId);
      await load(wsId);
    } catch {
      message.error("重试失败");
    }
  };

  const doDetail = async (runId: string) => {
    try {
      const d = await getRun(runId);
      setRunDetail(d);
      setIr("");
      try {
        const data = await getRunIr(runId);
        setIr(data.content);
      } catch {
        setIr("");
      }
      setDrawerOpen(true);
    } catch {
      message.error("任务不存在或无权访问");
    }
  };

  const columns = [
    { title: "任务 ID", dataIndex: "run_id", key: "run_id", width: 90, render: (v: string) => String(v).slice(0, 8) },
    { title: "格式", dataIndex: "format", key: "format", width: 80 },
    { title: "状态", dataIndex: "status", key: "status", width: 110, render: (v: string) => <Tag color={STATUS_COLOR[v] ?? "default"}>{v}</Tag> },
    { title: "渠道", dataIndex: "source_channel", key: "source_channel", width: 110 },
    { title: "创建时间", dataIndex: "created_at", key: "created_at", width: 180, render: (v: unknown) => String(v ?? "").slice(0, 16) },
    { title: "操作", key: "actions", width: 180, render: (_: unknown, r: Record<string, unknown>) => (
      <Space>
        {["failed", "dead_letter"].includes(String(r.status)) && (
          <Button size="small" data-testid="retry" onClick={() => doRetry(String(r.run_id))}>重试</Button>
        )}
        <Button size="small" data-testid="detail" onClick={() => doDetail(String(r.run_id))}>详情</Button>
      </Space>
    )},
  ];

  return (
    <div>
      <Typography.Title level={3}>简历解析</Typography.Title>
      <Card style={{ marginBottom: 16 }}>
        <Space wrap>
          <Select data-testid="workspace" style={{ width: 180 }} value={wsId ?? undefined}
            onChange={(v) => { setWsId(v); load(v); }}>
            {workspaces.map((w) => <Select.Option key={w.id} value={w.id}>{w.name}</Select.Option>)}
          </Select>
          <Select data-testid="channel" style={{ width: 140 }} value={channel} onChange={(v) => setChannel(v)}>
            {CHANNELS.map((c) => <Select.Option key={c} value={c}>{c}</Select.Option>)}
          </Select>
          <Input data-testid="template" placeholder="模板版本（CSV 必填）" value={templateVersion}
            onChange={(e) => setTemplateVersion(e.target.value)} style={{ width: 200 }} />
          <Upload showUploadList={false} multiple beforeUpload={doUpload} accept=".doc,.docx,.txt,.csv,.json">
            <Button type="primary" icon={<UploadOutlined />} data-testid="upload">上传简历</Button>
          </Upload>
          <Button data-testid="open-import" onClick={() => setImportOpen(true)}>JSON 批量导入</Button>
        </Space>
        {msg && <Typography.Text type="secondary" data-testid="msg" style={{ display: "block", marginTop: 8 }}>{msg}</Typography.Text>}
      </Card>
      <Table
        rowKey={(r) => String(r.run_id)}
        columns={columns}
        dataSource={runs}
        pagination={{ total, pageSize: 50, showTotal: (t) => `共 ${t} 个解析任务` }}
      />
      <Drawer title={runDetail ? `任务 ${String(runDetail.run_id).slice(0, 8)}` : "任务详情"} open={drawerOpen} onClose={() => setDrawerOpen(false)} width={560}>
        {runDetail && (
          <div data-testid="run-detail">
            <Typography.Paragraph>状态：{String(runDetail.status)} · 失败类型：{String(runDetail.failure_class ?? "—")} · 重试：{String(runDetail.retry_count ?? 0)}</Typography.Paragraph>
            {runDetail.error_message != null && String(runDetail.error_message) !== "" && (
              <Typography.Paragraph type="danger" data-testid="run-error">错误：{String(runDetail.error_message)}</Typography.Paragraph>
            )}
            <Typography.Title level={5}>IR 内容</Typography.Title>
            <pre data-testid="ir" style={{ whiteSpace: "pre-wrap", background: "#fafafa", padding: 12, borderRadius: 6 }}>{ir || "无 IR"}</pre>
          </div>
        )}
      </Drawer>
      <Modal title="JSON 批量导入" open={importOpen} onCancel={() => setImportOpen(false)} onOk={doImport} okText="导入" cancelText="取消" width={640}>
        <Space direction="vertical" style={{ width: "100%" }}>
          <Space>
            <Select data-testid="import-channel" style={{ width: 140 }} value={importChannel} onChange={(v) => setImportChannel(v)}>
              {CHANNELS.map((c) => <Select.Option key={c} value={c}>{c}</Select.Option>)}
            </Select>
            <Input data-testid="import-template" placeholder="模板版本（必填）" value={importTemplate}
              onChange={(e) => setImportTemplate(e.target.value)} style={{ width: 200 }} />
          </Space>
          <Input.TextArea data-testid="import-json" rows={10}
            placeholder='records 数组，如 {"records":[{"name":"张三","city":"杭州","skills":["Java"],"years_experience":5}]}'
            value={importJson} onChange={(e) => setImportJson(e.target.value)} />
        </Space>
      </Modal>
    </div>
  );
}