/**
 * Business dashboard — KPIs derived from `/v1/businesses/me/analytics`.
 *
 * The endpoint returns:
 *   - `total_revenue_mnt` + `total_sales` for the trailing window,
 *   - `daily[]` with one bucket per UTC calendar day (zero-fill on the
 *     server, no client gap-filling), and
 *   - `top_skus[]` ordered by units sold.
 *
 * The window-toggle chip row at the bottom of the KPI strip flips
 * `windowDays` and refetches; React Query caches per window so toggling
 * back-and-forth is free after the first load.
 */

import { Feather } from '@expo/vector-icons';
import { useQuery } from '@tanstack/react-query';
import { useState } from 'react';
import { Pressable, StyleSheet, View } from 'react-native';

import { getAnalytics, getMyBusiness } from '../../src/api/businesses';
import { Chip } from '../../src/components/Chip';
import { Empty, Loading } from '../../src/components/Empty';
import { Glass } from '../../src/components/Glass';
import { IconButton } from '../../src/components/IconButton';
import { Screen } from '../../src/components/Screen';
import { ScreenHeader } from '../../src/components/ScreenHeader';
import { Sparkline } from '../../src/components/Sparkline';
import { Text } from '../../src/components/Text';
import { fmt, mnt } from '../../src/lib/format';
import { useTheme } from '../../src/theme/ThemeProvider';

const WINDOW_OPTIONS: { days: number; label: string }[] = [
  { days: 7, label: '7 хоног' },
  { days: 30, label: '30 хоног' },
  { days: 90, label: '90 хоног' },
];

export default function BusinessDashboard() {
  const theme = useTheme();
  const [windowDays, setWindowDays] = useState(7);

  const businessQ = useQuery({ queryKey: ['business', 'me'], queryFn: getMyBusiness, retry: false });
  const analyticsQ = useQuery({
    queryKey: ['business', 'analytics', windowDays],
    queryFn: () => getAnalytics(windowDays),
    enabled: !!businessQ.data,
  });

  if (businessQ.isLoading) return <Loading />;
  if (!businessQ.data) {
    return (
      <Screen contentStyle={{ paddingHorizontal: 18 }}>
        <ScreenHeader sub="БИЗНЕС" title="Хяналтын самбар" />
        <Empty
          title="Бизнес профайл алга"
          sub="Эхлээд бизнесийн профайл үүсгэснээр агуулах, борлуулалт удирдах боломжтой болно."
        />
      </Screen>
    );
  }

  const analytics = analyticsQ.data;
  const daily = analytics?.daily ?? [];
  const topSkus = analytics?.top_skus ?? [];
  const trendValues = daily.length >= 2 ? daily.map((d) => d.revenue_mnt) : [0, 0];

  return (
    <Screen scroll>
      <ScreenHeader
        sub={businessQ.data.display_name.toUpperCase()}
        title="Хяналтын самбар"
        right={
          <IconButton onPress={() => null}>
            <Feather name="bell" size={18} color={theme.colors.text} />
          </IconButton>
        }
      />

      <View style={{ paddingHorizontal: 18 }}>
        <View style={styles.windowRow}>
          {WINDOW_OPTIONS.map((opt) => (
            <Pressable key={opt.days} onPress={() => setWindowDays(opt.days)}>
              <Chip label={opt.label} tone={windowDays === opt.days ? 'accent' : 'neutral'} />
            </Pressable>
          ))}
        </View>

        <View style={styles.kpiGrid}>
          <Glass radius="md" style={{ flex: 1 }}>
            <Text variant="eyebrow" tone="tertiary">
              НИЙТ ОРЛОГО
            </Text>
            <Text variant="num" weight="700" style={{ fontSize: 18, marginTop: 6 }}>
              {analytics ? mnt(analytics.total_revenue_mnt) : '—'}
            </Text>
          </Glass>
          <Glass radius="md" style={{ flex: 1 }}>
            <Text variant="eyebrow" tone="tertiary">
              ХУДАЛДААНЫ ТОО
            </Text>
            <Text variant="num" weight="700" style={{ fontSize: 18, marginTop: 6 }}>
              {analytics ? fmt(analytics.total_sales) : '—'}
            </Text>
          </Glass>
        </View>

        <Glass radius="md" style={{ marginTop: 12 }}>
          <View style={{ flexDirection: 'row', alignItems: 'baseline', justifyContent: 'space-between' }}>
            <Text variant="eyebrow" tone="tertiary">
              ӨДӨР ТУТМЫН ОРЛОГО
            </Text>
            <Text variant="mono" tone="tertiary">
              {daily.length}
            </Text>
          </View>
          <View style={{ marginTop: 8 }}>
            <Sparkline values={trendValues} width={300} height={50} />
          </View>
          {analyticsQ.isLoading ? (
            <Loading />
          ) : daily.length === 0 ? (
            <Text variant="caption" tone="tertiary" style={{ marginTop: 8 }}>
              Сонгосон хугацаанд борлуулалт алга. Хүсэлтэд үнийн санал илгээж эхлэнэ үү.
            </Text>
          ) : null}
        </Glass>

        <Glass radius="md" style={{ marginTop: 12 }}>
          <Text variant="eyebrow" tone="tertiary">
            ШИЛДЭГ БАРАА
          </Text>
          {analyticsQ.isLoading ? (
            <Loading />
          ) : topSkus.length === 0 ? (
            <Text variant="caption" tone="tertiary" style={{ marginTop: 8 }}>
              Хараахан худалдаалсан бараа алга.
            </Text>
          ) : (
            <View style={{ marginTop: 8 }}>
              {topSkus.slice(0, 5).map((sku, i) => (
                <View
                  key={sku.sku_id}
                  style={[
                    styles.topRow,
                    i < Math.min(topSkus.length, 5) - 1
                      ? {
                          borderBottomWidth: StyleSheet.hairlineWidth,
                          borderBottomColor: theme.colors.stroke2,
                        }
                      : null,
                  ]}
                >
                  <Text variant="num" weight="700" tone="tertiary" style={{ fontSize: 14, width: 22 }}>
                    {i + 1}
                  </Text>
                  <View style={{ flex: 1, minWidth: 0 }}>
                    <Text variant="body" weight="600" numberOfLines={1}>
                      {sku.display_name}
                    </Text>
                    <Text variant="mono" tone="tertiary" style={{ fontSize: 11 }}>
                      {sku.sku_code}
                    </Text>
                  </View>
                  <View style={{ alignItems: 'flex-end' }}>
                    <Text variant="num" weight="700">
                      {fmt(sku.units_sold)}
                    </Text>
                    <Text variant="caption" tone="tertiary">
                      ширхэг
                    </Text>
                  </View>
                </View>
              ))}
            </View>
          )}
        </Glass>

        <Glass radius="md" style={{ marginTop: 12 }}>
          <Text variant="eyebrow" tone="tertiary">
            ӨӨРИЙН БРЭНДИЙН ЗОРИЛТО
          </Text>
          <Text variant="caption" tone="secondary" style={{ marginTop: 6, lineHeight: 18 }}>
            Зөвхөн өөрийн хамрах брэнд + он + жолооны талтай тохирох хүсэлт танд илгээгдэнэ.
            Хамрах хүрээгээ <Text variant="caption" tone="accent" weight="600">тохиргоо</Text>
            -ноос засна уу.
          </Text>
        </Glass>
      </View>
    </Screen>
  );
}

const styles = StyleSheet.create({
  kpiGrid: { flexDirection: 'row', gap: 8, marginTop: 12 },
  windowRow: { flexDirection: 'row', gap: 6, paddingTop: 4 },
  topRow: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 12,
    paddingVertical: 10,
  },
});
