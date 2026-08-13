import { useMemo, useState } from "react";
import { Layout, Menu, Avatar, Dropdown, Typography, Modal, Input, message } from "antd";
import {
  AppstoreOutlined, MessageOutlined, TeamOutlined,
  FileTextOutlined, SettingOutlined, ApartmentOutlined,
  LogoutOutlined, UserOutlined, EditOutlined,
} from "@ant-design/icons";
import { Link, Outlet, useLocation, useNavigate } from "react-router-dom";
import { useAuthStore } from "../stores/authStore";
import * as authApi from "../api/auth";

const { Header, Sider, Content } = Layout;

const MENU_ITEMS = [
  { key: "/", icon: <AppstoreOutlined />, label: <Link to="/">工作台</Link> },
  {
    key: "hr",
    icon: <TeamOutlined />,
    label: "人事部",
    children: [
      { key: "/candidates", label: <Link to="/candidates">候选人管理</Link> },
      { key: "/jobs", label: <Link to="/jobs">职位管理</Link> },
      { key: "/resumes", label: <Link to="/resumes">简历解析</Link> },
      { key: "/interviews", label: <Link to="/interviews">面试管理</Link> },
      { key: "/search", label: <Link to="/search">智能人事助手</Link> },
    ],
  },
  { key: "/chat", icon: <MessageOutlined />, label: <Link to="/chat">知识库对话</Link> },
  { key: "/documents", icon: <FileTextOutlined />, label: <Link to="/documents">知识库文档</Link> },
  { key: "/models", icon: <SettingOutlined />, label: <Link to="/models">模型配置</Link> },
  { key: "/workspace", icon: <ApartmentOutlined />, label: <Link to="/workspace">工作区管理</Link> },
];

export default function AdminLayout() {
  const location = useLocation();
  const navigate = useNavigate();
  const user = useAuthStore((s) => s.user);
  const logout = useAuthStore((s) => s.logout);
  const setUser = useAuthStore((s) => s.setUser);
  const accessToken = useAuthStore((s) => s.accessToken);
  const [editOpen, setEditOpen] = useState(false);
  const [nickname, setNickname] = useState("");

  const selectedKey = useMemo(() => {
    const match = MENU_ITEMS
      .flatMap((m) => (m.children ?? [m]).map((c) => c.key))
      .filter((k) => location.pathname.startsWith(k));
    return match.length > 0 ? match.sort((a, b) => b.length - a.length)[0] : "/";
  }, [location.pathname]);

  const [openKeys, setOpenKeys] = useState<string[]>(["hr"]);

  const doUpdateProfile = async () => {
    if (!accessToken || !nickname) return;
    try {
      const updated = await authApi.updateMe(accessToken, nickname);
      setUser(updated);
      setEditOpen(false);
      message.success("资料已更新");
    } catch {
      message.error("更新失败");
    }
  };

  return (
    <Layout style={{ minHeight: "100vh" }}>
      <Sider theme="light" width={200} style={{ borderRight: "1px solid #f0f0f0" }}>
        <div style={{ height: 56, display: "flex", alignItems: "center", justifyContent: "center", fontWeight: 600, fontSize: 16 }}>
          AgentKB
        </div>
        <Menu mode="inline" selectedKeys={[selectedKey]} openKeys={openKeys} onOpenChange={setOpenKeys} items={MENU_ITEMS} style={{ borderRight: 0 }} />
      </Sider>
      <Layout>
        <Header style={{ background: "#fff", padding: "0 24px", display: "flex", alignItems: "center", justifyContent: "space-between", borderBottom: "1px solid #f0f0f0" }}>
          <Typography.Text strong>AgentKB 招聘知识库平台</Typography.Text>
          <Dropdown
            menu={{
              items: [
                { key: "profile", icon: <EditOutlined />, label: "编辑资料", onClick: () => { setNickname(user?.nickname ?? ""); setEditOpen(true); } },
                { key: "logout", icon: <LogoutOutlined />, label: "退出登录", onClick: () => { logout(); navigate("/login"); } },
              ],
            }}
          >
            <div style={{ cursor: "pointer", display: "flex", alignItems: "center", gap: 8 }}>
              <Avatar size="small" icon={<UserOutlined />} />
              <span>{user?.nickname ?? user?.email ?? "用户"}</span>
            </div>
          </Dropdown>
        </Header>
        <Content style={{ padding: 24 }}>
          <Outlet />
        </Content>
      </Layout>
      <Modal title="编辑资料" open={editOpen} onCancel={() => setEditOpen(false)} onOk={doUpdateProfile} okText="保存" cancelText="取消">
        <Input data-testid="nickname-input" placeholder="昵称" value={nickname} onChange={(e) => setNickname(e.target.value)} maxLength={32} />
      </Modal>
    </Layout>
  );
}