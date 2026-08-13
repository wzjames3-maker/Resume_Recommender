import { useEffect, useRef, useState } from "react";
import { Card, Col, Input, List, Modal, Popconfirm, Row, Select, Space, Typography, Button, message } from "antd";
import { PlusOutlined, FileTextOutlined, MessageOutlined, EditOutlined, DeleteOutlined } from "@ant-design/icons";
import { Link } from "react-router-dom";
import { useAuthStore } from "../stores/authStore";
import * as wsApi from "../api/workspaces";
import * as kbApi from "../api/knowledgeBase";

export default function DashboardPage() {
  const user = useAuthStore((s) => s.user);
  const [workspaces, setWorkspaces] = useState<any[]>([]);
  const [wsId, setWsId] = useState<number | null>(null);
  const [kbs, setKbs] = useState<any[]>([]);
  const [kbName, setKbName] = useState("");
  const [wsName, setWsName] = useState("");
  const [renameOpen, setRenameOpen] = useState(false);
  const [renameKb, setRenameKb] = useState<any>(null);
  const [newKbName, setNewKbName] = useState("");
  const listSeq = useRef(0);

  const loadKbs = async (id: number) => {
    const items = await kbApi.list(id);
    setKbs(items);
  };

  useEffect(() => {
    const req = ++listSeq.current;
    wsApi.list().then((items) => {
      if (req !== listSeq.current) return;
      setWorkspaces(items);
      if (items.length > 0) setWsId(items[0].id);
    });
  }, []);

  useEffect(() => {
    if (wsId != null) loadKbs(wsId);
  }, [wsId]);

  const createWs = async () => {
    if (!wsName) return;
    try {
      const ws = await wsApi.create(wsName);
      setWsName("");
      const items = await wsApi.list();
      setWorkspaces(items);
      setWsId(ws.id);
      await loadKbs(ws.id);
    } catch (err: any) {
      message.error(err?.response?.data?.message ?? "创建工作区失败");
    }
  };

  const createKb = async () => {
    if (!wsId || !kbName) return;
    try {
      await kbApi.create(wsId, { name: kbName });
      setKbName("");
      await loadKbs(wsId);
    } catch (err: any) {
      message.error(err?.response?.data?.message ?? "创建知识库失败");
    }
  };

  const doRename = async () => {
    if (!renameKb || !newKbName) return;
    try {
      await kbApi.update(renameKb.id, { name: newKbName });
      setRenameOpen(false);
      setNewKbName("");
      if (wsId != null) await loadKbs(wsId);
    } catch (err: any) {
      message.error(err?.response?.data?.message ?? "改名失败");
    }
  };

  const doDeleteKb = async (kbId: number) => {
    try {
      await kbApi.remove(kbId);
      if (wsId != null) await loadKbs(wsId);
    } catch (err: any) {
      message.error(err?.response?.data?.message ?? "删除失败（请先处理解析中的文档）");
    }
  };

  return (
    <div>
      <Typography.Title level={3}>工作台</Typography.Title>
      <Typography.Paragraph type="secondary">
        欢迎回来，{user?.nickname ?? user?.email}
      </Typography.Paragraph>

      <Row gutter={16} style={{ marginBottom: 24 }}>
        <Col span={8}>
          <Card>
            <Typography.Title level={4} style={{ marginTop: 0 }}>{workspaces.length}</Typography.Title>
            <Typography.Text type="secondary">我的工作区</Typography.Text>
          </Card>
        </Col>
        <Col span={8}>
          <Card>
            <Typography.Title level={4} style={{ marginTop: 0 }}>{kbs.length}</Typography.Title>
            <Typography.Text type="secondary">知识库</Typography.Text>
          </Card>
        </Col>
        <Col span={8}>
          <Card>
            <Typography.Title level={4} style={{ marginTop: 0 }}>{kbs.reduce((n, kb) => n + (kb.doc_count ?? 0), 0)}</Typography.Title>
            <Typography.Text type="secondary">文档</Typography.Text>
          </Card>
        </Col>
      </Row>

      <Card title="我的工作区" style={{ marginBottom: 24 }}>
        <Space style={{ marginBottom: 16 }}>
          <Select data-testid="ws-select" style={{ width: 200 }} value={wsId ?? undefined} onChange={(v) => setWsId(v)}>
            {workspaces.map((w) => (
              <Select.Option key={w.id} value={w.id}>{w.name}</Select.Option>
            ))}
          </Select>
        </Space>
        <Space.Compact style={{ width: "100%", maxWidth: 480 }}>
          <Input data-testid="ws-name" placeholder="新建工作区名称" value={wsName} onChange={(e) => setWsName(e.target.value)} />
          <Button data-testid="create-ws" type="primary" icon={<PlusOutlined />} onClick={createWs}>创建工作区</Button>
        </Space.Compact>
      </Card>

      <Card
        title="知识库"
        extra={
          <Space.Compact>
            <Input data-testid="kb-name" placeholder="新建知识库名称" value={kbName} onChange={(e) => setKbName(e.target.value)} />
            <Button data-testid="create-kb" type="primary" icon={<PlusOutlined />} onClick={createKb}>创建</Button>
          </Space.Compact>
        }
      >
        <List
          dataSource={kbs}
          locale={{ emptyText: "暂无知识库，先创建一个吧" }}
          renderItem={(kb) => (
            <List.Item
              actions={[
                <Link key="chat" to={`/documents/${kb.id}`}><Button size="small" icon={<FileTextOutlined />}>文档管理</Button></Link>,
                <Link key="chat2" to={`/chat/${kb.id}`}><Button size="small" icon={<MessageOutlined />}>进入对话</Button></Link>,
                <Button key="rename" size="small" icon={<EditOutlined />} data-testid="rename-kb"
                  onClick={() => { setRenameKb(kb); setNewKbName(String(kb.name)); setRenameOpen(true); }}>改名</Button>,
                <Popconfirm key="del" title="确认删除该知识库？" onConfirm={() => doDeleteKb(kb.id)}>
                  <Button size="small" danger icon={<DeleteOutlined />} data-testid="delete-kb">删除</Button>
                </Popconfirm>,
              ]}
            >
              <List.Item.Meta title={kb.name} description={`${kb.doc_count ?? 0} 文档 · ${kb.chunk_count ?? 0} chunks`} />
            </List.Item>
          )}
        />
      </Card>
      <Modal title="重命名知识库" open={renameOpen} onCancel={() => setRenameOpen(false)} onOk={doRename} okText="保存" cancelText="取消">
        <Input data-testid="new-kb-name" placeholder="新名称" value={newKbName} onChange={(e) => setNewKbName(e.target.value)} maxLength={64} />
      </Modal>
    </div>
  );
}