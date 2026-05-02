/**
 * Business stories — same feed surface as the driver tab, plus a
 * lightweight composer that POSTs to `/v1/story/posts`.
 */

import { Feather } from '@expo/vector-icons';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { useState } from 'react';
import { Modal, Pressable, StyleSheet, TextInput, View } from 'react-native';

import { getFeed, publishPost } from '../../src/api/stories';
import { Button } from '../../src/components/Button';
import { Empty, Loading } from '../../src/components/Empty';
import { Glass } from '../../src/components/Glass';
import { IconButton } from '../../src/components/IconButton';
import { Screen } from '../../src/components/Screen';
import { ScreenHeader } from '../../src/components/ScreenHeader';
import { Text } from '../../src/components/Text';
import { relativeMn } from '../../src/lib/format';
import { useTheme } from '../../src/theme/ThemeProvider';

export default function BusinessStories() {
  const theme = useTheme();
  const qc = useQueryClient();
  const feedQ = useQuery({ queryKey: ['stories', 'feed'], queryFn: () => getFeed({ limit: 20 }) });
  const [composing, setComposing] = useState(false);
  const [body, setBody] = useState('');

  const post = useMutation({
    mutationFn: () => publishPost({ body: body.trim(), media_asset_ids: [] }),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: ['stories', 'feed'] });
      setBody('');
      setComposing(false);
    },
  });

  const items = feedQ.data?.items ?? [];

  return (
    <Screen scroll>
      <ScreenHeader
        sub="БИЗНЕС ЗАР"
        title="Сошиал"
        right={
          <IconButton onPress={() => setComposing(true)} filled>
            <Feather name="plus" size={18} color="#fff" />
          </IconButton>
        }
      />

      <View style={{ paddingHorizontal: 18 }}>
        {feedQ.isLoading ? (
          <Loading />
        ) : items.length === 0 ? (
          <Empty
            title="Шинэ нийтлэл алга"
            sub="Хямдрал, шинэ бараа, үйлчилгээний мэдээллээ нийтэлж бизнесээ өргөжүүлнэ үү."
          />
        ) : (
          <View style={{ gap: 12 }}>
            {items.map((p) => (
              <Glass key={p.id} radius="lg">
                <Text variant="caption" tone="tertiary">
                  {relativeMn(p.created_at)}
                </Text>
                <Text variant="body" style={{ marginTop: 6, lineHeight: 20 }}>
                  {p.body}
                </Text>
                <View style={{ flexDirection: 'row', alignItems: 'center', gap: 18, marginTop: 10 }}>
                  <View style={styles.actionPill}>
                    <Feather name="heart" size={14} color={theme.colors.text2} />
                    <Text variant="caption" tone="secondary">
                      {p.like_count}
                    </Text>
                  </View>
                  <View style={styles.actionPill}>
                    <Feather name="message-circle" size={14} color={theme.colors.text2} />
                    <Text variant="caption" tone="secondary">
                      {p.comment_count}
                    </Text>
                  </View>
                </View>
              </Glass>
            ))}
          </View>
        )}
      </View>

      <Modal visible={composing} transparent animationType="slide">
        <View style={modal.backdrop}>
          <View style={[modal.sheet, { backgroundColor: theme.colors.bg1 }]}>
            <View style={modal.sheetHeader}>
              <Text variant="heading">Шинэ зар</Text>
              <Pressable onPress={() => setComposing(false)}>
                <Feather name="x" size={20} color={theme.colors.text} />
              </Pressable>
            </View>
            <Glass radius="md" style={{ paddingVertical: 4 }}>
              <TextInput
                value={body}
                onChangeText={setBody}
                placeholder="Жишээ нь — Хийн шүүлтүүр −25%, бүх загвар, энэ долоо хоног"
                placeholderTextColor={theme.colors.text3}
                multiline
                style={{
                  color: theme.colors.text,
                  fontSize: 14,
                  paddingVertical: 6,
                  minHeight: 100,
                  textAlignVertical: 'top',
                }}
              />
            </Glass>
            <Button
              size="lg"
              label={post.isPending ? 'Илгээж байна…' : 'Нийтлэх'}
              disabled={!body.trim() || post.isPending}
              loading={post.isPending}
              onPress={() => post.mutate()}
              style={{ marginTop: 12 }}
            />
          </View>
        </View>
      </Modal>
    </Screen>
  );
}

const styles = StyleSheet.create({
  actionPill: { flexDirection: 'row', alignItems: 'center', gap: 5 },
});

const modal = StyleSheet.create({
  backdrop: { flex: 1, backgroundColor: 'rgba(5,8,22,0.6)', justifyContent: 'flex-end' },
  sheet: { padding: 18, borderTopLeftRadius: 22, borderTopRightRadius: 22 },
  sheetHeader: {
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'space-between',
    marginBottom: 12,
  },
});
