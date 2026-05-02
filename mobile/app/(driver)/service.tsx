/**
 * Driver service-history + dues screen.
 *
 * Sources:
 *   - GET /v1/vehicles/me                         (find primary vehicle)
 *   - GET /v1/vehicles/{id}/service-history
 *   - GET /v1/vehicles/{id}/dues                  (real tax / insurance / fines rows)
 *   - POST /v1/vehicles/{id}/dues/{dueId}/pay     (QPay invoice creation)
 *
 * The pay flow:
 *   1. user taps "Төлөх" — we kick off the invoice via `payDue`,
 *   2. open the QPay deeplink in the system browser (or first url in
 *      `urls`), and
 *   3. flip the dues query into a 4 s polling cadence until the row's
 *      status flips to `paid` (or the user pulls back).
 */

import { Feather } from '@expo/vector-icons';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { useRouter } from 'expo-router';
import * as WebBrowser from 'expo-web-browser';
import { useCallback, useState } from 'react';
import { Alert, StyleSheet, View } from 'react-native';

import {
  listDues,
  listMyVehicles,
  listServiceHistory,
  payDue,
} from '../../src/api/vehicles';
import { Button } from '../../src/components/Button';
import { Empty, Loading } from '../../src/components/Empty';
import { Glass } from '../../src/components/Glass';
import { IconButton } from '../../src/components/IconButton';
import { Ring } from '../../src/components/Ring';
import { Screen } from '../../src/components/Screen';
import { ScreenHeader } from '../../src/components/ScreenHeader';
import { Text } from '../../src/components/Text';
import { dateOnly, fmt, mnt } from '../../src/lib/format';
import { useTheme } from '../../src/theme/ThemeProvider';
import type { components } from '../../types/api';

type VehicleDueOut = components['schemas']['VehicleDueOut'];
type VehicleDueKind = components['schemas']['VehicleDueKind'];

const DUE_LABELS: Record<VehicleDueKind, string> = {
  tax: 'Тээврийн хураамж',
  insurance: 'Даатгал',
  fines: 'Жолооны торгууль',
};

const DUE_ICONS: Record<VehicleDueKind, 'credit-card' | 'umbrella' | 'shield'> = {
  tax: 'credit-card',
  insurance: 'umbrella',
  fines: 'shield',
};

export default function ServiceScreen() {
  const theme = useTheme();
  const router = useRouter();
  const qc = useQueryClient();
  const vehiclesQ = useQuery({ queryKey: ['vehicles', 'me'], queryFn: () => listMyVehicles() });
  const primary = vehiclesQ.data?.items?.[0] ?? null;
  const id = primary?.id;

  /**
   * IDs of dues whose payments are in flight (after the user tapped
   * "Төлөх" and we successfully kicked off the QPay invoice). While
   * any are present we keep polling the dues list every 4 s until the
   * backend reports `status === 'paid'` for them.
   */
  const [pendingPayIds, setPendingPayIds] = useState<Set<string>>(new Set());

  const histQ = useQuery({
    queryKey: ['vehicle', id, 'service-history'],
    queryFn: () => (id ? listServiceHistory(id) : Promise.reject(new Error('no vehicle'))),
    enabled: !!id,
  });

  const duesQ = useQuery({
    queryKey: ['vehicle', id, 'dues'],
    queryFn: () => (id ? listDues(id) : Promise.reject(new Error('no vehicle'))),
    enabled: !!id,
    refetchInterval: pendingPayIds.size > 0 ? 4000 : false,
  });

  // Once the backend reports a pending due as `paid`, drop it from the
  // polling set. When the set empties, the `refetchInterval` above
  // turns itself off automatically on the next render.
  const dueItems = duesQ.data?.items ?? [];
  const stillPending = new Set<string>();
  for (const due of dueItems) {
    if (pendingPayIds.has(due.id) && due.status !== 'paid') {
      stillPending.add(due.id);
    }
  }
  if (stillPending.size !== pendingPayIds.size) {
    queueMicrotask(() => setPendingPayIds(stillPending));
  }

  const payMu = useMutation({
    mutationFn: async (vars: { vehicleId: string; dueId: string }) => {
      return payDue(vars.vehicleId, vars.dueId);
    },
    onSuccess: async (out, vars) => {
      // Mark this due as in-flight so the dues query starts polling.
      setPendingPayIds((prev) => {
        const next = new Set(prev);
        next.add(vars.dueId);
        return next;
      });
      await qc.invalidateQueries({ queryKey: ['vehicle', id, 'dues'] });
      // Open the deeplink the user can complete payment in.
      const target =
        out.deeplink ??
        (Array.isArray(out.urls) && out.urls.length > 0
          ? typeof out.urls[0]?.link === 'string'
            ? (out.urls[0].link as string)
            : null
          : null);
      if (target) {
        try {
          await WebBrowser.openBrowserAsync(target);
        } catch {
          // openBrowser failures are non-fatal — the polling will
          // still flip the row once the user finishes in another
          // app.
        }
      } else {
        Alert.alert(
          'QPay холбоос алга',
          'Төлбөрийн линк боловсруулагдаж байна. Хэсэг хүлээж дахин оролдоно уу.',
        );
      }
    },
    onError: () => {
      Alert.alert('Алдаа', 'Төлбөрийн нэхэмжлэх үүсгэж чадсангүй.');
    },
  });

  const onPay = useCallback(
    (due: VehicleDueOut) => {
      if (!id) return;
      payMu.mutate({ vehicleId: id, dueId: due.id });
    },
    [id, payMu],
  );

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
          {duesQ.isLoading && dueItems.length === 0 ? (
            <Loading />
          ) : dueItems.length === 0 ? (
            <Empty
              title="Төлбөргүй байна"
              sub="Тээврийн хураамж, даатгал, торгууль одоогоор алга. Шинэ хугацаа ойртвол энд харагдана."
            />
          ) : (
            dueItems.map((d) => (
              <DueRow
                key={d.id}
                due={d}
                pending={pendingPayIds.has(d.id) || (payMu.isPending && payMu.variables?.dueId === d.id)}
                onPay={() => onPay(d)}
              />
            ))
          )}
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

function DueRow({
  due,
  pending,
  onPay,
}: {
  due: VehicleDueOut;
  pending: boolean;
  onPay: () => void;
}) {
  const theme = useTheme();
  const isPaid = due.status === 'paid';
  const isOverdue = due.status === 'overdue';
  const isDue = due.status === 'due';
  const showPayBtn = isDue || isOverdue;
  const stripe = isPaid
    ? theme.colors.success
    : isOverdue
      ? theme.colors.danger
      : isDue
        ? theme.colors.warn
        : theme.colors.success;
  const tint = isPaid
    ? theme.colors.success
    : isOverdue
      ? theme.colors.danger
      : isDue
        ? theme.colors.warn
        : theme.colors.success;

  return (
    <Glass
      radius="md"
      style={{ borderLeftWidth: 3, borderLeftColor: stripe }}
    >
      <View style={{ flexDirection: 'row', alignItems: 'center', gap: 12 }}>
        <View
          style={[
            styles.icoBox,
            {
              backgroundColor: isPaid
                ? 'rgba(94,226,160,0.16)'
                : isOverdue
                  ? 'rgba(255,123,156,0.18)'
                  : 'rgba(255,179,71,0.18)',
            },
          ]}
        >
          <Feather name={DUE_ICONS[due.kind]} size={18} color={tint} />
        </View>
        <View style={{ flex: 1, minWidth: 0 }}>
          <Text variant="body" weight="600">
            {DUE_LABELS[due.kind]}
          </Text>
          <Text variant="caption" tone="tertiary" style={{ marginTop: 2 }}>
            {isPaid
              ? due.paid_at
                ? `Төлсөн ${dateOnly(due.paid_at)}`
                : 'Төлсөн'
              : due.due_date
                ? `Хугацаа: ${dateOnly(due.due_date)}`
                : 'Хугацаа тодорхойгүй'}
          </Text>
        </View>
        <View style={{ alignItems: 'flex-end', gap: 6 }}>
          <Text variant="num" weight="700">
            {mnt(due.amount_mnt)}
          </Text>
          {isPaid ? (
            <Text variant="caption" tone="success" weight="600">
              Төлөгдсөн
            </Text>
          ) : showPayBtn ? (
            <Button
              size="sm"
              label={pending ? 'Хүлээж байна…' : 'Төлөх'}
              onPress={onPay}
              loading={pending}
              disabled={pending}
            />
          ) : null}
        </View>
      </View>
    </Glass>
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
