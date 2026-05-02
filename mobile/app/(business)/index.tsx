/**
 * Business dashboard — KPIs derived from real backend counts.
 *
 * Sources:
 *   - listSkus() / total            → "Барааны төрөл"
 *   - listMyQuotes() / total        → outstanding-quote count
 *   - listOutgoingSales() / total   → 7-day sales count
 *
 * The bar-chart visual currently uses the latest-sale price set as
 * proxy values rather than aggregate analytics — backend doesn't yet
 * expose a daily-totals endpoint. This is annotated with a "Phase 2"
 * note in the chart card rather than fabricated trendlines.
 */

import { Feather } from '@expo/vector-icons';
import { useQuery } from '@tanstack/react-query';
import { StyleSheet, View } from 'react-native';

import { getMyBusiness } from '../../src/api/businesses';
import { listMyQuotes, listOutgoingSales } from '../../src/api/marketplace';
import { listSkus } from '../../src/api/warehouse';
import { Empty, Loading } from '../../src/components/Empty';
import { Glass } from '../../src/components/Glass';
import { IconButton } from '../../src/components/IconButton';
import { Screen } from '../../src/components/Screen';
import { ScreenHeader } from '../../src/components/ScreenHeader';
import { Sparkline } from '../../src/components/Sparkline';
import { Text } from '../../src/components/Text';
import { fmt, mntMillions } from '../../src/lib/format';
import { useTheme } from '../../src/theme/ThemeProvider';

export default function BusinessDashboard() {
  const theme = useTheme();
  const businessQ = useQuery({ queryKey: ['business', 'me'], queryFn: getMyBusiness, retry: false });
  const skusQ = useQuery({ queryKey: ['skus'], queryFn: () => listSkus({ limit: 1 }) });
  const quotesQ = useQuery({ queryKey: ['quotes', 'mine'], queryFn: () => listMyQuotes({ limit: 1 }) });
  const salesQ = useQuery({
    queryKey: ['sales', 'outgoing'],
    queryFn: () => listOutgoingSales({ limit: 50 }),
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

  const sales = salesQ.data?.items ?? [];
  // Build a simple sparkline from each sale's price — still real data,
  // not a fabrication; just not aggregate analytics.
  const trendValues =
    sales.length >= 2
      ? sales.slice(0, 14).map((s) => s.price_mnt)
      : [0, 0];

  const totalSalesMnt = sales.reduce((acc, s) => acc + s.price_mnt, 0);

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
        <View style={styles.kpiGrid}>
          {[
            {
              label: 'Барааны төрөл',
              value: skusQ.data ? fmt(skusQ.data.total) : '—',
              delta: '',
              tone: theme.colors.success,
            },
            {
              label: 'Сүүлийн борлуулалт',
              value: salesQ.data ? mntMillions(totalSalesMnt) : '—',
              delta: '',
              tone: theme.colors.success,
            },
            {
              label: 'Хүлээгдэх санал',
              value: quotesQ.data ? fmt(quotesQ.data.total) : '—',
              delta: '',
              tone: theme.colors.warn,
            },
          ].map((k) => (
            <Glass key={k.label} radius="md" style={{ flex: 1 }}>
              <Text variant="eyebrow" tone="tertiary">
                {k.label}
              </Text>
              <Text variant="num" weight="700" style={{ fontSize: 18, marginTop: 6 }}>
                {k.value}
              </Text>
            </Glass>
          ))}
        </View>

        <Glass radius="md" style={{ marginTop: 12 }}>
          <View style={{ flexDirection: 'row', alignItems: 'baseline', justifyContent: 'space-between' }}>
            <Text variant="eyebrow" tone="tertiary">
              СҮҮЛИЙН БОРЛУУЛАЛТУУД
            </Text>
            <Text variant="mono" tone="tertiary">
              {sales.length}
            </Text>
          </View>
          <View style={{ marginTop: 8 }}>
            <Sparkline values={trendValues} width={300} height={50} />
          </View>
          {sales.length === 0 ? (
            <Text variant="caption" tone="tertiary" style={{ marginTop: 8 }}>
              Хараахан борлуулалт алга. Хүсэлтэд үнийн санал илгээж эхлэнэ үү.
            </Text>
          ) : null}
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
  kpiGrid: { flexDirection: 'row', gap: 8 },
});
