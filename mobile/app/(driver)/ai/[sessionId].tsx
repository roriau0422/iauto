/**
 * AI Mechanic conversation thread.
 *
 * Posts text via `/v1/ai-mechanic/sessions/{id}/messages` and renders
 * the running message list. The four modality chips wire up the
 * backend's input forks:
 *
 *   - Зураг (visual)         → POST /visual         + image upload
 *   - Дуу хоолой (voice)      → POST /voice          + audio upload
 *   - Хөдөлгүүр (engine sound) → POST /engine-sound  + audio upload
 *   - Хийн шил (warning light) → POST /warning-light + image upload
 *
 * Image attachments use `expo-image-picker`; audio recordings use
 * `expo-av`'s `Audio.Recording` (iOS-style MP4 by default). Each
 * upload goes through the standard presign/PUT/confirm flow via
 * `uploadAsset()` and then posts the asset id to the matching
 * endpoint. While a request is in flight we render a transient
 * "Илгээж байна…" row in the conversation. After the response we
 * append a small chip showing the spend (sum of all *_micro_mnt
 * fields on the reply) for cost transparency.
 */

import { Feather, MaterialCommunityIcons } from '@expo/vector-icons';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { Audio } from 'expo-av';
import * as ImagePicker from 'expo-image-picker';
import { useLocalSearchParams, useRouter } from 'expo-router';
import { useEffect, useRef, useState } from 'react';
import {
  ActivityIndicator,
  Alert,
  KeyboardAvoidingView,
  Platform,
  Pressable,
  ScrollView,
  StyleSheet,
  TextInput,
  View,
} from 'react-native';

import {
  listMessages,
  postEngineSoundMessage,
  postTextMessage,
  postVisualMessage,
  postVoiceMessage,
  postWarningLightMessage,
} from '../../../src/api/aiMechanic';
import { uploadAsset } from '../../../src/api/media';
import { Chip } from '../../../src/components/Chip';
import { Glass } from '../../../src/components/Glass';
import { IconButton } from '../../../src/components/IconButton';
import { Loading } from '../../../src/components/Empty';
import { Screen } from '../../../src/components/Screen';
import { ScreenHeader } from '../../../src/components/ScreenHeader';
import { Text } from '../../../src/components/Text';
import { useTheme } from '../../../src/theme/ThemeProvider';
import type { components } from '../../../types/api';

type AssistantReplyOut = components['schemas']['AssistantReplyOut'];
type MultimodalReplyOut = components['schemas']['MultimodalReplyOut'];
type VoiceReplyOut = components['schemas']['VoiceReplyOut'];
type WarningLightReplyOut = components['schemas']['WarningLightReplyOut'];

type AnyReply =
  | AssistantReplyOut
  | MultimodalReplyOut
  | VoiceReplyOut
  | WarningLightReplyOut;

type Modality = 'text' | 'visual' | 'voice' | 'engine_sound' | 'warning_light';

const MODALITY_PROGRESS: Record<Modality, string> = {
  text: 'Илгээж байна…',
  visual: 'Зураг хуулж, оношилж байна…',
  voice: 'Дуу хоолойг хүлээн авч байна…',
  engine_sound: 'Хөдөлгүүрийн чимээг шинжилж байна…',
  warning_light: 'Хийн шилний дүрсийг таниж байна…',
};

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

  /** Banner for the most recent reply's estimated cost. Cleared on next send. */
  const [spendChip, setSpendChip] = useState<string | null>(null);
  /** Currently in-flight modality, drives the transient progress row. */
  const [pendingModality, setPendingModality] = useState<Modality | null>(null);
  /** Active audio recorder (voice + engine-sound). Set while recording. */
  const recordingRef = useRef<Audio.Recording | null>(null);
  const [recordingKind, setRecordingKind] = useState<'voice' | 'engine_sound' | null>(null);

  const refreshMessages = async () => {
    await qc.invalidateQueries({ queryKey: ['ai', 'session', sessionId, 'messages'] });
  };

  const sendText = useMutation({
    mutationFn: (content: string) => {
      if (!sessionId) throw new Error('missing session id');
      return postTextMessage(sessionId, { content });
    },
    onSuccess: async (out) => {
      setInput('');
      setSpendChip(formatSpend(out));
      await refreshMessages();
    },
    onError: () => Alert.alert('Алдаа', 'Зурвас илгээж чадсангүй.'),
  });

  const sendVisual = useMutation({
    mutationFn: async (vars: { mediaAssetId: string; prompt: string }) => {
      if (!sessionId) throw new Error('missing session id');
      return postVisualMessage(sessionId, {
        media_asset_id: vars.mediaAssetId,
        prompt: vars.prompt,
      });
    },
    onSuccess: async (out) => {
      setSpendChip(formatSpend(out));
      await refreshMessages();
    },
    onError: () => Alert.alert('Алдаа', 'Зураг илгээхэд алдаа гарлаа.'),
  });

  const sendVoice = useMutation({
    mutationFn: async (vars: { mediaAssetId: string }) => {
      if (!sessionId) throw new Error('missing session id');
      return postVoiceMessage(sessionId, { media_asset_id: vars.mediaAssetId });
    },
    onSuccess: async (out) => {
      setSpendChip(formatSpend(out));
      await refreshMessages();
    },
    onError: () => Alert.alert('Алдаа', 'Дуу хоолойг боловсруулж чадсангүй.'),
  });

  const sendEngineSound = useMutation({
    mutationFn: async (vars: { mediaAssetId: string }) => {
      if (!sessionId) throw new Error('missing session id');
      return postEngineSoundMessage(sessionId, { media_asset_id: vars.mediaAssetId });
    },
    onSuccess: async (out) => {
      setSpendChip(formatSpend(out));
      await refreshMessages();
    },
    onError: () => Alert.alert('Алдаа', 'Хөдөлгүүрийн чимээг боловсруулж чадсангүй.'),
  });

  const sendWarningLight = useMutation({
    mutationFn: async (vars: { mediaAssetId: string }) => {
      if (!sessionId) throw new Error('missing session id');
      return postWarningLightMessage(sessionId, { media_asset_id: vars.mediaAssetId });
    },
    onSuccess: async (out) => {
      setSpendChip(formatSpend(out));
      await refreshMessages();
    },
    onError: () => Alert.alert('Алдаа', 'Хийн шилний зургийг боловсруулж чадсангүй.'),
  });

  useEffect(() => {
    requestAnimationFrame(() => scrollRef.current?.scrollToEnd({ animated: true }));
  }, [messagesQ.data?.items.length, pendingModality]);

  useEffect(() => {
    return () => {
      // If the screen unmounts mid-recording, drop the recorder cleanly.
      if (recordingRef.current) {
        recordingRef.current.stopAndUnloadAsync().catch(() => undefined);
        recordingRef.current = null;
      }
    };
  }, []);

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
    setSpendChip(null);
    setPendingModality('text');
    sendText.mutate(t, { onSettled: () => setPendingModality(null) });
  };

  const pickAndUploadImage = async (kind: 'visual' | 'warning_light') => {
    const perm = await ImagePicker.requestMediaLibraryPermissionsAsync();
    if (!perm.granted) {
      Alert.alert('Зөвшөөрөл хэрэгтэй', 'Зураг сонгохын тулд галерейн эрх олгоно уу.');
      return null;
    }
    const result = await ImagePicker.launchImageLibraryAsync({
      mediaTypes: ['images'],
      quality: 0.85,
      allowsMultipleSelection: false,
    });
    if (result.canceled || result.assets.length === 0) return null;
    const asset = result.assets[0];
    const contentType = guessImageMime(asset.mimeType, asset.uri);
    // The visual endpoint accepts `part_search`, `review`, or `story`
    // purposes. We use `part_search` because the visual modality on
    // this screen is "what part is this / what's wrong here?". The
    // warning-light endpoint requires `warning_light`.
    const purpose: 'part_search' | 'warning_light' =
      kind === 'warning_light' ? 'warning_light' : 'part_search';
    const upload = await uploadAsset({
      uri: asset.uri,
      contentType,
      byteSize: asset.fileSize ?? estimateByteSize(asset.width, asset.height),
      purpose,
    }).catch(() => null);
    if (!upload) {
      Alert.alert('Алдаа', 'Зураг хуулж чадсангүй.');
      return null;
    }
    return upload.id;
  };

  const onVisual = async () => {
    setSpendChip(null);
    setPendingModality('visual');
    try {
      const mediaAssetId = await pickAndUploadImage('visual');
      if (!mediaAssetId) {
        setPendingModality(null);
        return;
      }
      const promptText = input.trim();
      sendVisual.mutate(
        {
          mediaAssetId,
          prompt: promptText.length > 0 ? promptText : 'Энэ зургийг тайлбарлаж өг',
        },
        {
          onSuccess: () => setInput(''),
          onSettled: () => setPendingModality(null),
        },
      );
    } catch {
      setPendingModality(null);
    }
  };

  const onWarningLight = async () => {
    setSpendChip(null);
    setPendingModality('warning_light');
    try {
      const mediaAssetId = await pickAndUploadImage('warning_light');
      if (!mediaAssetId) {
        setPendingModality(null);
        return;
      }
      sendWarningLight.mutate(
        { mediaAssetId },
        { onSettled: () => setPendingModality(null) },
      );
    } catch {
      setPendingModality(null);
    }
  };

  const startRecording = async (kind: 'voice' | 'engine_sound') => {
    if (recordingRef.current) return; // already recording
    try {
      const perm = await Audio.requestPermissionsAsync();
      if (!perm.granted) {
        Alert.alert('Зөвшөөрөл хэрэгтэй', 'Бичлэг хийхийн тулд микрофоны эрх олгоно уу.');
        return;
      }
      await Audio.setAudioModeAsync({ allowsRecordingIOS: true, playsInSilentModeIOS: true });
      const { recording } = await Audio.Recording.createAsync(
        Audio.RecordingOptionsPresets.HIGH_QUALITY,
      );
      recordingRef.current = recording;
      setRecordingKind(kind);
    } catch {
      Alert.alert('Алдаа', 'Бичлэг эхлүүлж чадсангүй.');
    }
  };

  const stopAndSendRecording = async () => {
    const rec = recordingRef.current;
    const kind = recordingKind;
    if (!rec || !kind) return;
    recordingRef.current = null;
    setRecordingKind(null);
    setSpendChip(null);
    setPendingModality(kind);
    try {
      await rec.stopAndUnloadAsync();
      await Audio.setAudioModeAsync({ allowsRecordingIOS: false });
      const uri = rec.getURI();
      if (!uri) {
        setPendingModality(null);
        Alert.alert('Алдаа', 'Бичлэгийн файл олдсонгүй.');
        return;
      }
      const status = await rec.getStatusAsync().catch(() => null);
      const durationMillis =
        status && 'durationMillis' in status && typeof status.durationMillis === 'number'
          ? status.durationMillis
          : 0;
      const byteSize = estimateAudioBytes(durationMillis);
      // HIGH_QUALITY preset writes `.m4a` (MPEG-4 AAC) on iOS/Android
      // and `audio/webm` on the web. The backend's media-upload enum
      // accepts both.
      const audioMime: 'audio/mp4' | 'audio/webm' =
        Platform.OS === 'web' ? 'audio/webm' : 'audio/mp4';
      const upload = await uploadAsset({
        uri,
        contentType: audioMime,
        byteSize,
        purpose: kind === 'voice' ? 'voice' : 'engine_sound',
      });
      if (kind === 'voice') {
        sendVoice.mutate(
          { mediaAssetId: upload.id },
          { onSettled: () => setPendingModality(null) },
        );
      } else {
        sendEngineSound.mutate(
          { mediaAssetId: upload.id },
          { onSettled: () => setPendingModality(null) },
        );
      }
    } catch {
      setPendingModality(null);
      Alert.alert('Алдаа', 'Бичлэг боловсруулахад алдаа гарлаа.');
    }
  };

  const cancelRecording = async () => {
    const rec = recordingRef.current;
    recordingRef.current = null;
    setRecordingKind(null);
    if (rec) {
      try {
        await rec.stopAndUnloadAsync();
        await Audio.setAudioModeAsync({ allowsRecordingIOS: false });
      } catch {
        // best effort
      }
    }
  };

  const onVoiceTap = () => {
    if (recordingKind === 'voice') {
      void stopAndSendRecording();
    } else if (recordingKind === 'engine_sound') {
      Alert.alert('Бичлэг идэвхтэй', 'Хөдөлгүүрийн чимээний бичлэгийг түр зогсоо.');
    } else {
      void startRecording('voice');
    }
  };

  const onEngineSoundTap = () => {
    if (recordingKind === 'engine_sound') {
      void stopAndSendRecording();
    } else if (recordingKind === 'voice') {
      Alert.alert('Бичлэг идэвхтэй', 'Дуу хоолойн бичлэгийг түр зогсоо.');
    } else {
      void startRecording('engine_sound');
    }
  };

  const isBusy = pendingModality != null || recordingKind != null;

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
                      UCar Механик
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
        {pendingModality ? (
          <Glass radius="lg" style={[styles.assistantBubble, { alignSelf: 'flex-start' }]}>
            <View style={{ flexDirection: 'row', alignItems: 'center', gap: 8 }}>
              <ActivityIndicator color={theme.colors.accent2} />
              <Text variant="caption" tone="secondary">
                {MODALITY_PROGRESS[pendingModality]}
              </Text>
            </View>
          </Glass>
        ) : null}
        {spendChip ? (
          <View style={{ alignSelf: 'flex-start' }}>
            <Chip label={spendChip} tone="neutral" />
          </View>
        ) : null}
      </ScrollView>

      <KeyboardAvoidingView behavior={Platform.OS === 'ios' ? 'padding' : undefined}>
        <View style={styles.composerWrap}>
          <View style={styles.modalityRow}>
            <ModalityChip
              icon={<Feather name="camera" size={14} color={theme.colors.accent2} />}
              label="Зураг"
              onPress={onVisual}
              disabled={isBusy && pendingModality !== 'visual'}
            />
            <ModalityChip
              icon={<Feather name="mic" size={14} color={theme.colors.accent2} />}
              label={recordingKind === 'voice' ? 'Зогсоох' : 'Дуу хоолой'}
              onPress={onVoiceTap}
              disabled={isBusy && recordingKind !== 'voice' && pendingModality !== 'voice'}
              active={recordingKind === 'voice'}
            />
            <ModalityChip
              icon={<MaterialCommunityIcons name="engine" size={14} color={theme.colors.accent2} />}
              label={recordingKind === 'engine_sound' ? 'Зогсоох' : 'Хөдөлгүүр'}
              onPress={onEngineSoundTap}
              disabled={
                isBusy && recordingKind !== 'engine_sound' && pendingModality !== 'engine_sound'
              }
              active={recordingKind === 'engine_sound'}
            />
            <ModalityChip
              icon={
                <MaterialCommunityIcons
                  name="alert-octagon-outline"
                  size={14}
                  color={theme.colors.accent2}
                />
              }
              label="Хийн шил"
              onPress={onWarningLight}
              disabled={isBusy && pendingModality !== 'warning_light'}
            />
            {recordingKind ? (
              <Pressable
                onPress={() => void cancelRecording()}
                style={[
                  styles.modBtn,
                  { backgroundColor: theme.colors.danger },
                ]}
              >
                <Feather name="x" size={14} color="#fff" />
                <Text variant="caption" weight="600" tone="inverse">
                  Цуцлах
                </Text>
              </Pressable>
            ) : null}
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
              disabled={!input.trim() || isBusy}
              style={({ pressed }) => [
                styles.sendBtn,
                {
                  backgroundColor: theme.colors.accent,
                  opacity: input.trim() && !isBusy ? (pressed ? 0.8 : 1) : 0.4,
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

function ModalityChip({
  icon,
  label,
  onPress,
  disabled,
  active,
}: {
  icon: React.ReactNode;
  label: string;
  onPress: () => void;
  disabled?: boolean;
  active?: boolean;
}) {
  const theme = useTheme();
  return (
    <Pressable
      onPress={onPress}
      disabled={disabled}
      style={[
        styles.modBtn,
        {
          backgroundColor: active ? theme.colors.accent : theme.colors.accentGlow,
          opacity: disabled ? 0.4 : 1,
        },
      ]}
    >
      {icon}
      <Text variant="caption" weight="600" tone={active ? 'inverse' : 'accent'}>
        {label}
      </Text>
    </Pressable>
  );
}

/**
 * Sum every `*_micro_mnt` field on a reply and format as MNT. The
 * backend names vary by reply shape (agent_micro_mnt,
 * transcription_micro_mnt, multimodal_micro_mnt, classifier_micro_mnt,
 * est_cost_micro_mnt) so we walk the row and add anything that ends
 * in `_micro_mnt`.
 */
function formatSpend(out: AnyReply): string {
  let totalMicro = 0;
  for (const [k, v] of Object.entries(out as Record<string, unknown>)) {
    if (k.endsWith('_micro_mnt') && typeof v === 'number') {
      totalMicro += v;
    }
  }
  const mntValue = totalMicro / 1_000_000;
  if (mntValue < 1) {
    return `Үнэ: ~${mntValue.toFixed(3)}₮`;
  }
  return `Үнэ: ~${mntValue.toFixed(1)}₮`;
}

function guessImageMime(
  declared: string | null | undefined,
  uri: string,
): 'image/jpeg' | 'image/png' | 'image/webp' {
  const lower = (declared ?? '').toLowerCase();
  if (lower === 'image/png') return 'image/png';
  if (lower === 'image/webp') return 'image/webp';
  if (lower === 'image/jpeg' || lower === 'image/jpg') return 'image/jpeg';
  const ext = uri.split('?')[0].split('.').pop()?.toLowerCase();
  if (ext === 'png') return 'image/png';
  if (ext === 'webp') return 'image/webp';
  return 'image/jpeg';
}

function estimateByteSize(width: number | undefined, height: number | undefined): number {
  if (width == null || height == null || width <= 0 || height <= 0) return 256 * 1024;
  return Math.max(64 * 1024, Math.floor(width * height * 0.5));
}

/**
 * Lower-bound estimate for AAC audio at ~128 kbps. Used when the
 * recorder API doesn't expose the final file size before upload.
 */
function estimateAudioBytes(durationMillis: number): number {
  const seconds = Math.max(1, Math.ceil(durationMillis / 1000));
  return Math.max(16 * 1024, seconds * 16 * 1024);
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
