import { client } from "./client";

export async function listConfigs(wsId: number) {
  return client.get(`/workspaces/${wsId}/model-configs`).then((r) => r.data.items);
}

export async function upsertConfig(wsId: number, body: { model_type: string; base_url: string; model_name: string; api_key: string }) {
  return client.post(`/workspaces/${wsId}/model-configs`, body).then((r) => r.data);
}

export async function testConfig(wsId: number, modelType: string) {
  return client.post(`/workspaces/${wsId}/model-configs/${modelType}/test`).then((r) => r.data);
}