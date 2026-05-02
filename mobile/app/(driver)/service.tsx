/**
 * Driver service-history + dues screen. Pulls real data from:
 *   - GET /v1/vehicles/me              (find primary vehicle)
 *   - GET /v1/vehicles/{id}/service-history
 *   - GET /v1/vehicles/{id}/tax        (placeholder shape; phase 2 fills in)
 *   - GET /v1/vehicles/{id}/insurance
 *   - GET /v1/vehicles/{id}/fines
 *
 * The dues amounts/dates are stub-shape per `MyCarItemOut` — real data
 * pipelines land in a later session. We surface "Удахгүй" copy on
 * empty/null amount instead of fabricating numbers.
 */

import { Feather } from '@expo/vector-icons';
import { useQuery } from '@tanstack/react-query';
import { useRouter } from 'expo-router';
import { StyleSheet, View } from 'react-native';

import {
  listMyVehicles,
  listServiceHistory,
  listVehicleFines,
  listVehicleInsurance,
  listVehicleTax,
} from '../../src/api/vehicles';
import { Empty, Loading } from '../../src/components/Empty';
import { Glass } from '../../src/components/Glass';
import { IconButton } from '../../src/components/IconButton';
import { Ring } from '../../src/components/Ring';
import { Screen } from '../../src/components/Screen';
import { ScreenHeader } from '../../src/components/ScreenHeader';
import { Text } from '../../src/components/Text';
import { dateOnly, fmt, mnt } from '../../src/lib/format';
import { useTheme } from '../../src/theme/ThemeProvider';

export default function ServiceScreen() {
  const theme = useTheme();
  const router = useRouter();
  const vehiclesQ = useQuery({ queryKey: ['vehicles', 'me'], queryFn: () => listMyVehicles() });
  const primary = vehiclesQ.data?.items?.[0] ?? null;
  const id = primary?.id;

  const histQ = useQuery({
    queryKey: ['vehicle', id, 'service-history'],
    queryFn: () => (id ? listServiceHistory(id) : Promise.reject(new Error('no vehicle'))),
    enabled: !!id,
  });
  const taxQ = useQuery({
    queryKey: ['vehicle', id, 'tax'],
    queryFn: () => (id ? listVehicleTax(id) : Promise.reject(new Error('no vehicle'))),
    enabled: !!id,
  });
  const insQ = useQuery({
    queryKey: ['vehicle', id, 'insurance'],
    queryFn: () => (id ? listVehicleInsurance(id) : Promise.reject(new Error('no vehicle'))),
    enabled: !!id,
  });
  const finesQ = useQuery({
    queryKey: ['vehicle', id, 'fines'],
    queryFn: () => (id ? listVehicleFines(id) : Promise.reject(new Error('no vehicle'))),
    enabled: !!id,
  });

  if (vehiclesQ.isLoading) return <Loading />;
  if (!primary) {
    return (
      <Screen contentStyle={{ paddingHorizontal: 18 }}>
        <ScreenHeader
          sub="МИНИЙ МАШИН"
          title="Үйлчилгээ ба төлбөр"
          left={
            <IconButton onPress={() => router.back()}>
              <Feather name="arrow-left" size={18} color={theme.colors.text} />
            </IconButton>
          }
        />
        <Empty title="Машингүй байна" sub="Эхлээд дугаараа бүртгүүлнэ үү." />
      </Screen>
    );
  }

  const dues: { kind: string; label: string; data: typeof taxQ.data }[] = [
    { kind: 'tax', label: 'Тээврийн хураамж', data: taxQ.data },
    { kind: 'insurance', label: 'Даатгал', data: insQ.data },
    { kind: 'fines', label: 'Жолооны торгууль', data: finesQ.data },
  ];

  return (
    <Screen scroll>
      <ScreenHeader
        sub="МИНИЙ МАШИН"
        title="Үйлчилгээ ба төлбөр"
        left={
          <IconButton onPress={() => router.back()}>
            <Feather name="arrow-left" size={18} color={theme.colors.text} />
          </IconButton>
        }
      />

      <View style={{ paddingHorizontal: 18 }}>
        <View style={{ gap: 8 }}>
          {dues.map((d) => {
            const items = d.data?.items ?? [];
            const top = items[0];
            const due = top?.due_at;
            const amount = top?.amount_mnt;
            const isDue = due ? new Date(due).getTime() - Date.now() < 30 * 24 * 60 * 60 * 1000 : false;
            return (
              <Glass
                key={d.kind}
                radius="md"
                style={{
                  borderLeftWidth: 3,
                  borderLeftColor: isDue ? theme.colors.warn : theme.colors.success,
                }}
              >
                <View style={{ flexDirection: 'row', alignItems: 'center', gap: 12 }}>
                  <View
                    style={[
                      styles.icoBox,
                      {
                        backgroundColor: isDue
                          ? 'rgba(255,179,71,0.18)'
                          : 'rgba(94,226,160,0.16)',
                      },
                    ]}
                  >
                    <Feather
                      name={d.kind === 'fines' ? 'shield' : d.kind === 'insurance' ? 'umbrella' : 'credit-card'}
                      size={18}
                      color={isDue ? theme.colors.warn : theme.colors.success}
                    />
                  </View>
                  <View style={{ flex: 1, minWidth: 0 }}>
                    <Text variant="body" weight="600">
                      {d.label}
                    </Text>
                    <Text variant="caption" tone="tertiary" style={{ marginTop: 2 }}>
                      {due ? `Хугацаа: ${dateOnly(due)}` : 'Удахгүй холбогдоно'}
                    </Text>
                  </View>
                  <View style={{ alignItems: 'flex-end' }}>
                    <Text variant="num" weight="700">
                      {amount != null ? mnt(amount) : '—'}
                    </Text>
                    {isDue ? (
                      <Text variant="caption" tone="warn" weight="600">
                        QPay-ээр төлөх →
                      </Text>
                    ) : null}
                  </View>
                </View>
              </Glass>
            );
          })}
        </View>

        <Glass radius="md" style={{ marginTop: 14 }}>
          <Text variant="eyebrow" tone="tertiary">
            ДАРААГИЙН ҮЙЛЧИЛГЭЭ
          </Text>
          <View style={{ flexDirection: 'row', alignItems: 'center', gap: 16, marginTop: 12 }}>
            <View style={{ flex: 1 }}>
              <Text variant="num" weight="700" style={{ fontSize: 22 }}>
                Удахгүй
              </Text>
              <Text variant="caption" tone="tertiary" style={{ marginTop: 2 }}>
                Тосолгооны хугацаа таны бүртгэлтэй мэдээлэлд тулгуурлан тооцоологдоно.
              </Text>
            </View>
            <Ring size={80} value={0.66} stroke={6} label="—" sub="оноо" />
          </View>
        </Glass>

        <View style={styles.histHeader}>
          <Text variant="heading">Үйлчилгээний түүх</Text>
          <Text variant="caption" tone="accent" weight="600">
            PDF татах
          </Text>
        </View>

        {histQ.isLoading ? (
          <Loading />
        ) : (histQ.data?.items.length ?? 0) === 0 ? (
          <Empty
            title="Үйлчилгээний бичлэг алга"
            sub="Тосолгоо, шүүлтүүр, дугуй сэлгэлтийг бүртгээд түүх энд харагдана."
          />
        ) : (
          <Glass radius="md" style={{ paddingVertical: 0 }}>
            {(histQ.data?.items ?? []).map((h, i, arr) => (
              <View
                key={h.id}
                style={[
                  styles.histRow,
                  i < arr.length - 1
                    ? { borderBottomWidth: StyleSheet.hairlineWidth, borderBottomColor: theme.colors.stroke2 }
                    : null,
                ]}
              >
                <View style={[styles.dot, { backgroundColor: theme.colors.accent2 }]} />
                <View style={{ flex: 1, minWidth: 0 }}>
                  <Text variant="body" weight="600">
                    {h.title ?? labelForKind(h.kind)}
                  </Text>
                  <Text variant="caption" tone="tertiary">
                    {h.location ?? '—'} · {h.mileage_km != null ? `${fmt(h.mileage_km)} км` : '—'}
                  </Text>
                </View>
                <View style={{ alignItems: 'flex-end' }}>
                  <Text variant="num" weight="700">
                    {h.cost_mnt != null ? mnt(h.cost_mnt) : '—'}
                  </Text>
                  <Text variant="mono" tone="tertiary" style={{ fontSize: 10 }}>
                    {dateOnly(h.noted_at)}
                  </Text>
                </View>
              </View>
            ))}
          </Glass>
        )}
      </View>
    </Screen>
  );
}

function labelForKind(k: string): string {
  switch (k) {
    case 'oil':
      return 'Тосолгоо';
    case 'filter':
      return 'Шүүлтүүр';
    case 'tire':
      return 'Дугуй';
    case 'battery':
      return 'Аккум';
    default:
      return 'Үйлчилгээ';
  }
}

const styles = StyleSheet.create({
  icoBox: {
    width: 40,
    height: 40,
    borderRadius: 12,
    alignItems: 'center',
    justifyContent: 'center',
  },
  histHeader: {
    marginTop: 18,
    marginBottom: 8,
    flexDirection: 'row',
    alignItems: 'baseline',
    justifyContent: 'space-between',
  },
  histRow: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 12,
    paddingVertical: 12,
    paddingHorizontal: 14,
  },
  dot: { width: 8, height: 8, borderRadius: 4 },
});
