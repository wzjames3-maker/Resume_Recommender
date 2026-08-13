import { useEffect, useState } from "react";
import { Button, Card, Col, Form, Input, Modal, Row, Select, Table, Tag, Typography, message } from "antd";
import { Link } from "react-router-dom";
import { createJob, listJobs } from "../api/jobs";
import * as wsApi from "../api/workspaces";

export default function JobsPage() {
  const [workspaces, setWorkspaces] = useState<{ id: number; name: string }[]>([]);
  const [wsId, setWsId] = useState<number | null>(null);
  const [items, setItems] = useState<Record<string, unknown>[]>([]);
  const [total, setTotal] = useState(0);
  const [status, setStatus] = useState("");
  const [loading, setLoading] = useState(false);
  const [open, setOpen] = useState(false);
  const [form] = Form.useForm();
  const [matchPrompt, setMatchPrompt] = useState("");

  const load = async (curWs: number) => {
    setLoading(true);
    try {
      const data = await listJobs(curWs, { status: status || undefined, page: 1, page_size: 50 });
      setItems(data.items);
      setTotal(data.total);
    } catch {
      message.error("加载职位失败");
    } finally {
      setLoading(false);
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

  const doCreate = async () => {
    const values = await form.validateFields();
    if (wsId == null) return;
    try {
      const res = await createJob(wsId, {
        name: values.name,
        description: values.description,
        headcount: Number(values.headcount) || 1,
        city: values.city || null,
        salary_range: values.salary || null,
      });
      setMatchPrompt(res.match_prompt ?? "");
      form.resetFields();
      setOpen(false);
      await load(wsId);
    } catch {
      message.error("创建职位失败（请确认岗位要求可被解析）");
    }
  };

  const columns = [
    { title: "职位名称", dataIndex: "name", key: "name", render: (_: unknown, r: Record<string, unknown>) => (
      <Link to={`/jobs/${r.job_id}?ws=${wsId}`}>{String(r.name)}</Link>
    )},
    { title: "状态", dataIndex: "status", key: "status", width: 100, render: (v: unknown) => <Tag color={v === "open" ? "green" : "default"}>{String(v)}</Tag> },
    { title: "城市", dataIndex: "city", key: "city", width: 120, render: (v: unknown) => v ? String(v) : "—" },
    { title: "招聘人数", dataIndex: "headcount", key: "headcount", width: 100 },
    { title: "薪资", dataIndex: "salary_range", key: "salary_range", width: 140, render: (v: unknown) => v ? String(v) : "—" },
    { title: "创建时间", dataIndex: "created_at", key: "created_at", width: 180, render: (v: unknown) => String(v ?? "").slice(0, 16) },
  ];

  return (
    <div>
      <Typography.Title level={3}>职位管理</Typography.Title>
      <Card style={{ marginBottom: 16 }}>
        <Row gutter={8}>
          <Col span={6}>
            <Select data-testid="workspace" style={{ width: "100%" }} value={wsId ?? undefined}
              onChange={(v) => { setWsId(v); load(v); }}>
              {workspaces.map((w) => <Select.Option key={w.id} value={w.id}>{w.name}</Select.Option>)}
            </Select>
          </Col>
          <Col span={6}>
            <Select data-testid="status" style={{ width: "100%" }} value={status} placeholder="全部状态"
              onChange={(v) => { setStatus(v); if (wsId != null) load(wsId); }}>
              <Select.Option value="">全部状态</Select.Option>
              <Select.Option value="open">招聘中</Select.Option>
              <Select.Option value="closed">已关闭</Select.Option>
            </Select>
          </Col>
          <Col span={6} offset={6} style={{ textAlign: "right" }}>
            <Button type="primary" data-testid="open-create" onClick={() => setOpen(true)}>创建职位</Button>
          </Col>
        </Row>
      </Card>
      {matchPrompt && <Typography.Paragraph type="secondary" data-testid="match-prompt">生成匹配词：{matchPrompt}</Typography.Paragraph>}
      <Table
        rowKey={(r) => String(r.job_id)}
        columns={columns}
        dataSource={items}
        loading={loading}
        pagination={{ total, pageSize: 50, showTotal: (t) => `共 ${t} 个职位` }}
      />
      <Modal title="创建职位" open={open} onCancel={() => setOpen(false)} onOk={doCreate} okText="创建" cancelText="取消">
        <Form form={form} layout="vertical">
          <Form.Item name="name" label="职位名称" rules={[{ required: true, message: "请输入职位名称" }]}>
            <Input data-testid="name" placeholder="职位名称" />
          </Form.Item>
          <Form.Item name="description" label="岗位要求（自然语言）" rules={[{ required: true, message: "请输入岗位要求" }]}>
            <Input.TextArea data-testid="description" rows={4} placeholder="例如：5 年以上 Java 后端经验，熟悉 Spring Boot" />
          </Form.Item>
          <Form.Item name="headcount" label="招聘人数" initialValue="1">
            <Input data-testid="headcount" placeholder="招聘人数" />
          </Form.Item>
          <Form.Item name="city" label="城市">
            <Input data-testid="city" placeholder="城市" />
          </Form.Item>
          <Form.Item name="salary" label="薪资范围（可选）">
            <Input data-testid="salary" placeholder="20k-40k" />
          </Form.Item>
        </Form>
      </Modal>
    </div>
  );
}