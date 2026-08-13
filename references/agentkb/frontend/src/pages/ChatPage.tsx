import { useEffect, useState } from "react";
import { useParams } from "react-router-dom";
import { Button, Card, Col, Empty, Input, List, Row, Typography, Popconfirm, message as antdMessage } from "antd";
import { SendOutlined, DeleteOutlined, MessageOutlined } from "@ant-design/icons";
import { streamChat } from "../api/chat";
import { listConversations, listMessages, deleteConversation } from "../api/conversations";
import { get as getKb } from "../api/knowledgeBase";

interface MsgView {
  role: string;
  content: string;
}

export default function ChatPage() {
  const { kbId } = useParams();
  const [message, setMessage] = useState("");
  const [answer, setAnswer] = useState("");
  const [error, setError] = useState("");
  const [convs, setConvs] = useState<Record<string, unknown>[]>([]);
  const [convId, setConvId] = useState<number | null>(null);
  const [history, setHistory] = useState<MsgView[]>([]);
  const [kbName, setKbName] = useState("");

  const loadConvs = async (curKbId: number) => {
    try {
      const data = await listConversations(curKbId, 1, 50);
      setConvs(data.items);
    } catch {
      setConvs([]);
    }
  };

  useEffect(() => {
    if (kbId) {
      loadConvs(Number(kbId));
      getKb(Number(kbId)).then((d) => setKbName(d.name)).catch(() => setKbName(""));
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [kbId]);

  const loadHistory = async (curConvId: number) => {
    try {
      const data = await listMessages(curConvId, 1, 100);
      setHistory(data.items.map((m: { role: string; content: string }) => ({ role: m.role, content: m.content })));
      setConvId(curConvId);
      setAnswer("");
    } catch {
      antdMessage.error("加载历史消息失败");
    }
  };

  const doDelete = async (curConvId: number) => {
    try {
      await deleteConversation(curConvId);
      setConvs((prev) => prev.filter((c) => Number(c.id) !== curConvId));
      if (convId === curConvId) {
        setConvId(null);
        setHistory([]);
      }
    } catch {
      antdMessage.error("删除会话失败");
    }
  };

  const send = async () => {
    if (!message) return;
    const text = message.trim();
    setAnswer("");
    setError("");
    setHistory((prev) => [...prev, { role: "user", content: text }]);
    setMessage("");
    try {
      await streamChat(
        { knowledge_base_id: kbId ? Number(kbId) : 0, conversation_id: convId ?? undefined, message: text },
        {
          onToken: (t) => setAnswer((prev) => prev + t),
          onDone: () => {
            setTimeout(() => {
              if (kbId) loadConvs(Number(kbId));
            }, 300);
          },
          onError: (m) => setError(m),
        }
      );
    } catch {
      antdMessage.error("请求失败，请检查网络后重试");
    }
  };

  if (!kbId) {
    return (
      <Card>
        <Empty description="未选择知识库，请先在工作台选择或创建知识库后进入对话" />
      </Card>
    );
  }

  return (
    <Row gutter={16} style={{ height: "calc(100vh - 120px)" }}>
      <Col span={6}>
        <Card title="会话历史" style={{ height: "100%" }} styles={{ body: { overflow: "auto", height: "calc(100% - 57px)" } }}>
          <List
            dataSource={convs}
            locale={{ emptyText: "暂无会话" }}
            renderItem={(c) => (
              <List.Item
                actions={[
                  <Popconfirm key="del" title="删除该会话？" onConfirm={() => doDelete(Number(c.id))}>
                    <Button size="small" type="text" icon={<DeleteOutlined />} data-testid="delete-conv" />
                  </Popconfirm>,
                ]}
              >
                <List.Item.Meta
                  avatar={<MessageOutlined />}
                  title={
                    <Button type={convId === Number(c.id) ? "primary" : "text"} size="small" onClick={() => loadHistory(Number(c.id))} data-testid="conv">
                      {String(c.title)}
                    </Button>
                  }
                  description={String(c.updated_at ?? "").slice(0, 16)}
                />
              </List.Item>
            )}
          />
        </Card>
      </Col>
      <Col span={18}>
        <Card
          title={kbName ? `对话 · ${kbName}` : "对话"}
          style={{ height: "100%", display: "flex", flexDirection: "column" }}
          styles={{ body: { flex: 1, display: "flex", flexDirection: "column", overflow: "hidden" } }}
        >
          <div style={{ flex: 1, overflow: "auto" }}>
            {history.map((m, i) => (
              <div key={i} style={{ marginBottom: 12 }}>
                <Typography.Text strong>{m.role === "user" ? "我" : "AI"}</Typography.Text>
                <div style={{
                  background: m.role === "user" ? "#e6f4ff" : "#fafafa",
                  padding: 8, borderRadius: 6, marginTop: 4, whiteSpace: "pre-wrap",
                }}>
                  {m.content}
                </div>
              </div>
            ))}
            {answer && (
              <div style={{ marginBottom: 12 }}>
                <Typography.Text strong>AI</Typography.Text>
                <div style={{ background: "#fafafa", padding: 8, borderRadius: 6, marginTop: 4, whiteSpace: "pre-wrap" }}>
                  {answer}
                </div>
              </div>
            )}
          </div>
          {error && <Typography.Text type="danger" data-testid="error">{error}</Typography.Text>}
          <div style={{ display: "flex", gap: 8, marginTop: 12 }}>
            <Input.TextArea
              data-testid="message"
              value={message}
              onChange={(e) => setMessage(e.target.value)}
              placeholder="输入问题，Enter 发送"
              autoSize={{ minRows: 2, maxRows: 4 }}
              onPressEnter={(e) => { if (!e.shiftKey) { e.preventDefault(); send(); } }}
            />
            <Button type="primary" icon={<SendOutlined />} data-testid="send" onClick={send}>发送</Button>
          </div>
        </Card>
      </Col>
    </Row>
  );
}