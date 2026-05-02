/**
 * Driver chat screen — WebSocket-backed thread view.
 *
 * Auth via `?token=` query param on the WS URL (see `src/api/chat.ts`).
 * The composer sends a `send` frame; incoming `message` frames append
 * to the visible list. Initial backlog comes from the REST list.
 */

import { Feather } from '@expo/vector-icons';
import { useLocalSearchParams, useRouter } from 'expo-router';
import { useEffect, useRef, useState } from 'react';
import {
  KeyboardAvoidingView,
  Platform,
  Pressable,
  ScrollView,
  StyleSheet,
  TextInput,
  View,
} from 'react-native';

import { useAuth } from '../../../../src/auth/store';
import { Glass } from '../../../../src/components/Glass';
import { IconButton } from '../../../../src/components/IconButton';
import { Loading } from '../../../../src/components/Empty';
import { Screen } from '../../../../src/components/Screen';
import { Text } from '../../../../src/components/Text';
import { useChat } from '../../../../src/lib/useChat';
import { timeOnly } from '../../../../src/lib/format';
import { useTheme } from '../../../../src/theme/ThemeProvider';

export default function ChatScreen() {
  const theme = useTheme();
  const router = useRouter();
  const me = useAuth((s) => s.user);
  const { threadId } = useLocalSearchParams<{ threadId?: string }>();
  const { messages, status, send } = useChat(threadId ?? null);
  const [text, setText] = useState('');
  const scrollRef = useRef<ScrollView | null>(null);

  useEffect(() => {
    // Auto-scroll on new message.
    requestAnimationFrame(() => scrollRef.current?.scrollToEnd({ animated: true }));
  }, [messages.length]);

  if (!threadId) {
    return (
      <Screen contentStyle={{ paddingHorizontal: 18 }}>
        <Loading />
      </Screen>
    );
  }

  const onSend = () => {
    const t = text.trim();
    if (!t) return;
    send(t);
    setText('');
  };

  return (
    <Screen scroll={false} edges={['top', 'bottom']}>
      <View style={[styles.header, { borderColor: theme.colors.stroke2 }]}>
        <IconButton onPress={() => router.back()}>
          <Feather name="arrow-left" size={18} color={theme.colors.text} />
        </IconButton>
        <View style={[styles.avatar, { backgroundColor: theme.colors.success }]}>
          <Text variant="body" weight="700" tone="inverse">
            A
          </Text>
        </View>
        <View style={{ flex: 1, minWidth: 0 }}>
          <View style={{ flexDirection: 'row', alignItems: 'center', gap: 6 }}>
            <Text variant="heading">Бизнес чат</Text>
            <Feather name="shield" size={13} color={theme.colors.accent2} />
          </View>
          <View style={{ flexDirection: 'row', alignItems: 'center', gap: 4 }}>
            <View
              style={{
                width: 6,
                height: 6,
                borderRadius: 3,
                backgroundColor:
                  status === 'open' ? theme.colors.success : theme.colors.warn,
              }}
            />
            <Text variant="caption" tone="tertiary">
              {status === 'open' ? 'Идэвхтэй' : status === 'connecting' ? 'Холбож байна…' : status === 'error' ? 'Алдаа' : 'Холбогдсонгүй'}
            </Text>
          </View>
        </View>
      </View>

      <ScrollView
        ref={scrollRef}
        style={{ flex: 1 }}
        contentContainerStyle={{ padding: 16, gap: 8 }}
        showsVerticalScrollIndicator={false}
      >
        {messages.length === 0 ? (
          <Text variant="caption" tone="tertiary" style={{ textAlign: 'center', marginTop: 24 }}>
            Анхны зурвасаа бичнэ үү
          </Text>
        ) : null}
        {messages.map((m) => {
          const mine = m.author_user_id && me?.id ? m.author_user_id === me.id : false;
          if (m.kind === 'system') {
            return (
              <Text
                key={m.id}
                variant="caption"
                tone="tertiary"
                style={{ alignSelf: 'center', marginVertical: 4 }}
              >
                {m.body}
              </Text>
            );
          }
          return (
            <View
              key={m.id}
              style={[styles.bubbleRow, { alignSelf: mine ? 'flex-end' : 'flex-start' }]}
            >
              {mine ? (
                <View style={[styles.bubbleMine, { backgroundColor: theme.colors.accent }]}>
                  <Text variant="body" tone="inverse">
                    {m.body}
                  </Text>
                </View>
              ) : (
                <Glass radius="md" style={styles.bubbleTheirs}>
                  <Text variant="body">{m.body}</Text>
                </Glass>
              )}
              <Text
                variant="caption"
                tone="tertiary"
                style={{ alignSelf: mine ? 'flex-end' : 'flex-start', marginTop: 3 }}
              >
                {timeOnly(m.created_at)}
              </Text>
            </View>
          );
        })}
      </ScrollView>

      <KeyboardAvoidingView behavior={Platform.OS === 'ios' ? 'padding' : undefined}>
        <View style={styles.composerRow}>
          <Glass radius="lg" style={{ flex: 1, paddingVertical: 4 }}>
            <TextInput
              value={text}
              onChangeText={setText}
              placeholder="Зурвас бичих…"
              placeholderTextColor={theme.colors.text3}
              style={[styles.input, { color: theme.colors.text }]}
              multiline
            />
          </Glass>
          <Pressable
            onPress={onSend}
            disabled={status !== 'open' || !text.trim()}
            style={({ pressed }) => [
              styles.sendBtn,
              {
                backgroundColor: theme.colors.accent,
                opacity: status === 'open' && text.trim() ? (pressed ? 0.8 : 1) : 0.4,
              },
            ]}
          >
            <Feather name="send" size={16} color="#fff" />
          </Pressable>
        </View>
      </KeyboardAvoidingView>
    </Screen>
  );
}

const styles = StyleSheet.create({
  header: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 10,
    paddingHorizontal: 16,
    paddingVertical: 10,
    borderBottomWidth: StyleSheet.hairlineWidth,
  },
  avatar: {
    width: 36,
    height: 36,
    borderRadius: 18,
    alignItems: 'center',
    justifyContent: 'center',
  },
  bubbleRow: { maxWidth: '78%' },
  bubbleMine: {
    paddingHorizontal: 14,
    paddingVertical: 10,
    borderRadius: 16,
    borderTopRightRadius: 4,
  },
  bubbleTheirs: { borderTopLeftRadius: 4 },
  composerRow: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 8,
    paddingHorizontal: 12,
    paddingTop: 8,
    paddingBottom: 12,
  },
  input: {
    fontSize: 14,
    paddingVertical: 6,
    paddingHorizontal: 10,
    minHeight: 32,
    maxHeight: 120,
  },
  sendBtn: {
    width: 40,
    height: 40,
    borderRadius: 20,
    alignItems: 'center',
    justifyContent: 'center',
  },
});
