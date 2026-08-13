import { useEffect, useState } from "react";
import { Button, Card, Descriptions, Empty, Input, Popconfirm, Select, Space, Table, Tag, Typography, message } from "antd";
import { getDetail, getUsage, inviteMember, remove, removeMember, updateMemberRole } from "../api/workspaces";
import * as wsApi from "../api/workspaces";

export default function WorkspacePage() {
  const [workspaces, setWorkspaces] = useState<{ id: number; name: string }[]>([]);
  const [wsId, setWsId] = useState<number | null>(null);
  const [detail, setDetail] = useState<Record<string, unknown> | null>(null);
  const [usage, setUsage] = useState<Record<string, unknown> | null>(null);
  const [inviteEmail, setInviteEmail] = useState("");
  const [inviteRole, setInviteRole] = useState("member");
  const [msg, setMsg] = useState("");

  const load = async (curWs: number) => {
    try {
      const d = await getDetail(curWs);
      setDetail(d);
      const u = await getUsage(curWs);
      setUsage(u);
      setMsg("");
    } catch {
      setMsg("加载工作区信息失败");
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

  const doInvite = async () => {
    if (wsId == null || !inviteEmail) return;
    try {
      await inviteMember(wsId, inviteEmail, inviteRole);
      setInviteEmail("");
      await load(wsId);
    } catch {
      message.error("邀请失败（需 admin 权限、账号须存在且未加入）");
    }
  };

  const doSetRole = async (userId: number, role: string) => {
    if (wsId == null) return;
    try {
      await updateMemberRole(wsId, userId, role);
      await load(wsId);
    } catch {
      message.error("修改角色失败（owner 角色不可修改）");
    }
  };

  const doRemove = async (userId: number) => {
    if (wsId == null) return;
    try {
      await removeMember(wsId, userId);
      await load(wsId);
    } catch {
      message.error("移除失败（owner 不可移除）");
    }
  };

  const doDelete = async () => {
    if (wsId == null) return;
    try {
      await remove(wsId);
      wsApi.list().then((rows) => {
        setWorkspaces(rows);
        if (rows.length > 0) {
          setWsId(rows[0].id);
          load(rows[0].id);
        } else {
          setDetail(null);
        }
      });
    } catch {
      message.error("删除失败（仅 owner 可删除）");
    }
  };

  const members = (detail?.members ?? []) as Record<string, unknown>[];

  const memberColumns = [
    { title: "昵称", dataIndex: "nickname", key: "nickname", render: (v: unknown, m: Record<string, unknown>) => String(v || m.email) },
    { title: "邮箱", dataIndex: "email", key: "email" },
    { title: "角色", dataIndex: "role", key: "role", width: 100, render: (v: string) => <Tag color={v === "owner" ? "gold" : v === "admin" ? "blue" : "default"}>{v}</Tag> },
    { title: "加入时间", dataIndex: "joined_at", key: "joined_at", width: 180, render: (v: unknown) => String(v ?? "").slice(0, 16) },
    { title: "操作", key: "actions", width: 220, render: (_: unknown, m: Record<string, unknown>) => (
      String(m.role) !== "owner" && (
        <Space>
          <Select size="small" value={String(m.role)} style={{ width: 90 }}
            onChange={(v) => doSetRole(Number(m.user_id), v)}>
            <Select.Option value="member">member</Select.Option>
            <Select.Option value="admin">admin</Select.Option>
          </Select>
          <Button size="small" danger data-testid="remove-member" onClick={() => doRemove(Number(m.user_id))}>移除</Button>
        </Space>
      )
    )},
  ];

  return (
    <div>
      <Typography.Title level={3}>工作区管理</Typography.Title>
      <Card style={{ marginBottom: 16 }}>
        <Space>
          <Select data-testid="workspace" style={{ width: 180 }} value={wsId ?? undefined}
            onChange={(v) => { setWsId(v); load(v); }}>
            {workspaces.map((w) => <Select.Option key={w.id} value={w.id}>{w.name}</Select.Option>)}
          </Select>
          <Popconfirm title="确认删除该工作区？所有数据将清空。" onConfirm={doDelete}>
            <Button danger data-testid="delete-ws">删除工作区</Button>
          </Popconfirm>
        </Space>
      </Card>
      {detail ? (
        <>
          <Card title="工作区信息" style={{ marginBottom: 16 }}>
            <Descriptions column={3} size="small" bordered>
              <Descriptions.Item label="名称" data-testid="ws-name">{String(detail.name)}</Descriptions.Item>
              <Descriptions.Item label="我的角色">{String(detail.role)}</Descriptions.Item>
              <Descriptions.Item label="创建时间">{String(detail.created_at ?? "").slice(0, 16)}</Descriptions.Item>
            </Descriptions>
            {usage && (
              <Typography.Paragraph style={{ marginTop: 12 }} data-testid="usage">
                本月用量 {String(usage.tokens_used_this_month)} / {String(usage.monthly_limit)} tokens（剩余 {String(usage.remaining)}）
              </Typography.Paragraph>
            )}
          </Card>
          <Card title="成员管理" style={{ marginBottom: 16 }}>
            <Space style={{ marginBottom: 16 }}>
              <Input data-testid="invite-email" placeholder="邀请成员邮箱" value={inviteEmail}
                onChange={(e) => setInviteEmail(e.target.value)} style={{ width: 240 }} />
              <Select data-testid="invite-role" style={{ width: 110 }} value={inviteRole} onChange={(v) => setInviteRole(v)}>
                <Select.Option value="member">member</Select.Option>
                <Select.Option value="admin">admin</Select.Option>
              </Select>
              <Button type="primary" data-testid="invite" onClick={doInvite}>邀请</Button>
            </Space>
            <Table rowKey={(m) => String(m.user_id)} columns={memberColumns} dataSource={members} pagination={false} data-testid="member-table" />
          </Card>
        </>
      ) : (
        <Empty data-testid="no-ws" description={msg || "暂无工作区"} />
      )}
    </div>
  );
}