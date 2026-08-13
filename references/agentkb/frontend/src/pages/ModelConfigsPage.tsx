import { useEffect, useState } from "react";
import { Button, Card, Form, Input, Select, Space, Table, Tag, Typography, message } from "antd";
import { listConfigs, testConfig, upsertConfig } from "../api/modelConfigs";
import * as wsApi from "../api/workspaces";

const TYPES = ["llm", "embedding", "rerank"];

export default function ModelConfigsPage() {
  const [workspaces, setWorkspaces] = useState<{ id: number; name: string }[]>([]);
  const [wsId, setWsId] = useState<number | null>(null);
  const [configs, setConfigs] = useState<Record<string, unknown>[]>([]);
  const [form] = Form.useForm();
  const [testResult, setTestResult] = useState<Record<string, string>>({});
  const [msg, setMsg] = useState("");

  const load = async (curWs: number) => {
    try {
      const items = await listConfigs(curWs);
      setConfigs(items);
      setMsg("");
    } catch {
      setMsg("加载配置失败");
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

  const doSave = async () => {
    if (wsId == null) return;
    const values = await form.validateFields();
    try {
      await upsertConfig(wsId, {
        model_type: values.model_type,
        base_url: values.base_url,
        model_name: values.model_name,
        api_key: values.api_key,
      });
      form.resetFields();
      message.success("配置已保存");
      await load(wsId);
    } catch (err: any) {
      message.error(err?.response?.data?.message ?? "保存失败（需要 admin 权限或 base_url 非法）");
    }
  };

  const doTest = async (type: string) => {
    if (wsId == null) return;
    try {
      const res = await testConfig(wsId, type);
      setTestResult((prev) => ({ ...prev, [type]: res.status }));
    } catch {
      setTestResult((prev) => ({ ...prev, [type]: "failed" }));
    }
  };

  const columns = [
    { title: "类型", dataIndex: "model_type", key: "model_type", width: 100, render: (v: string) => <Tag color="blue">{v}</Tag> },
    { title: "模型名", dataIndex: "model_name", key: "model_name" },
    { title: "Base URL", dataIndex: "base_url", key: "base_url" },
    { title: "Key", dataIndex: "key_prefix", key: "key_prefix", width: 120, render: (v: unknown) => `${v}...` },
    { title: "版本", dataIndex: "model_config_revision", key: "model_config_revision", width: 80 },
    { title: "操作", key: "actions", width: 150, render: (_: unknown, c: Record<string, unknown>) => (
      <Space>
        <Button size="small" data-testid="test" onClick={() => doTest(String(c.model_type))}>测试连通</Button>
        {testResult[String(c.model_type)] && <Tag color={testResult[String(c.model_type)] === "ok" ? "green" : "red"}>{testResult[String(c.model_type)]}</Tag>}
      </Space>
    )},
  ];

  return (
    <div>
      <Typography.Title level={3}>模型配置</Typography.Title>
      <Card style={{ marginBottom: 16 }}>
        <Space>
          <Select data-testid="workspace" style={{ width: 180 }} value={wsId ?? undefined}
            onChange={(v) => { setWsId(v); load(v); }}>
            {workspaces.map((w) => <Select.Option key={w.id} value={w.id}>{w.name}</Select.Option>)}
          </Select>
        </Space>
      </Card>
      <Card title="新增 / 更新配置" style={{ marginBottom: 16 }}>
        <Form form={form} layout="inline" style={{ display: "flex", flexWrap: "wrap", gap: 8 }}>
          <Form.Item name="model_type" initialValue="llm" rules={[{ required: true }]}>
            <Select data-testid="type" style={{ width: 120 }}>
              {TYPES.map((t) => <Select.Option key={t} value={t}>{t}</Select.Option>)}
            </Select>
          </Form.Item>
          <Form.Item name="base_url" rules={[{ required: true, message: "请输入 Base URL" }]}>
            <Input data-testid="base-url" placeholder="https://api.example.com/v1" style={{ width: 260 }} />
          </Form.Item>
          <Form.Item name="model_name" rules={[{ required: true, message: "请输入模型名" }]}>
            <Input data-testid="model-name" placeholder="模型名" style={{ width: 160 }} />
          </Form.Item>
          <Form.Item name="api_key" rules={[{ required: true, message: "请输入 API Key" }]}>
            <Input.Password data-testid="api-key" placeholder="API Key" style={{ width: 200 }} />
          </Form.Item>
          <Button type="primary" data-testid="save" onClick={doSave}>保存</Button>
        </Form>
        {msg && <Typography.Text type="danger" data-testid="msg">{msg}</Typography.Text>}
      </Card>
      <Table rowKey={(c) => String(c.id)} columns={columns} dataSource={configs} pagination={false} />
    </div>
  );
}