import { useEffect, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { Button, Card, Select, Space, Table, Tag, Typography, Upload, message, List } from "antd";
import { UploadOutlined } from "@ant-design/icons";
import { listDocuments, uploadDocument, deleteDocument, retryDocument, listChunks } from "../api/documents";
import { get as getKb, list as listKbs } from "../api/knowledgeBase";
import * as wsApi from "../api/workspaces";

const STATUS_COLOR: Record<string, string> = {
  pending: "orange", processing: "blue", ready: "green", failed: "red",
};

export default function DocumentsPage() {
  const { kbId } = useParams();
  const [kb, setKb] = useState<Record<string, unknown> | null>(null);
  const [kbs, setKbs] = useState<{ id: number; name: string }[]>([]);
  const [wsId, setWsId] = useState<number | null>(null);
  const [docs, setDocs] = useState<Record<string, unknown>[]>([]);
  const [total, setTotal] = useState(0);
  const [status, setStatus] = useState("");
  const [msg, setMsg] = useState("");
  const [chunks, setChunks] = useState<Record<string, unknown>[]>([]);
  const [chunkDoc, setChunkDoc] = useState<number | null>(null);

  const loadDocs = async (curKbId: number) => {
    try {
      const data = await listDocuments(curKbId, { status: status || undefined, page: 1, page_size: 50 });
      setDocs(data.items);
      setTotal(data.total);
      setMsg("");
    } catch {
      setMsg("加载文档失败");
    }
  };

  useEffect(() => {
    if (kbId) {
      getKb(Number(kbId)).then((d) => {
        setKb(d);
        setWsId(d.workspace_id);
        loadDocs(Number(kbId));
      });
      return;
    }
    wsApi.list().then((rows) => {
      if (rows.length === 0) return;
      setWsId(rows[0].id);
      listKbs(rows[0].id).then((items) => {
        setKbs(items);
        if (items.length > 0) {
          setKb({ id: items[0].id, name: items[0].name, workspace_id: rows[0].id });
          loadDocs(items[0].id);
        }
      });
    });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [kbId]);

  const doUpload = async (file: File) => {
    if (kb == null) return false;
    try {
      await uploadDocument(Number(kb.id), file);
      await loadDocs(Number(kb.id));
      message.success(`${file.name} 上传成功，等待解析`);
    } catch (err: any) {
      message.error(err?.message ?? "上传失败");
    }
    return false;
  };

  const doDelete = async (docId: number) => {
    if (kb == null) return;
    try {
      await deleteDocument(docId);
      await loadDocs(Number(kb.id));
    } catch {
      message.error("删除失败（解析中的文档不可删除）");
    }
  };

  const doRetry = async (docId: number) => {
    if (kb == null) return;
    try {
      await retryDocument(docId);
      await loadDocs(Number(kb.id));
    } catch {
      message.error("重试失败");
    }
  };

  const doViewChunks = async (docId: number) => {
    if (chunkDoc === docId) { setChunks([]); setChunkDoc(null); return; }
    try {
      const data = await listChunks(docId, { page: 1, page_size: 100 });
      setChunks(data.items);
      setChunkDoc(docId);
    } catch {
      message.error("加载 chunks 失败");
    }
  };

  const columns = [
    { title: "文件名", dataIndex: "filename", key: "filename" },
    { title: "状态", dataIndex: "status", key: "status", width: 110, render: (v: string) => <Tag color={STATUS_COLOR[v] ?? "default"}>{v}</Tag> },
    { title: "Chunks", dataIndex: "chunk_count", key: "chunk_count", width: 90 },
    { title: "大小", dataIndex: "file_size", key: "file_size", width: 100, render: (v: unknown) => `${Number(v) / 1024 >= 1 ? (Number(v) / 1024).toFixed(1) + " KB" : v + " B"}` },
    { title: "创建时间", dataIndex: "created_at", key: "created_at", width: 180, render: (v: unknown) => String(v ?? "").slice(0, 16) },
    { title: "操作", key: "actions", width: 220, render: (_: unknown, d: Record<string, unknown>) => (
      <Space>
        {d.status === "failed" && <Button size="small" data-testid="retry" onClick={() => doRetry(Number(d.id))}>重试</Button>}
        <Button size="small" data-testid="chunks" onClick={() => doViewChunks(Number(d.id))}>
          {chunkDoc === Number(d.id) ? "收起 chunks" : "chunks"}
        </Button>
        <Button size="small" danger data-testid="delete" onClick={() => doDelete(Number(d.id))}>删除</Button>
      </Space>
    )},
  ];

  return (
    <div>
      <Typography.Title level={3}>知识库文档管理</Typography.Title>
      <Link to="/">返回工作台</Link>
      <Card style={{ marginTop: 16, marginBottom: 16 }}>
        <Space wrap>
          {kbId == null && (
            <Select data-testid="kb-select" style={{ width: 200 }} value={kb ? String(kb.id) : undefined}
              onChange={(v) => { const id = Number(v); const cur = kbs.find((k) => k.id === id); if (cur) { setKb({ ...cur, workspace_id: wsId }); loadDocs(id); } }}>
              {kbs.map((k) => <Select.Option key={k.id} value={String(k.id)}>{k.name}</Select.Option>)}
            </Select>
          )}
          <Select data-testid="status" style={{ width: 130 }} value={status} placeholder="全部状态"
            onChange={(v) => { setStatus(v); if (kb) loadDocs(Number(kb.id)); }}>
            <Select.Option value="">全部状态</Select.Option>
            <Select.Option value="pending">等待解析</Select.Option>
            <Select.Option value="processing">解析中</Select.Option>
            <Select.Option value="ready">就绪</Select.Option>
            <Select.Option value="failed">失败</Select.Option>
          </Select>
          <Upload showUploadList={false} beforeUpload={doUpload} accept=".pdf,.md,.txt,.docx">
            <Button type="primary" icon={<UploadOutlined />} data-testid="upload">上传文档</Button>
          </Upload>
        </Space>
        {kb && <Typography.Text type="secondary" data-testid="kb-info" style={{ display: "block", marginTop: 8 }}>知识库：{String(kb.name)}</Typography.Text>}
      </Card>
      {msg && <Typography.Text type="danger" data-testid="msg">{msg}</Typography.Text>}
      <Table
        rowKey={(d) => String(d.id)}
        columns={columns}
        dataSource={docs}
        pagination={{ total, pageSize: 50, showTotal: (t) => `共 ${t} 个文档` }}
        expandable={{
          expandedRowRender: (d) => (
            chunkDoc === Number(d.id) ? (
              <List
                size="small"
                dataSource={chunks}
                renderItem={(c, i) => <List.Item key={i} data-testid="chunk">#{String(c.position)} · {String(c.content)}</List.Item>}
              />
            ) : null
          ),
        }}
      />
    </div>
  );
}