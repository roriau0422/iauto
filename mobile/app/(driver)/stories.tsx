/**
 * Stories feed — driver POV.
 *
 * Backend currently exposes only business-authored posts (decision in
 * the design file's "ОЙРЫН ҮЕД" / "Phase 2" annotation). We still show
 * the story rail with what we have plus the disclosure banner.
 */

import { Feather } from '@expo/vector-icons';
import { useQuery } from '@tanstack/react-query';
import { ScrollView, StyleSheet, View } from 'react-native';

import { getFeed } from '../../src/api/stories';
import { Chip } from '../../src/components/Chip';
import { Empty, Loading } from '../../src/components/Empty';
import { Glass } from '../../src/components/Glass';
import { IconButton } from '../../src/components/IconButton';
import { Screen } from '../../src/components/Screen';
import { ScreenHeader } from '../../src/components/ScreenHeader';
import { Text } from '../../src/components/Text';
import { relativeMn } from '../../src/lib/format';
import { useTheme } from '../../src/theme/ThemeProvider';

export default function StoriesScreen() {
  const theme = useTheme();
  const feedQ = useQuery({ queryKey: ['stories', 'feed'], queryFn: () => getFeed({ limit: 20 }) });
  const items = feedQ.data?.items ?? [];

  return (
    <Screen scroll>
      <ScreenHeader
        sub="МЭДЭЭНИЙ СУВАГ"
        title="Сошиал"
        right={
          <IconButton onPress={() => null}>
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
          <View style={{ alignItems: 'center', width: 64 }}>
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
          </View>
          {items.slice(0, 8).map((p) => (
            <View key={p.id} style={{ alignItems: 'center', width: 64 }}>
              <View
                style={[
                  styles.dot,
                  {
                    backgroundColor: theme.colors.accent,
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

        <Glass
          radius="md"
          style={{
            marginTop: 10,
            backgroundColor: 'rgba(255,179,71,0.08)',
            borderColor: 'rgba(255,179,71,0.22)',
            borderWidth: 0.5,
          }}
        >
          <View style={{ flexDirection: 'row', alignItems: 'center', gap: 10 }}>
            <View
              style={{
                width: 24,
                height: 24,
                borderRadius: 6,
                backgroundColor: 'rgba(255,179,71,0.2)',
                alignItems: 'center',
                justifyContent: 'center',
              }}
            >
              <Feather name="info" size={12} color={theme.colors.warn} />
            </View>
            <Text variant="caption" tone="secondary" style={{ flex: 1, lineHeight: 17 }}>
              <Text variant="caption" weight="700" style={{ color: theme.colors.warn }}>
                Phase 2 ·
              </Text>{' '}
              Жолоочдын нийтлэл удахгүй нээгдэнэ. Одоогоор бизнесүүдийн зар, мэдээллийг харна
              уу.
            </Text>
          </View>
        </Glass>

        {feedQ.isLoading ? (
          <Loading />
        ) : items.length === 0 ? (
          <Empty
            title="Шинэ нийтлэл алга"
            sub="Бизнес түншүүд хямдрал, шинэ бараа, үйлчилгээний мэдээллээ үе үе нийтэлдэг."
          />
        ) : (
          <View style={{ gap: 12, marginTop: 14 }}>
            {items.map((p) => (
              <Glass key={p.id} radius="lg">
                <View style={{ flexDirection: 'row', alignItems: 'center', gap: 10 }}>
                  <View style={[styles.feedAvatar, { backgroundColor: theme.colors.accent }]}>
                    <Text variant="body" weight="700" tone="inverse">
                      {p.body[0]?.toUpperCase() ?? 'i'}
                    </Text>
                  </View>
                  <View style={{ flex: 1, minWidth: 0 }}>
                    <View style={{ flexDirection: 'row', alignItems: 'center', gap: 5 }}>
                      <Text variant="body" weight="700">
                        Бизнес
                      </Text>
                      <Feather name="shield" size={12} color={theme.colors.accent2} />
                    </View>
                    <Text variant="caption" tone="tertiary">
                      {relativeMn(p.created_at)}
                    </Text>
                  </View>
                  <Chip label="SPONSORED" tone="warn" />
                </View>

                <View style={[styles.feedHero, { backgroundColor: theme.colors.surface2 }]}>
                  <Text variant="title" tone="primary" weight="700" style={{ color: '#fff' }}>
                    {p.body.slice(0, 80)}
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
                      {p.like_count}
                    </Text>
                  </View>
                  <View style={styles.actionPill}>
                    <Feather name="message-circle" size={16} color={theme.colors.text2} />
                    <Text variant="caption" weight="500" tone="secondary">
                      {p.comment_count}
                    </Text>
                  </View>
                  <View style={{ flex: 1 }} />
                  <Feather name="bookmark" size={16} color={theme.colors.text3} />
                </View>
              </Glass>
            ))}
          </View>
        )}
      </View>
    </Screen>
  );
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
});
