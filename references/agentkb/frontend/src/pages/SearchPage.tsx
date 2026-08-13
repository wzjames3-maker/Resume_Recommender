import { useEffect, useState } from "react";
import { Button, Card, Col, Input, Row, Select, Space, Tag, Typography } from "antd";
import { SendOutlined } from "@ant-design/icons";
import { searchChat, SearchCard, JobCandidate, StatisticsCard } from "../api/search";
import * as wsApi from "../api/workspaces";

interface Turn {
  user: string;
  summary: string;
  cards: SearchCard[];
  jobCandidates: JobCandidate[];
  statistics?: StatisticsCard;
}

export default function SearchPage() {
  const [workspaces, setWorkspaces] = useState<{ id: number; name: string }[]>([]);
  const [wsId, setWsId] = useState<number | null>(null);
  const [message, setMessage] = useState("");
  const [turns, setTurns] = useState<Turn[]>([]);
  const [conversationId, setConversationId] = useState<number | undefined>(undefined);
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(false);

  useEffect(() => {
    wsApi.list().then((items) => {
      setWorkspaces(items);
      if (items.length > 0) setWsId(items[0].id);
    });
  }, []);

  const send = async (text?: string) => {
    const msg = text ?? message;
    if (!msg || wsId == null || loading) return;
    setError("");
    setLoading(true);
    try {
      const result = await searchChat(wsId, msg, conversationId);
      setTurns((prev) => [...prev, { user: msg, summary: result.summary, cards: result.cards, jobCandidates: result.jobCandidates, statistics: result.statistics }]);
      setConversationId(result.conversationId);
      setMessage("");
    } catch (e) {
      setError(e instanceof Error ? e.message : "请求失败，请检查网络后重试");
    } finally {
      setLoading(false);
    }
  };

  const pickJob = (job: JobCandidate) => {
    send(`选择职位 #${job.job_id}：${job.name}`);
  };

  return (
    <div style={{ maxWidth: 900, margin: "0 auto" }}>
      <Typography.Title level={3}>智能人事助手</Typography.Title>
      <Typography.Paragraph type="secondary">
        意图识别：搜索人才 / 按岗位搜索 / 追问收敛 / 统计查询 / 写请求引导 / 闲聊 / 超出范围
      </Typography.Paragraph>
      <Space style={{ marginBottom: 16 }}>
        <Select
          data-testid="workspace"
          style={{ width: 200 }}
          value={wsId ?? undefined}
          onChange={(v) => { setWsId(v); setTurns([]); setConversationId(undefined); }}
        >
          {workspaces.map((w) => (
            <Select.Option key={w.id} value={w.id}>{w.name}</Select.Option>
          ))}
        </Select>
      </Space>

      <div style={{ marginBottom: 16 }}>
        {turns.map((t, i) => (
          <Card key={i} style={{ marginBottom: 16 }} data-testid="turn">
            <Typography.Paragraph><Typography.Text strong>我问：</Typography.Text>{t.user}</Typography.Paragraph>
            <Typography.Paragraph><Typography.Text strong>回答：</Typography.Text>{t.summary}</Typography.Paragraph>
            {t.jobCandidates.length > 0 && (
              <div style={{ marginBottom: 8 }}>
                <Typography.Text strong>候选职位：</Typography.Text>
                <Space wrap>
                  {t.jobCandidates.map((j) => (
                    <Button key={j.job_id} size="small" data-testid="job-option" onClick={() => pickJob(j)}>
                      {j.name}（{j.city ?? "—"}，{j.headcount} 人）
                    </Button>
                  ))}
                </Space>
              </div>
            )}
            {t.statistics && (
              <div data-testid="statistics-card" style={{ marginBottom: 8 }}>
                <Typography.Text strong>统计：</Typography.Text> 共 {t.statistics.count} 位
                {t.statistics.dimension && t.statistics.distribution.length > 0 && (
                  <div>
                    {t.statistics.distribution.map((g) => (
                      <Tag key={g.key}>{g.key}: {g.count}</Tag>
                    ))}
                  </div>
                )}
              </div>
            )}
            <Row gutter={[8, 8]}>
              {t.cards.map((c) => (
                <Col span={8} key={c.candidate_id}>
                  <Card size="small" data-testid="card">
                    <Typography.Text strong>{c.name}</Typography.Text>
                    <div style={{ fontSize: 12, color: "#888" }}>
                      {c.city ?? "—"} · {c.highest_degree ?? "—"} · {c.years_experience ?? "—"} 年
                    </div>
                    {c.matched_conditions.length > 0 && (
                      <div style={{ marginTop: 4 }}>
                        {c.matched_conditions.map((m) => <Tag key={m} color="blue" style={{ fontSize: 11 }}>{m}</Tag>)}
                      </div>
                    )}
                  </Card>
                </Col>
              ))}
            </Row>
          </Card>
        ))}
      </div>

      <div style={{ display: "flex", gap: 8 }}>
        <Input.TextArea
          data-testid="message"
          value={message}
          onChange={(e) => setMessage(e.target.value)}
          placeholder="例如：找 5 年以上 Java 后端，base 杭州；或按岗位搜人、统计人才分布"
          autoSize={{ minRows: 2, maxRows: 4 }}
          onPressEnter={(e) => { if (!e.shiftKey) { e.preventDefault(); send(); } }}
        />
        <Button type="primary" icon={<SendOutlined />} data-testid="send" onClick={() => send()} loading={loading}>
          {loading ? "搜人中…" : "发送"}
        </Button>
      </div>
      {error && <Typography.Text type="danger" data-testid="error">{error}</Typography.Text>}
    </div>
  );
}