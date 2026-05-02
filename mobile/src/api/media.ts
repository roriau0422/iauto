/**
 * `/v1/media/*` — presign + confirm upload flow.
 *
 * Backend issues a presigned PUT URL; the client uploads bytes directly
 * to S3-compatible object storage with the headers the server prescribes,
 * then calls `confirm()` so the row flips from `pending` → `active`.
 */

import { apiClient } from './client';
import type { components } from '../../types/api';

type MediaUploadCreateIn = components['schemas']['MediaUploadCreateIn'];
type MediaUploadCreateOut = components['schemas']['MediaUploadCreateOut'];
type MediaAssetOut = components['schemas']['MediaAssetOut'];
type MediaAssetDownloadOut = components['schemas']['MediaAssetDownloadOut'];

export async function createUpload(
  body: MediaUploadCreateIn,
): Promise<MediaUploadCreateOut> {
  const r = await apiClient.post<MediaUploadCreateOut>('/v1/media/uploads', body);
  return r.data;
}

export async function confirmUpload(assetId: string): Promise<MediaAssetOut> {
  const r = await apiClient.post<MediaAssetOut>(
    `/v1/media/uploads/${assetId}/confirm`,
  );
  return r.data;
}

export async function getAssetDownload(assetId: string): Promise<MediaAssetDownloadOut> {
  const r = await apiClient.get<MediaAssetDownloadOut>(`/v1/media/assets/${assetId}`);
  return r.data;
}

/**
 * High-level "upload bytes" helper. Caller hands us `{uri, contentType,
 * byteSize, purpose}`. We:
 *   1. ask the backend for a presigned URL,
 *   2. PUT the bytes directly to that URL with the prescribed headers,
 *   3. confirm the upload, returning the active asset row.
 */
export async function uploadAsset(opts: {
  uri: string;
  contentType: MediaUploadCreateIn['content_type'];
  byteSize: number;
  purpose: MediaUploadCreateIn['purpose'];
}): Promise<MediaAssetOut> {
  const presign = await createUpload({
    byte_size: opts.byteSize,
    content_type: opts.contentType,
    purpose: opts.purpose,
  });
  const fileResp = await fetch(opts.uri);
  const blob = await fileResp.blob();
  const putResp = await fetch(presign.upload_url, {
    method: presign.method,
    headers: presign.headers,
    body: blob,
  });
  if (!putResp.ok) {
    throw new Error(`PUT to object storage failed: ${putResp.status}`);
  }
  return confirmUpload(presign.asset_id);
}
