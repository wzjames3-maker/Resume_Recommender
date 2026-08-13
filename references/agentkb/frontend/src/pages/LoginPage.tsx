import { useState } from "react";
import { useNavigate, Link } from "react-router-dom";
import { Alert, Button, Card, Form, Input, Typography } from "antd";
import { LockOutlined, MailOutlined } from "@ant-design/icons";
import { useAuthStore } from "../stores/authStore";

export default function LoginPage() {
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(false);
  const login = useAuthStore((s) => s.login);
  const nav = useNavigate();

  const onFinish = async (values: { email: string; password: string }) => {
    setError("");
    setLoading(true);
    try {
      await login(values.email, values.password);
      nav("/");
    } catch (err: any) {
      setError(err?.response?.data?.message ?? "邮箱或密码错误");
    } finally {
      setLoading(false);
    }
  };

  return (
    <div style={{ minHeight: "100vh", display: "flex", alignItems: "center", justifyContent: "center", background: "#f5f7fa" }}>
      <Card style={{ width: 400, boxShadow: "0 4px 16px rgba(0,0,0,0.08)" }}>
        <Typography.Title level={3} style={{ textAlign: "center", marginBottom: 4 }}>
          AgentKB
        </Typography.Title>
        <Typography.Paragraph type="secondary" style={{ textAlign: "center", marginBottom: 24 }}>
          简历智能解析与招聘知识库平台
        </Typography.Paragraph>
        {error && <Alert type="error" message={error} data-testid="error" style={{ marginBottom: 16 }} showIcon />}
        <Form onFinish={onFinish} size="large">
          <Form.Item name="email" rules={[{ required: true, message: "请输入邮箱" }]}>
            <Input data-testid="email" prefix={<MailOutlined />} placeholder="邮箱" />
          </Form.Item>
          <Form.Item name="password" rules={[{ required: true, message: "请输入密码" }]}>
            <Input.Password data-testid="password" prefix={<LockOutlined />} placeholder="密码" />
          </Form.Item>
          <Form.Item>
            <Button type="primary" htmlType="submit" block loading={loading} data-testid="submit">
              登录
            </Button>
          </Form.Item>
        </Form>
        <div style={{ textAlign: "center" }}>
          <Link to="/register">还没有账号？注册</Link>
        </div>
      </Card>
    </div>
  );
}