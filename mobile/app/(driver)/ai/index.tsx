/**
 * AI Mechanic — session picker + new-session CTA.
 *
 * Each session is a long-lived conversation. Multimodal input (voice,
 * visual, engine sound, warning light) is composed inside an open
 * session at /(driver)/ai/[sessionId].
 */

import { Feather, MaterialCommunityIcons } from '@expo/vector-icons';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { useRouter } from 'expo-router';
import { Pressable, StyleSheet, View } from 'react-native';

import { createSession, listSessions } from '../../../src/api/aiMechanic';
import { listMyVehicles } from '../../../src/api/vehicles';
import { Button } from '../../../src/components/Button';
import { Chip } from '../../../src/components/Chip';
import { Empty, Loading } from '../../../src/components/Empty';
import { Glass } from '../../../src/components/Glass';
import { Screen } from '../../../src/components/Screen';
import { ScreenHeader } from '../../../src/components/ScreenHeader';
import { Text } from '../../../src/components/Text';
import { relativeMn } from '../../../src/lib/format';
import { useTheme } from '../../../src/theme/ThemeProvider';

export default function AiSessionList() {
  const theme = useTheme();
  const router = useRouter();
  const qc = useQueryClient();

  const sessionsQ = useQuery({
    queryKey: ['ai', 'sessions'],
    queryFn: () => listSessions({ limit: 50 }),
  });
  const vehiclesQ = useQuery({ queryKey: ['vehicles', 'me'], queryFn: () => listMyVehicles() });

  const create = useMutation({
    mutationFn: () => {
      const primary = vehiclesQ.data?.items?.[0];
      return createSession({ vehicle_id: primary?.id ?? null });
    },
    onSuccess: (s) => {
      void qc.invalidateQueries({ queryKey: ['ai', 'sessions'] });
      router.push({ pathname: '/(driver)/ai/[sessionId]', params: { sessionId: s.id } });
    },
  });

  const items = sessionsQ.data?.items ?? [];

  return (
    <Screen scroll>
      <ScreenHeader
        sub="iAUTO МЕХАНИК"
        title="Оношилгоо"
        right={<Chip label="Pro" tone="accent" />}
      />

      <View style={{ paddingHorizontal: 18 }}>
        <Glass radius="lg">
          <View style={{ flexDirection: 'row', alignItems: 'center', gap: 12 }}>
            <View style={[styles.aiAvatar, { backgroundColor: theme.colors.accent }]}>
              <MaterialCommunityIcons name="creation" size={22} color="#fff" />
            </View>
            <View style={{ flex: 1 }}>
              <Text variant="heading">Шинэ асуулт</Text>
              <Text variant="caption" tone="tertiary" style={{ marginTop: 4 }}>
                Бичих, дуу хоолой, хийн шил, хөдөлгүүрийн чимээ — олон арга.
              </Text>
            </View>
          </View>
          <Button
            size="md"
            label="Шинэ сессээ эхлэх"
            onPress={() => create.mutate()}
            disabled={create.isPending}
            loading={create.isPending}
            leftIcon={<Feather name="plus" size={16} color="#fff" />}
            style={{ marginTop: 12 }}
          />
        </Glass>

        <View style={styles.histHeader}>
          <Text variant="heading">Өмнөх сессүүд</Text>
          <Text variant="caption" tone="tertiary">
            <Text variant="mono">{items.length}</Text>
          </Text>
        </View>

        {sessionsQ.isLoading ? (
          <Loading />
        ) : items.length === 0 ? (
          <Empty
            title="Сесс алга"
            sub="Шинэ асуулт явуулснаар оношилгооны түүх нь энд хадгалагдана."
          />
        ) : (
          <View style={{ gap: 10, marginTop: 8 }}>
            {items.map((s) => (
              <Pressable
                key={s.id}
                onPress={() =>
                  router.push({ pathname: '/(driver)/ai/[sessionId]', params: { sessionId: s.id } })
                }
              >
                <Glass radius="md">
                  <View style={{ flexDirection: 'row', alignItems: 'center', gap: 10 }}>
                    <View
                      style={[
                        styles.iconBox,
                        { backgroundColor: theme.colors.accentGlow },
                      ]}
                    >
                      <Feather name="message-circle" size={16} color={theme.colors.accent2} />
                    </View>
                    <View style={{ flex: 1, minWidth: 0 }}>
                      <Text variant="body" weight="600" numberOfLines={1}>
                        {s.title ?? 'Шинэ сесс'}
                      </Text>
                      <Text variant="caption" tone="tertiary">
                        {relativeMn(s.created_at)} · {s.status === 'active' ? 'Идэвхтэй' : 'Хаагдсан'}
                      </Text>
                    </View>
                    <Feather name="chevron-right" size={18} color={theme.colors.text3} />
                  </View>
                </Glass>
              </Pressable>
            ))}
          </View>
        )}
      </View>
    </Screen>
  );
}

const styles = StyleSheet.create({
  aiAvatar: {
    width: 40,
    height: 40,
    borderRadius: 12,
    alignItems: 'center',
    justifyContent: 'center',
  },
  histHeader: {
    marginTop: 18,
    marginBottom: 6,
    flexDirection: 'row',
    alignItems: 'baseline',
    justifyContent: 'space-between',
  },
  iconBox: {
    width: 32,
    height: 32,
    borderRadius: 8,
    alignItems: 'center',
    justifyContent: 'center',
  },
});
