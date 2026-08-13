import { useEffect, useState } from "react";
import { useParams, useSearchParams } from "react-router-dom";
import { Button, Card, Input, Popconfirm, Space, Tabs, Tag, Timeline, Typography, message } from "antd";
import {
  addNote, candidateAssignments, getCandidate, getTimeline, mergeCandidates, overrideField, purgeCandidate,
  restoreCandidate, softDelete,
} from "../api/candidates";
import * as wsApi from "../api/workspaces";

export default function CandidateDetailPage() {
  const { id } = useParams();
  const [searchParams] = useSearchParams();
  const [wsId, setWsId] = useState<number | null>(searchParams.get("ws") ? Number(searchParams.get("ws")) : null);
  const [view, setView] = useState<Record<string, unknown> | null>(null);
  const [ir, setIr] = useState("");
  const [suitableJobs, setSuitableJobs] = useState<Record<string, unknown>[]>([]);
  const [sourceChannel, setSourceChannel] = useState("");
  const [referrer, setReferrer] = useState("");
  const [timeline, setTimeline] = useState<Record<string, unknown>[]>([]);
  const [assignments, setAssignments] = useState<Record<string, unknown>[]>([]);
  const [mergeId, setMergeId] = useState("");
  const [fieldPath, setFieldPath] = useState("city");
  const [fieldValue, setFieldValue] = useState("");
  const [note, setNote] = useState("");
  const [error, setError] = useState("");

  const load = async (curWs: number) => {
    if (!id) return;
    try {
      const data = await getCandidate(curWs, Number(id));
      setView(data.candidate);
      setIr(data.ir ?? "");
      setSuitableJobs(data.suitable_jobs ?? []);
      setSourceChannel(data.source_channel ?? "");
      setReferrer(data.referrer ?? "");
      const tl = await getTimeline(curWs, Number(id));
      setTimeline(tl.items);
      const as = await candidateAssignments(curWs, Number(id));
      setAssignments(as.items);
      setError("");
    } catch {
      setError("候选人不存在或无权访问");
    }
  };

  useEffect(() => {
    if (wsId != null) {
      load(wsId);
      return;
    }
    wsApi.list().then((rows) => {
      if (rows.length > 0) {
        setWsId(rows[0].id);
        load(rows[0].id);
      }
    });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [id, wsId]);

  const applyOverride = async () => {
    if (wsId == null || !view) return;
    try {
      await overrideField(wsId, Number(id), {
        base_revision_id: view.latest_revision_id,
        field_path: fieldPath,
        action: "override",
        after_value: fieldValue,
      });
      message.success("字段已修正");
      await load(wsId);
    } catch {
      setError("修正失败（可能已被重新解析，请刷新）");
    }
  };

  const doDelete = async () => { if (wsId != null) { await softDelete(wsId, Number(id)); message.success("已软删除"); await load(wsId); } };
  const doRestore = async () => { if (wsId != null) { await restoreCandidate(wsId, Number(id)); message.success("已恢复"); await load(wsId); } };
  const doPurge = async () => { if (wsId != null) { await purgeCandidate(wsId, Number(id)); message.success("已硬删除"); await load(wsId); } };
  const doNote = async () => { if (wsId == null || !note) return; await addNote(wsId, Number(id), note); setNote(""); await load(wsId); };
  const doMerge = async () => {
    if (wsId == null || !view || !mergeId) return;
    try {
      await mergeCandidates(wsId, Number(id), Number(mergeId), Number(view.latest_revision_id));
      setMergeId("");
      await load(wsId);
    } catch {
      setError("合并失败");
    }
  };

  if (!view) return <div data-testid="error">{error || "加载中…"}</div>;

  const fields = view.fields as Record<string, unknown>;
  const profile = (view.profile ?? {}) as Record<string, unknown>;

  return (
    <div>
      <Typography.Title level={3} data-testid="name">候选人：{String(view.name ?? "")}</Typography.Title>
      {error && <Typography.Text type="danger" data-testid="error">{error}</Typography.Text>}
      <Space style={{ marginBottom: 16 }}>
        <Tag color="blue" data-testid="status">{String(view.status)}</Tag>
        <Typography.Text type="secondary">来源：{sourceChannel || "—"}{referrer ? ` · 内推人：${referrer}` : ""}</Typography.Text>
      </Space>
      <Tabs
        items={[
          {
            key: "fields",
            label: "结构化字段",
            children: <pre data-testid="fields">{JSON.stringify(fields, null, 2)}</pre>,
          },
          {
            key: "profile",
            label: "画像",
            children: <pre data-testid="profile">{JSON.stringify(profile, null, 2)}</pre>,
          },
          {
            key: "ir",
            label: "原文对照（IR）",
            children: <pre data-testid="ir">{ir || "无 IR"}</pre>,
          },
          {
            key: "timeline",
            label: "时间线",
            children: (
              <div>
                <Space style={{ marginBottom: 16 }}>
                  <Input data-testid="note" placeholder="添加备注" value={note} onChange={(e) => setNote(e.target.value)} style={{ width: 300 }} />
                  <Button data-testid="add-note" type="primary" onClick={doNote}>添加</Button>
                </Space>
                <Timeline
                  items={timeline.map((e) => ({ children: <span data-testid="event">{String(e.title)} ({String(e.created_at)})</span> }))}
                />
              </div>
            ),
          },
        ]}
      />
      <Card title="职位指派" style={{ marginBottom: 16 }}>
        {assignments.length === 0 ? <Typography.Text type="secondary" data-testid="assignment-empty">暂无指派</Typography.Text> : (
          <Space direction="vertical">
            {assignments.map((a) => (
              <div key={String(a.assignment_id)} data-testid="assignment">
                <a href={`/jobs/${a.job_id}?ws=${wsId}`} onClick={(e) => { e.preventDefault(); window.location.href = e.currentTarget.href; }}>{String(a.job_name)}</a>
                {" "}· {String(a.status)}{a.reject_reason ? ` · ${String(a.reject_reason)}` : ""}
              </div>
            ))}
          </Space>
        )}
      </Card>
      <Card title="TA 可能适合的在招职位" style={{ marginBottom: 16 }}>
        <Space direction="vertical">
          {suitableJobs.map((j) => (
            <div key={String(j.job_id)} data-testid="suitable-job">
              <a href={`/jobs/${j.job_id}?ws=${wsId}`} onClick={(e) => { e.preventDefault(); window.location.href = e.currentTarget.href; }}>{String(j.name)}</a>
              {" "}· {String(j.city ?? "—")}（命中：{Array.isArray(j.matched_conditions) ? j.matched_conditions.join("、") : ""}）
            </div>
          ))}
        </Space>
      </Card>
      <Card title="字段修正" style={{ marginBottom: 16 }}>
        <Space>
          <Input data-testid="field-path" value={fieldPath} onChange={(e) => setFieldPath(e.target.value)} style={{ width: 120 }} />
          <Input data-testid="field-value" value={fieldValue} onChange={(e) => setFieldValue(e.target.value)} placeholder="新值" style={{ width: 200 }} />
          <Button data-testid="apply" type="primary" onClick={applyOverride}>应用修正</Button>
        </Space>
      </Card>
      <Card title="生命周期" style={{ marginBottom: 16 }}>
        <Space>
          <Button data-testid="delete" danger onClick={doDelete}>软删除</Button>
          <Button data-testid="restore" onClick={doRestore}>恢复</Button>
          <Popconfirm title="确认硬删除？不可恢复" onConfirm={doPurge}>
            <Button data-testid="purge" danger onClick={() => {}}>硬删除</Button>
          </Popconfirm>
        </Space>
      </Card>
      <Card title="合并重复候选人">
        <Space>
          <Input data-testid="merge-id" placeholder="被合并候选人 ID" value={mergeId} onChange={(e) => setMergeId(e.target.value)} style={{ width: 200 }} />
          <Button data-testid="merge" onClick={doMerge}>合并到本候选人</Button>
        </Space>
      </Card>
    </div>
  );
}