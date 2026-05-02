/**
 * Stories feed — driver POV.
 *
 * Both driver- and business-authored posts ride the same feed; the
 * backend stamps each row with `author_kind` + nullable `tenant_id`
 * and we render a small "БИЗНЕС" chip on tenant rows. The composer
 * at the top issues a `publishPost` call which the backend routes to
 * the right `author_kind` based on the caller's user role — drivers
 * get drafts published as personal posts, businesses get them
 * published as tenant posts.
 *
 * Image attachments go through the standard presign/PUT/confirm flow
 * via `uploadAsset()`. Multiple images are allowed (each becomes a
 * `media_asset_ids[i]` on the post body).
 */

import { Feather } from '@expo/vector-icons';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import * as ImagePicker from 'expo-image-picker';
import { useState } from 'react';
import {
  Alert,
  Image,
  Pressable,
  ScrollView,
  StyleSheet,
  TextInput,
  View,
} from 'react-native';

import { uploadAsset } from '../../src/api/media';
import { getFeed, publishPost } from '../../src/api/stories';
import { useAuth } from '../../src/auth/store';
import { Button } from '../../src/components/Button';
import { Chip } from '../../src/components/Chip';
import { Empty, Loading } from '../../src/components/Empty';
import { Glass } from '../../src/components/Glass';
import { IconButton } from '../../src/components/IconButton';
import { Screen } from '../../src/components/Screen';
import { ScreenHeader } from '../../src/components/ScreenHeader';
import { Text } from '../../src/components/Text';
import { relativeMn } from '../../src/lib/format';
import { useTheme } from '../../src/theme/ThemeProvider';
import type { components } from '../../types/api';

type StoryPostOut = components['schemas']['StoryPostOut'];

type StagedImage = {
  uri: string;
  contentType: 'image/jpeg' | 'image/png' | 'image/webp';
  byteSize: number;
};

export default function StoriesScreen() {
  const theme = useTheme();
  const qc = useQueryClient();
  const me = useAuth((s) => s.user);
  const feedQ = useQuery({ queryKey: ['stories', 'feed'], queryFn: () => getFeed({ limit: 20 }) });
  const items = (feedQ.data?.items ?? []) as StoryPostOut[];

  const [body, setBody] = useState('');
  const [staged, setStaged] = useState<StagedImage[]>([]);
  const [composerOpen, setComposerOpen] = useState(false);

  const postMu = useMutation({
    mutationFn: async (vars: { body: string; mediaIds: string[] }) => {
      return publishPost({ body: vars.body, media_asset_ids: vars.mediaIds });
    },
    onSuccess: async () => {
      setBody('');
      setStaged([]);
      setComposerOpen(false);
      await qc.invalidateQueries({ queryKey: ['stories'] });
    },
    onError: () => {
      Alert.alert('Алдаа', 'Нийтлэлийг илгээж чадсангүй. Дахин оролдоно уу.');
    },
  });

  const onPickImage = async () => {
    const perm = await ImagePicker.requestMediaLibraryPermissionsAsync();
    if (!perm.granted) {
      Alert.alert('Зөвшөөрөл хэрэгтэй', 'Зураг сонгохын тулд галерейн эрх олгоно уу.');
      return;
    }
    const result = await ImagePicker.launchImageLibraryAsync({
      mediaTypes: ['images'],
      quality: 0.85,
      allowsMultipleSelection: false,
      base64: false,
    });
    if (result.canceled || result.assets.length === 0) return;
    const asset = result.assets[0];
    const contentType = guessImageMime(asset.mimeType, asset.uri);
    setStaged((prev) => [
      ...prev,
      {
        uri: asset.uri,
        contentType,
        byteSize: asset.fileSize ?? estimateByteSize(asset.width, asset.height),
      },
    ]);
  };

  const onSend = async () => {
    const text = body.trim();
    if (!text && staged.length === 0) return;
    try {
      const mediaIds: string[] = [];
      for (const img of staged) {
        const asset = await uploadAsset({
          uri: img.uri,
          contentType: img.contentType,
          byteSize: img.byteSize,
          purpose: 'story',
        });
        mediaIds.push(asset.id);
      }
      postMu.mutate({ body: text, mediaIds });
    } catch {
      Alert.alert('Алдаа', 'Зураг хуулахад алдаа гарлаа.');
    }
  };

  return (
    <Screen scroll>
      <ScreenHeader
        sub="МЭДЭЭНИЙ СУВАГ"
        title="Сошиал"
        right={
          <IconButton onPress={() => setComposerOpen((v) => !v)} active={composerOpen}>
            <Feather name="plus" size={18} color={theme.colors.text} />
          </IconButton>
        }
      />

      <View style={{ paddingHorizontal: 18 }}>
        <ScrollView
          horizontal
          showsHorizontalScrollIndicator={false}
          contentContainerStyle={{ gap: 10, paddingVertical: 4 }}
        >
          <Pressable onPress={() => setComposerOpen(true)} style={{ alignItems: 'center', width: 64 }}>
            <View
              style={[
                styles.addRing,
                { borderColor: theme.colors.stroke },
              ]}
            >
              <Feather name="plus" size={20} color={theme.colors.text2} />
            </View>
            <Text variant="caption" tone="tertiary" style={{ marginTop: 5 }}>
              Нэмэх
            </Text>
          </Pressable>
          {items.slice(0, 8).map((p) => (
            <View key={p.id} style={{ alignItems: 'center', width: 64 }}>
              <View
                style={[
                  styles.dot,
                  {
                    backgroundColor:
                      p.author_kind === 'business' ? theme.colors.accent2 : theme.colors.accent,
                    borderColor: theme.colors.bg1,
                  },
                ]}
              >
                <Text variant="body" weight="700" tone="inverse">
                  {p.body[0]?.toUpperCase() ?? '·'}
                </Text>
              </View>
              <Text
                variant="caption"
                tone="tertiary"
                numberOfLines={1}
                style={{ marginTop: 5, maxWidth: 64 }}
              >
                {relativeMn(p.created_at)}
              </Text>
            </View>
          ))}
        </ScrollView>

        {composerOpen ? (
          <Glass radius="md" style={{ marginTop: 12 }}>
            <Text variant="eyebrow" tone="tertiary">
              ШИНЭ НИЙТЛЭЛ
            </Text>
            <TextInput
              value={body}
              onChangeText={setBody}
              placeholder="Юу шинэ юм бэ?"
              placeholderTextColor={theme.colors.text3}
              style={[
                styles.composerInput,
                { color: theme.colors.text, borderColor: theme.colors.stroke2 },
              ]}
              multiline
            />
            {staged.length > 0 ? (
              <ScrollView
                horizontal
                showsHorizontalScrollIndicator={false}
                contentContainerStyle={{ gap: 8, paddingTop: 10 }}
              >
                {staged.map((s, i) => (
                  <View key={`${s.uri}-${i}`} style={styles.thumbWrap}>
                    <Image source={{ uri: s.uri }} style={styles.thumb} />
                    <Pressable
                      onPress={() => setStaged((prev) => prev.filter((_, j) => j !== i))}
                      style={[styles.thumbX, { backgroundColor: theme.colors.danger }]}
                    >
                      <Feather name="x" size={12} color="#fff" />
                    </Pressable>
                  </View>
                ))}
              </ScrollView>
            ) : null}
            <View style={{ flexDirection: 'row', alignItems: 'center', gap: 8, marginTop: 10 }}>
              <IconButton onPress={onPickImage} size={36}>
                <Feather name="image" size={16} color={theme.colors.text2} />
              </IconButton>
              <View style={{ flex: 1 }} />
              <Button
                label="Илгээх"
                size="sm"
                onPress={onSend}
                loading={postMu.isPending}
                disabled={postMu.isPending || (!body.trim() && staged.length === 0)}
              />
            </View>
          </Glass>
        ) : null}

        {feedQ.isLoading ? (
          <Loading />
        ) : items.length === 0 ? (
          <Empty
            title="Шинэ нийтлэл алга"
            sub="Анхны нийтлэлээ нэмж эхэл — эсвэл бизнесүүдийн зар, шинэ бараа удахгүй харагдана."
          />
        ) : (
          <View style={{ gap: 12, marginTop: 14 }}>
            {items.map((p) => (
              <FeedCard key={p.id} post={p} myUserId={me?.id ?? null} />
            ))}
          </View>
        )}
      </View>
    </Screen>
  );
}

function FeedCard({
  post,
  myUserId,
}: {
  post: StoryPostOut;
  myUserId: string | null;
}) {
  const theme = useTheme();
  const isBusiness = post.author_kind === 'business';
  const isMine = myUserId != null && post.author_user_id === myUserId;

  const headerName = isBusiness ? 'Бизнес түнш' : isMine ? 'Та' : 'Жолооч';

  return (
    <Glass radius="lg">
      <View style={{ flexDirection: 'row', alignItems: 'center', gap: 10 }}>
        <View
          style={[
            styles.feedAvatar,
            {
              backgroundColor: isBusiness ? theme.colors.accent2 : theme.colors.accent,
            },
          ]}
        >
          <Text variant="body" weight="700" tone="inverse">
            {(headerName[0] ?? 'i').toUpperCase()}
          </Text>
        </View>
        <View style={{ flex: 1, minWidth: 0 }}>
          <View style={{ flexDirection: 'row', alignItems: 'center', gap: 5 }}>
            <Text variant="body" weight="700">
              {headerName}
            </Text>
            {isBusiness ? (
              <Chip label="БИЗНЕС" tone="accent" />
            ) : (
              <Feather name="user" size={12} color={theme.colors.text3} />
            )}
          </View>
          <Text variant="caption" tone="tertiary">
            {relativeMn(post.created_at)}
          </Text>
        </View>
        {/* Sponsored chip is reserved for ad placements; story posts never set it. */}
      </View>

      <View style={[styles.feedHero, { backgroundColor: theme.colors.surface2 }]}>
        <Text variant="title" tone="primary" weight="700" style={{ color: '#fff' }}>
          {post.body.slice(0, 80)}
        </Text>
      </View>

      <View
        style={{
          flexDirection: 'row',
          alignItems: 'center',
          gap: 18,
          marginTop: 10,
        }}
      >
        <View style={styles.actionPill}>
          <Feather name="heart" size={16} color={theme.colors.text2} />
          <Text variant="caption" weight="500" tone="secondary">
            {post.like_count}
          </Text>
        </View>
        <View style={styles.actionPill}>
          <Feather name="message-circle" size={16} color={theme.colors.text2} />
          <Text variant="caption" weight="500" tone="secondary">
            {post.comment_count}
          </Text>
        </View>
        <View style={{ flex: 1 }} />
        <Feather name="bookmark" size={16} color={theme.colors.text3} />
      </View>
    </Glass>
  );
}

function guessImageMime(
  declared: string | null | undefined,
  uri: string,
): 'image/jpeg' | 'image/png' | 'image/webp' {
  const lower = (declared ?? '').toLowerCase();
  if (lower === 'image/png') return 'image/png';
  if (lower === 'image/webp') return 'image/webp';
  if (lower === 'image/jpeg' || lower === 'image/jpg') return 'image/jpeg';
  // Fallback to extension sniffing — `mimeType` isn't always populated
  // by `expo-image-picker`, and the backend's MediaUploadCreateIn has
  // a closed enum we have to satisfy.
  const ext = uri.split('?')[0].split('.').pop()?.toLowerCase();
  if (ext === 'png') return 'image/png';
  if (ext === 'webp') return 'image/webp';
  return 'image/jpeg';
}

/**
 * Best-effort lower-bound for image byte sizes when `expo-image-picker`
 * does not return a `fileSize`. Uses the pixel area as a proxy at a
 * conservative byte-per-pixel rate so the presign endpoint accepts
 * the upload — the actual PUT carries the true size in the
 * Content-Length header anyway.
 */
function estimateByteSize(width: number | undefined, height: number | undefined): number {
  if (width == null || height == null || width <= 0 || height <= 0) return 256 * 1024;
  return Math.max(64 * 1024, Math.floor(width * height * 0.5));
}

const styles = StyleSheet.create({
  addRing: {
    width: 60,
    height: 60,
    borderRadius: 30,
    borderWidth: 1.5,
    borderStyle: 'dashed',
    alignItems: 'center',
    justifyContent: 'center',
  },
  dot: {
    width: 60,
    height: 60,
    borderRadius: 30,
    borderWidth: 2,
    alignItems: 'center',
    justifyContent: 'center',
  },
  feedAvatar: {
    width: 38,
    height: 38,
    borderRadius: 19,
    alignItems: 'center',
    justifyContent: 'center',
  },
  feedHero: {
    height: 180,
    borderRadius: 14,
    marginTop: 12,
    padding: 16,
    justifyContent: 'flex-end',
  },
  actionPill: { flexDirection: 'row', alignItems: 'center', gap: 5 },
  composerInput: {
    minHeight: 64,
    maxHeight: 180,
    marginTop: 8,
    borderRadius: 10,
    borderWidth: StyleSheet.hairlineWidth,
    paddingHorizontal: 12,
    paddingVertical: 10,
    fontSize: 14,
    lineHeight: 20,
  },
  thumbWrap: { position: 'relative' },
  thumb: { width: 80, height: 80, borderRadius: 10 },
  thumbX: {
    position: 'absolute',
    top: 4,
    right: 4,
    width: 20,
    height: 20,
    borderRadius: 10,
    alignItems: 'center',
    justifyContent: 'center',
  },
});
