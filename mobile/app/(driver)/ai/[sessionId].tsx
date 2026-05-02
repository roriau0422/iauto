/**
 * AI Mechanic conversation thread.
 *
 * Posts text via `/v1/ai-mechanic/sessions/{id}/messages` and renders
 * the running message list. The other multimodal forks (voice / visual
 * / engine sound / warning light) are exposed as composer chips that
 * trigger media-picker flows; each path uploads to S3 via the media
 * presign endpoint and then posts the asset id to its respective AI
 * endpoint. The minimum-viable surface here is text — multimodal
 * uploads land later in the same screen without a redesign.
 */

import { Feather, MaterialCommunityIcons } from '@expo/vector-icons';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { useLocalSearchParams, useRouter } from 'expo-router';
import { useEffect, useRef, useState } from 'react';
import {
  ActivityIndicator,
  KeyboardAvoidingView,
  Platform,
  Pressable,
  ScrollView,
  StyleSheet,
  TextInput,
  View,
} from 'react-native';

import { listMessages, postTextMessage } from '../../../src/api/aiMechanic';
import { Chip } from '../../../src/components/Chip';
import { Glass } from '../../../src/components/Glass';
import { IconButton } from '../../../src/components/IconButton';
import { Loading } from '../../../src/components/Empty';
import { Screen } from '../../../src/components/Screen';
import { ScreenHeader } from '../../../src/components/ScreenHeader';
import { Text } from '../../../src/components/Text';
import { useTheme } from '../../../src/theme/ThemeProvider';

export default function AiSessionThread() {
  const theme = useTheme();
  const router = useRouter();
  const qc = useQueryClient();
  const { sessionId } = useLocalSearchParams<{ sessionId?: string }>();
  const messagesQ = useQuery({
    queryKey: ['ai', 'session', sessionId, 'messages'],
    queryFn: () => {
      if (!sessionId) throw new Error('missing session id');
      return listMessages(sessionId);
    },
    enabled: !!sessionId,
  });
  const [input, setInput] = useState('');
  const scrollRef = useRef<ScrollView | null>(null);

  const sendText = useMutation({
    mutationFn: (content: string) => {
      if (!sessionId) throw new Error('missing session id');
      return postTextMessage(sessionId, { content });
    },
    onSuccess: () => {
      setInput('');
      void qc.invalidateQueries({ queryKey: ['ai', 'session', sessionId, 'messages'] });
    },
  });

  useEffect(() => {
    requestAnimationFrame(() => scrollRef.current?.scrollToEnd({ animated: true }));
  }, [messagesQ.data?.items.length]);

  if (!sessionId || messagesQ.isLoading) {
    return (
      <Screen contentStyle={{ paddingHorizontal: 18 }}>
        <Loading />
      </Screen>
    );
  }

  const messages = messagesQ.data?.items ?? [];

  const onSend = () => {
    const t = input.trim();
    if (!t) return;
    sendText.mutate(t);
  };

  return (
    <Screen scroll={false} edges={['top', 'bottom']}>
      <ScreenHeader
        sub="iAUTO МЕХАНИК"
        title="Оношилгоо"
        left={
          <IconButton onPress={() => router.back()}>
            <Feather name="arrow-left" size={18} color={theme.colors.text} />
          </IconButton>
        }
        right={<Chip label="Pro" tone="accent" />}
      />

      <ScrollView
        ref={scrollRef}
        style={{ flex: 1 }}
        contentContainerStyle={{ paddingHorizontal: 18, paddingBottom: 16, gap: 10 }}
        showsVerticalScrollIndicator={false}
      >
        {messages.length === 0 ? (
          <Glass radius="lg" style={{ marginTop: 18 }}>
            <Text variant="heading">Юу болж байна вэ?</Text>
            <Text variant="caption" tone="tertiary" style={{ marginTop: 6, lineHeight: 18 }}>
              Машиныхаа байдал, гарч буй чимээ, гэрэл, шахалт, эсвэл тогтмол гарах асуудлаа
              бичээд илгээнэ үү. Дараа нь дуу хоолой, зураг, хөдөлгүүрийн чимээгээр нөхөж
              болно.
            </Text>
          </Glass>
        ) : null}
        {messages.map((m) => {
          const mine = m.role === 'user';
          return (
            <View
              key={m.id}
              style={{
                alignSelf: mine ? 'flex-end' : 'flex-start',
                maxWidth: '92%',
              }}
            >
              {mine ? (
                <View
                  style={[
                    styles.bubbleMine,
                    { backgroundColor: theme.colors.accent },
                  ]}
                >
                  <Text variant="body" tone="inverse" style={{ lineHeight: 20 }}>
                    {m.content}
                  </Text>
                </View>
              ) : (
                <Glass radius="lg" style={styles.assistantBubble}>
                  <View style={styles.assistantHead}>
                    <View style={[styles.aiBadge, { backgroundColor: theme.colors.accent }]}>
                      <MaterialCommunityIcons name="creation" size={14} color="#fff" />
                    </View>
                    <Text variant="caption" weight="700">
                      iAuto Механик
                    </Text>
                  </View>
                  <Text variant="body" style={{ marginTop: 6, lineHeight: 20 }}>
                    {m.content}
                  </Text>
                </Glass>
              )}
            </View>
          );
        })}
        {sendText.isPending ? (
          <Glass radius="lg" style={[styles.assistantBubble, { alignSelf: 'flex-start' }]}>
            <ActivityIndicator color={theme.colors.accent2} />
          </Glass>
        ) : null}
      </ScrollView>

      <KeyboardAvoidingView behavior={Platform.OS === 'ios' ? 'padding' : undefined}>
        <View style={styles.composerWrap}>
          <View style={styles.modalityRow}>
            <Pressable
              style={[styles.modBtn, { backgroundColor: theme.colors.accentGlow }]}
              onPress={() => null}
            >
              <Feather name="camera" size={14} color={theme.colors.accent2} />
              <Text variant="caption" weight="600" tone="accent">
                Зураг
              </Text>
            </Pressable>
            <Pressable
              style={[styles.modBtn, { backgroundColor: theme.colors.accentGlow }]}
              onPress={() => null}
            >
              <Feather name="mic" size={14} color={theme.colors.accent2} />
              <Text variant="caption" weight="600" tone="accent">
                Дуу хоолой
              </Text>
            </Pressable>
            <Pressable
              style={[styles.modBtn, { backgroundColor: theme.colors.accentGlow }]}
              onPress={() => null}
            >
              <MaterialCommunityIcons name="engine" size={14} color={theme.colors.accent2} />
              <Text variant="caption" weight="600" tone="accent">
                Хөдөлгүүр
              </Text>
            </Pressable>
            <Pressable
              style={[styles.modBtn, { backgroundColor: theme.colors.accentGlow }]}
              onPress={() => null}
            >
              <MaterialCommunityIcons name="alert-octagon-outline" size={14} color={theme.colors.accent2} />
              <Text variant="caption" weight="600" tone="accent">
                Хийн шил
              </Text>
            </Pressable>
          </View>
          <View style={styles.composer}>
            <Glass radius="lg" style={{ flex: 1, paddingVertical: 4 }}>
              <TextInput
                value={input}
                onChangeText={setInput}
                placeholder="Асуултаа бичнэ үү…"
                placeholderTextColor={theme.colors.text3}
                style={[styles.input, { color: theme.colors.text }]}
                multiline
              />
            </Glass>
            <Pressable
              onPress={onSend}
              disabled={!input.trim() || sendText.isPending}
              style={({ pressed }) => [
                styles.sendBtn,
                {
                  backgroundColor: theme.colors.accent,
                  opacity: input.trim() && !sendText.isPending ? (pressed ? 0.8 : 1) : 0.4,
                },
              ]}
            >
              <Feather name="send" size={16} color="#fff" />
            </Pressable>
          </View>
        </View>
      </KeyboardAvoidingView>
    </Screen>
  );
}

const styles = StyleSheet.create({
  bubbleMine: {
    paddingHorizontal: 14,
    paddingVertical: 10,
    borderRadius: 16,
    borderTopRightRadius: 4,
  },
  assistantBubble: { borderTopLeftRadius: 4, maxWidth: '92%' },
  assistantHead: { flexDirection: 'row', alignItems: 'center', gap: 8 },
  aiBadge: {
    width: 26,
    height: 26,
    borderRadius: 8,
    alignItems: 'center',
    justifyContent: 'center',
  },
  composerWrap: { paddingHorizontal: 12, paddingTop: 8, paddingBottom: 12, gap: 8 },
  modalityRow: { flexDirection: 'row', flexWrap: 'wrap', gap: 6 },
  modBtn: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 5,
    paddingHorizontal: 10,
    paddingVertical: 6,
    borderRadius: 9999,
  },
  composer: { flexDirection: 'row', alignItems: 'center', gap: 8 },
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
