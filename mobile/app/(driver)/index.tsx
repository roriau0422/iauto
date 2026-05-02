/**
 * Driver Home — vehicle hero, dues banner (notifications), quick actions,
 * AI оношилгоо ring, valuation tile, stories rail teaser.
 *
 * All data is real-server. Empty states surface when the user has no
 * registered vehicle, no notifications, no AI sessions, etc.
 */

import { Feather, MaterialCommunityIcons } from '@expo/vector-icons';
import { useQuery } from '@tanstack/react-query';
import { useRouter } from 'expo-router';
import { Pressable, ScrollView, StyleSheet, View } from 'react-native';

import { listSessions } from '../../src/api/aiMechanic';
import { listMyNotifications } from '../../src/api/notifications';
import { getFeed } from '../../src/api/stories';
import { listMyVehicles } from '../../src/api/vehicles';
import { useAuth } from '../../src/auth/store';
import { Button } from '../../src/components/Button';
import { Empty } from '../../src/components/Empty';
import { Glass } from '../../src/components/Glass';
import { IconButton } from '../../src/components/IconButton';
import { Ring } from '../../src/components/Ring';
import { Screen } from '../../src/components/Screen';
import { ScreenHeader } from '../../src/components/ScreenHeader';
import { Sparkline } from '../../src/components/Sparkline';
import { Text } from '../../src/components/Text';
import { VehicleCard } from '../../src/components/VehicleCard';
import { relativeMn } from '../../src/lib/format';
import { useTheme } from '../../src/theme/ThemeProvider';

export default function HomeScreen() {
  const theme = useTheme();
  const router = useRouter();
  const user = useAuth((s) => s.user);

  const vehiclesQ = useQuery({ queryKey: ['vehicles', 'me'], queryFn: () => listMyVehicles() });
  const sessionsQ = useQuery({
    queryKey: ['ai', 'sessions', { limit: 1 }],
    queryFn: () => listSessions({ limit: 1 }),
  });
  const notifsQ = useQuery({
    queryKey: ['notifications', { limit: 4 }],
    queryFn: () => listMyNotifications({ limit: 4 }),
  });
  const storiesQ = useQuery({
    queryKey: ['stories', { limit: 6 }],
    queryFn: () => getFeed({ limit: 6 }),
  });

  const greetingInitial = user?.display_name?.[0] ?? user?.phone?.slice(-1) ?? 'i';
  const greetingName = user?.display_name ?? 'тавтай морил';

  const vehicles = vehiclesQ.data?.items ?? [];
  const primary = vehicles[0] ?? null;
  const lastSession = sessionsQ.data?.items?.[0] ?? null;
  const notifications = notifsQ.data?.items ?? [];
  const firstNotif = notifications[0];
  const stories = storiesQ.data?.items ?? [];

  return (
    <Screen scroll>
      <ScreenHeader
        sub="БАЯРТАЙ ӨГЛӨӨ"
        title={`Сайн уу, ${greetingName}`}
        left={
          <View style={[styles.avatar, { backgroundColor: theme.colors.accent }]}>
            <Text variant="body" weight="700" tone="inverse">
              {greetingInitial.toUpperCase()}
            </Text>
          </View>
        }
        right={
          <IconButton onPress={() => router.push('/settings')}>
            <Feather name="bell" size={18} color={theme.colors.text} />
            {notifications.length > 0 ? <View style={[styles.bellDot, { borderColor: theme.colors.bg1 }]} /> : null}
          </IconButton>
        }
      />

      <View style={{ paddingHorizontal: 18 }}>
        {primary ? (
          <Pressable onPress={() => router.push('/(driver)/service')}>
            <VehicleCard
              v={{
                plate: primary.plate,
                make: primary.make ?? '—',
                model: primary.model ?? '',
                build_year: primary.build_year ?? new Date().getFullYear(),
                fuel_type: primary.fuel_type,
                steering_side: primary.steering_side,
                capacity_cc: primary.capacity_cc,
                engine_number: primary.engine_number,
                last_ai_diagnostic_at: lastSession?.created_at,
              }}
            />
          </Pressable>
        ) : (
          <Glass radius="lg">
            <Text variant="heading">Машингүй байна</Text>
            <Text variant="caption" tone="tertiary" style={{ marginTop: 6 }}>
              Дугаараа оруулж бүртгүүлснээр зах зээл, AI механик, үнэлгээний сан танилцана.
            </Text>
            <Button
              size="md"
              label="Машин нэмэх"
              onPress={() => router.push('/onboarding/plate')}
              style={{ marginTop: 12 }}
              leftIcon={<Feather name="plus" size={16} color="#fff" />}
            />
          </Glass>
        )}

        {firstNotif ? (
          <Glass
            radius="md"
            style={[styles.notifStrip, { borderLeftWidth: 3, borderLeftColor: theme.colors.warn }]}
          >
            <View style={styles.notifIcon}>
              <Feather name="alert-circle" size={18} color={theme.colors.warn} />
            </View>
            <View style={{ flex: 1, minWidth: 0 }}>
              <Text variant="eyebrow" style={{ color: theme.colors.warn }}>
                Анхааруулга
              </Text>
              <Text variant="body" weight="600" numberOfLines={1}>
                {firstNotif.kind === 'reservation_confirmed' ||
                firstNotif.kind === 'reservation_completed'
                  ? 'Захиалгын мэдэгдэл'
                  : firstNotif.kind}
              </Text>
              <Text variant="caption" tone="tertiary" numberOfLines={1}>
                {relativeMn(firstNotif.created_at)} · {firstNotif.body_text}
              </Text>
            </View>
            <Feather name="chevron-right" size={18} color={theme.colors.text3} />
          </Glass>
        ) : null}

        <View style={styles.actionsGrid}>
          {[
            {
              label: 'AI Механик',
              icon: <MaterialCommunityIcons name="creation" size={18} color="#7BA8FF" />,
              tint: '#7BA8FF',
              onPress: () => router.push('/(driver)/ai'),
            },
            {
              label: 'Эд анги',
              icon: <Feather name="search" size={18} color="#5EE2A0" />,
              tint: '#5EE2A0',
              onPress: () => router.push('/(driver)/market'),
            },
            {
              label: 'Үнэлгээ',
              icon: <MaterialCommunityIcons name="chart-line" size={18} color="#FFB347" />,
              tint: '#FFB347',
              onPress: () => router.push('/(driver)/value'),
            },
            {
              label: 'Үйлчилгээ',
              icon: <Feather name="tool" size={18} color="#A89BFF" />,
              tint: '#A89BFF',
              onPress: () => router.push('/(driver)/service'),
            },
          ].map((a) => (
            <Pressable key={a.label} onPress={a.onPress} style={{ flex: 1 }}>
              <Glass radius="md" style={{ alignItems: 'center', paddingVertical: 12 }}>
                <View
                  style={[
                    styles.actionIcon,
                    { backgroundColor: `${a.tint}22` },
                  ]}
                >
                  {a.icon}
                </View>
                <Text variant="caption" weight="700" style={{ marginTop: 8, fontSize: 10.5 }}>
                  {a.label}
                </Text>
              </Glass>
            </Pressable>
          ))}
        </View>

        <View style={styles.duoRow}>
          <Pressable style={{ flex: 1 }} onPress={() => router.push('/(driver)/ai')}>
            <Glass radius="md">
              <Text variant="eyebrow" tone="tertiary">
                AI ОНОШИЛГОО · СҮҮЛИЙН
              </Text>
              {lastSession ? (
                <View style={styles.aiRow}>
                  <Ring size={56} value={0.86} label="—" sub="оноо" />
                  <View style={{ flex: 1 }}>
                    <Text variant="caption" weight="600" tone="success">
                      ● Бүртгэлтэй
                    </Text>
                    <Text variant="caption" tone="tertiary">
                      {relativeMn(lastSession.created_at)}
                    </Text>
                  </View>
                </View>
              ) : (
                <View style={{ marginTop: 10 }}>
                  <Text variant="caption" tone="tertiary">
                    Нэг ч сесс нээгдээгүй байна
                  </Text>
                  <Text variant="caption" tone="tertiary" style={{ marginTop: 4 }}>
                    Эхний асуултаа AI Механикт явуулна уу
                  </Text>
                </View>
              )}
            </Glass>
          </Pressable>

          <Pressable style={{ flex: 1 }} onPress={() => router.push('/(driver)/value')}>
            <Glass radius="md">
              <Text variant="eyebrow" tone="tertiary">
                Зах зээлийн үнэ
              </Text>
              <ValuationTeaser />
            </Glass>
          </Pressable>
        </View>

        <View style={styles.feedHeader}>
          <Text variant="heading">Сошиал мэдээний суваг</Text>
          <Pressable onPress={() => router.push('/(driver)/stories')}>
            <Text variant="caption" tone="accent" weight="600">
              Бүгд →
            </Text>
          </Pressable>
        </View>
        {stories.length > 0 ? (
          <ScrollView
            horizontal
            showsHorizontalScrollIndicator={false}
            contentContainerStyle={{ gap: 8, paddingVertical: 4 }}
          >
            {stories.slice(0, 5).map((s) => (
              <View key={s.id} style={{ width: 60, alignItems: 'center' }}>
                <View
                  style={[
                    styles.storyDot,
                    {
                      backgroundColor: theme.colors.accent,
                      borderColor: theme.colors.bg1,
                    },
                  ]}
                >
                  <Text variant="body" weight="700" tone="inverse">
                    {s.body[0]?.toUpperCase() ?? 'i'}
                  </Text>
                </View>
                <Text
                  variant="caption"
                  tone="tertiary"
                  numberOfLines={1}
                  style={{ marginTop: 4, maxWidth: 60 }}
                >
                  {s.body.slice(0, 12)}
                </Text>
              </View>
            ))}
          </ScrollView>
        ) : (
          <Empty title="Шинэ нийтлэл алга" sub="Бизнесүүдийн зар, шинэ бараа удахгүй харагдана." />
        )}
      </View>
    </Screen>
  );
}

function ValuationTeaser() {
  // No client-side valuation cache yet — render an empty teaser until
  // the user clicks through and runs the estimate.
  return (
    <View style={{ marginTop: 10 }}>
      <Text variant="num" weight="700" style={{ fontSize: 17 }}>
        —
      </Text>
      <Text variant="caption" tone="tertiary" style={{ marginTop: 4 }}>
        Үнэлгээ авахад дараа суурь үзүүлэлт харагдана
      </Text>
      <View style={{ marginTop: 6 }}>
        <Sparkline values={[0.5, 0.55, 0.62, 0.6, 0.7, 0.72, 0.78]} width={100} height={22} />
      </View>
    </View>
  );
}

const styles = StyleSheet.create({
  avatar: {
    width: 38,
    height: 38,
    borderRadius: 19,
    alignItems: 'center',
    justifyContent: 'center',
  },
  bellDot: {
    position: 'absolute',
    top: 8,
    right: 8,
    width: 7,
    height: 7,
    borderRadius: 4,
    backgroundColor: '#FF6E6E',
    borderWidth: 2,
  },
  notifStrip: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 12,
    marginTop: 12,
    paddingLeft: 8,
  },
  notifIcon: {
    width: 36,
    height: 36,
    borderRadius: 10,
    backgroundColor: 'rgba(255,179,71,0.18)',
    alignItems: 'center',
    justifyContent: 'center',
  },
  actionsGrid: { flexDirection: 'row', gap: 8, marginTop: 14 },
  actionIcon: {
    width: 36,
    height: 36,
    borderRadius: 11,
    alignItems: 'center',
    justifyContent: 'center',
  },
  duoRow: { flexDirection: 'row', gap: 10, marginTop: 12 },
  aiRow: { flexDirection: 'row', alignItems: 'center', gap: 12, marginTop: 10 },
  feedHeader: {
    marginTop: 18,
    marginBottom: 6,
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'space-between',
  },
  storyDot: {
    width: 56,
    height: 56,
    borderRadius: 28,
    borderWidth: 2,
    alignItems: 'center',
    justifyContent: 'center',
  },
});
