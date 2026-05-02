/**
 * Part-search detail — driver POV. Shows the request, the list of
 * incoming quotes, and a CTA to open chat with a particular supplier
 * (which doesn't exist yet — backend creates a thread per quote on
 * reserve, so the chat link goes through a reservation step).
 */

import { Feather } from '@expo/vector-icons';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { useLocalSearchParams, useRouter } from 'expo-router';
import { Pressable, StyleSheet, View } from 'react-native';

import {
  cancelPartSearch,
  getPartSearch,
  listSearchQuotes,
  reserveQuote,
} from '../../../src/api/marketplace';
import { Button } from '../../../src/components/Button';
import { Chip } from '../../../src/components/Chip';
import { Empty, Loading } from '../../../src/components/Empty';
import { Glass } from '../../../src/components/Glass';
import { IconButton } from '../../../src/components/IconButton';
import { Screen } from '../../../src/components/Screen';
import { ScreenHeader } from '../../../src/components/ScreenHeader';
import { Text } from '../../../src/components/Text';
import { mnt, relativeMn } from '../../../src/lib/format';
import { useTheme } from '../../../src/theme/ThemeProvider';

export default function PartSearchDetail() {
  const theme = useTheme();
  const router = useRouter();
  const qc = useQueryClient();
  const { id } = useLocalSearchParams<{ id?: string }>();

  const searchQ = useQuery({
    queryKey: ['search', id],
    queryFn: () => {
      if (!id) throw new Error('missing id');
      return getPartSearch(id);
    },
    enabled: !!id,
  });
  const quotesQ = useQuery({
    queryKey: ['search', id, 'quotes'],
    queryFn: () => {
      if (!id) throw new Error('missing id');
      return listSearchQuotes(id, { limit: 50 });
    },
    enabled: !!id,
  });

  const reserve = useMutation({
    mutationFn: (quoteId: string) => reserveQuote(quoteId),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: ['search', id] });
      void qc.invalidateQueries({ queryKey: ['reservations', 'mine'] });
    },
  });

  const cancel = useMutation({
    mutationFn: () => {
      if (!id) throw new Error('missing id');
      return cancelPartSearch(id);
    },
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: ['search', id] });
      void qc.invalidateQueries({ queryKey: ['searches', 'mine'] });
    },
  });

  if (searchQ.isLoading) return <Loading label="Уншиж байна" />;
  const search = searchQ.data;
  if (!search) {
    return (
      <Screen contentStyle={{ paddingHorizontal: 18 }}>
        <Empty title="Хүсэлт олдсонгүй" />
      </Screen>
    );
  }

  const quotes = quotesQ.data?.items ?? [];

  return (
    <Screen scroll>
      <ScreenHeader
        sub="ХҮСЭЛТ"
        title="Үнийн санал"
        left={
          <IconButton onPress={() => router.back()}>
            <Feather name="arrow-left" size={18} color={theme.colors.text} />
          </IconButton>
        }
        right={
          search.status === 'open' ? (
            <IconButton onPress={() => cancel.mutate()}>
              <Feather name="x" size={16} color={theme.colors.text2} />
            </IconButton>
          ) : null
        }
      />

      <View style={{ paddingHorizontal: 18 }}>
        <Glass radius="md">
          <Text variant="eyebrow" tone="tertiary">
            ТАЙЛБАР
          </Text>
          <Text variant="body" style={{ marginTop: 6, lineHeight: 20 }}>
            {search.description}
          </Text>
          <View style={{ flexDirection: 'row', gap: 6, marginTop: 10 }}>
            <Chip
              label={statusLabel(search.status)}
              tone={search.status === 'open' ? 'success' : 'neutral'}
            />
            <Chip label={relativeMn(search.created_at)} />
          </View>
        </Glass>

        <View style={styles.quotesHeader}>
          <Text variant="heading">Үнийн саналууд</Text>
          <Text variant="caption" tone="tertiary">
            <Text variant="mono">{quotes.length}</Text> санал
          </Text>
        </View>

        {quotesQ.isLoading ? (
          <Loading />
        ) : quotes.length === 0 ? (
          <Empty
            title="Санал ирээгүй байна"
            sub="Бизнесүүд таны хүсэлтийг хараад үнэ ирүүлмэгц энд харагдана."
          />
        ) : (
          <View style={{ gap: 10, marginTop: 10 }}>
            {quotes.map((q) => (
              <Glass key={q.id} radius="md">
                <View style={{ flexDirection: 'row', alignItems: 'flex-start', gap: 10 }}>
                  <View style={[styles.thumb, { backgroundColor: theme.colors.surface2 }]}>
                    <Feather name="package" size={20} color={theme.colors.accent2} />
                  </View>
                  <View style={{ flex: 1, minWidth: 0 }}>
                    <View style={styles.priceRow}>
                      <Text variant="num" weight="700" style={{ fontSize: 18 }}>
                        {mnt(q.price_mnt)}
                      </Text>
                      <Chip label={conditionLabel(q.condition)} tone="accent" />
                    </View>
                    {q.notes ? (
                      <Text variant="caption" tone="secondary" style={{ marginTop: 4 }}>
                        {q.notes}
                      </Text>
                    ) : null}
                    <Text variant="caption" tone="tertiary" style={{ marginTop: 4 }}>
                      {relativeMn(q.created_at)}
                    </Text>
                  </View>
                </View>
                {search.status === 'open' ? (
                  <Pressable
                    style={{ marginTop: 10 }}
                    disabled={reserve.isPending}
                    onPress={() => reserve.mutate(q.id)}
                  >
                    <Button
                      size="md"
                      label={reserve.isPending ? 'Захиалж байна…' : '24 цаг захиалах'}
                      onPress={() => reserve.mutate(q.id)}
                      disabled={reserve.isPending}
                      loading={reserve.isPending}
                      leftIcon={<Feather name="clock" size={14} color="#fff" />}
                    />
                  </Pressable>
                ) : null}
              </Glass>
            ))}
          </View>
        )}
      </View>
    </Screen>
  );
}

function statusLabel(s: string): string {
  switch (s) {
    case 'open':
      return 'Нээлттэй';
    case 'cancelled':
      return 'Цуцлагдсан';
    case 'expired':
      return 'Хугацаа дууссан';
    case 'fulfilled':
      return 'Биелсэн';
    default:
      return s;
  }
}

function conditionLabel(c: string): string {
  switch (c) {
    case 'new':
      return 'Шинэ';
    case 'used':
      return 'Хуучин';
    case 'imported':
      return 'Орж ирсэн';
    default:
      return c;
  }
}

const styles = StyleSheet.create({
  quotesHeader: {
    marginTop: 18,
    marginBottom: 6,
    flexDirection: 'row',
    alignItems: 'baseline',
    justifyContent: 'space-between',
  },
  thumb: {
    width: 44,
    height: 44,
    borderRadius: 10,
    alignItems: 'center',
    justifyContent: 'center',
  },
  priceRow: {
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'space-between',
    gap: 8,
  },
});
