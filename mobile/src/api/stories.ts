/**
 * `/v1/story/*` — feed, post, like, comment.
 *
 * Driver-authored stories are NOT yet supported by the backend; phase 1
 * only exposes business-authored posts. The mobile UI surfaces a "Phase
 * 2" disclosure for that gap rather than mocking driver posts.
 */

import { apiClient } from './client';
import type { components } from '../../types/api';

type StoryFeedOut = components['schemas']['StoryFeedOut'];
type StoryPostCreateIn = components['schemas']['StoryPostCreateIn'];
type StoryPostOut = components['schemas']['StoryPostOut'];
type StoryLikeOut = components['schemas']['StoryLikeOut'];
type StoryUnlikeOut = components['schemas']['StoryUnlikeOut'];
type StoryCommentCreateIn = components['schemas']['StoryCommentCreateIn'];
type StoryCommentOut = components['schemas']['StoryCommentOut'];
type StoryCommentListOut = components['schemas']['StoryCommentListOut'];

export async function getFeed(opts?: {
  limit?: number;
  before_id?: string | null;
}): Promise<StoryFeedOut> {
  const r = await apiClient.get<StoryFeedOut>('/v1/story/feed', { params: opts });
  return r.data;
}

export async function publishPost(body: StoryPostCreateIn): Promise<StoryPostOut> {
  const r = await apiClient.post<StoryPostOut>('/v1/story/posts', body);
  return r.data;
}

export async function getPost(postId: string): Promise<StoryPostOut> {
  const r = await apiClient.get<StoryPostOut>(`/v1/story/posts/${postId}`);
  return r.data;
}

export async function likePost(postId: string): Promise<StoryLikeOut> {
  const r = await apiClient.post<StoryLikeOut>(`/v1/story/posts/${postId}/like`);
  return r.data;
}

export async function unlikePost(postId: string): Promise<StoryUnlikeOut> {
  const r = await apiClient.delete<StoryUnlikeOut>(`/v1/story/posts/${postId}/like`);
  return r.data;
}

export async function listComments(
  postId: string,
  opts?: { limit?: number; before_id?: string | null },
): Promise<StoryCommentListOut> {
  const r = await apiClient.get<StoryCommentListOut>(
    `/v1/story/posts/${postId}/comments`,
    { params: opts },
  );
  return r.data;
}

export async function addComment(
  postId: string,
  body: StoryCommentCreateIn,
): Promise<StoryCommentOut> {
  const r = await apiClient.post<StoryCommentOut>(
    `/v1/story/posts/${postId}/comments`,
    body,
  );
  return r.data;
}
