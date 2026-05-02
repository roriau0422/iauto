/**
 * useChat(threadId) — live chat hook backed by `/v1/chat/ws`.
 *
 * Resolves an access token at mount, opens a WS, sends a `subscribe`
 * frame for the thread, then merges incoming `message` frames with the
 * paginated REST list. `send(text)` writes a `send` frame.
 *
 * Reconnect strategy: on close we wait an exponential backoff (1s, 2s,
 * 4s, capped at 8s) and retry while the thread is still mounted.
 */

import { useCallback, useEffect, useRef, useState } from 'react';

import { buildChatSocketUrl, listChatMessages } from '../api/chat';
import { loadTokens } from '../api/tokens';
import type { components } from '../../types/api';

export type ChatMessageOut = components['schemas']['ChatMessageOut'];

type WsFrame =
  | { type: 'message'; message: ChatMessageOut }
  | { type: 'error'; error_code: string; detail: string };

export type ChatState = {
  messages: ChatMessageOut[];
  status: 'connecting' | 'open' | 'closed' | 'error';
  error: string | null;
  send: (text: string) => void;
};

export function useChat(threadId: string | null): ChatState {
  const [messages, setMessages] = useState<ChatMessageOut[]>([]);
  const [status, setStatus] = useState<ChatState['status']>('connecting');
  const [error, setError] = useState<string | null>(null);
  const wsRef = useRef<WebSocket | null>(null);
  const cancelledRef = useRef(false);
  const retryRef = useRef(0);

  // Initial REST list — the WS only carries new frames.
  useEffect(() => {
    if (!threadId) return;
    let cancelled = false;
    listChatMessages(threadId, { limit: 50 })
      .then((resp) => {
        if (cancelled) return;
        // Backend returns newest-first, reverse for display oldest-first.
        setMessages([...resp.items].reverse());
      })
      .catch((e: unknown) => {
        if (cancelled) return;
        setError(e instanceof Error ? e.message : 'failed to load messages');
      });
    return () => {
      cancelled = true;
    };
  }, [threadId]);

  // Open WebSocket
  useEffect(() => {
    if (!threadId) return;
    cancelledRef.current = false;

    const connect = async (): Promise<void> => {
      if (cancelledRef.current) return;
      setStatus('connecting');
      const tokens = await loadTokens();
      if (!tokens?.access) {
        setStatus('error');
        setError('not authenticated');
        return;
      }
      const url = buildChatSocketUrl(tokens.access);
      const ws = new WebSocket(url);
      wsRef.current = ws;

      ws.onopen = () => {
        setStatus('open');
        retryRef.current = 0;
        ws.send(JSON.stringify({ type: 'subscribe', thread_id: threadId }));
      };

      ws.onmessage = (ev: WebSocketMessageEvent) => {
        try {
          const data = typeof ev.data === 'string' ? ev.data : '';
          if (!data) return;
          const parsed = JSON.parse(data) as WsFrame;
          if (parsed.type === 'message') {
            setMessages((cur) => [...cur, parsed.message]);
          } else if (parsed.type === 'error') {
            setError(parsed.detail);
          }
        } catch {
          // Ignore malformed frames.
        }
      };

      ws.onerror = () => {
        setStatus('error');
      };

      ws.onclose = () => {
        if (cancelledRef.current) return;
        setStatus('closed');
        retryRef.current = Math.min(retryRef.current + 1, 4);
        const delay = Math.min(1000 * 2 ** (retryRef.current - 1), 8000);
        setTimeout(() => {
          if (!cancelledRef.current) void connect();
        }, delay);
      };
    };

    void connect();

    return () => {
      cancelledRef.current = true;
      const ws = wsRef.current;
      if (ws && ws.readyState === WebSocket.OPEN) ws.close();
      wsRef.current = null;
    };
  }, [threadId]);

  const send = useCallback(
    (text: string) => {
      const ws = wsRef.current;
      if (!ws || ws.readyState !== WebSocket.OPEN || !threadId) return;
      ws.send(
        JSON.stringify({
          type: 'send',
          thread_id: threadId,
          kind: 'text',
          body: text,
        }),
      );
    },
    [threadId],
  );

  return { messages, status, error, send };
}
