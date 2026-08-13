import { useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { Alert, Button, Card, Form, Input, Typography } from "antd";
import { LockOutlined, MailOutlined, UserOutlined } from "@ant-design/icons";
import * as authApi from "../api/auth";

export default function RegisterPage() {
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(false);
  const nav = useNavigate();

  const onFinish = async (values: { email: string; password: string; nickname: string }) => {
    setError("");
    setLoading(true);
    try {
      await authApi.register(values.email, values.password, values.nickname);
      nav("/login");
    } catch (err: any) {
      setError(err?.response?.data?.message ?? "注册失败，请检查输入");
    } finally {
      setLoading(false);
    }
  };

  return (
    <div style={{ minHeight: "100vh", display: "flex", alignItems: "center", justifyContent: "center", background: "#f5f7fa" }}>
      <Card style={{ width: 400, boxShadow: "0 4px 16px rgba(0,0,0,0.08)" }}>
        <Typography.Title level={3} style={{ textAlign: "center", marginBottom: 24 }}>
          注册 AgentKB
        </Typography.Title>
        {error && <Alert type="error" message={error} data-testid="error" style={{ marginBottom: 16 }} showIcon />}
        <Form onFinish={onFinish} size="large">
          <Form.Item name="email" rules={[{ required: true, type: "email", message: "请输入有效邮箱" }]}>
            <Input data-testid="email" prefix={<MailOutlined />} placeholder="邮箱" />
          </Form.Item>
          <Form.Item name="nickname" rules={[{ required: true, message: "请输入昵称" }]}>
            <Input data-testid="nickname" prefix={<UserOutlined />} placeholder="昵称" />
          </Form.Item>
          <Form.Item name="password" rules={[{ required: true, min: 8, message: "密码至少 8 位" }]}>
            <Input.Password data-testid="password" prefix={<LockOutlined />} placeholder="密码（至少 8 位）" />
          </Form.Item>
          <Form.Item>
            <Button type="primary" htmlType="submit" block loading={loading} data-testid="submit">
              注册
            </Button>
          </Form.Item>
        </Form>
        <div style={{ textAlign: "center" }}>
          <Link to="/login">已有账号？返回登录</Link>
        </div>
      </Card>
    </div>
  );
}