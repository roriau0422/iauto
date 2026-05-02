/**
 * Driver Marketplace — list of the user's part-search requests + a CTA
 * to compose a new one.
 *
 * The design's static "parts list" (catalog rows with prices, shop,
 * stars, distance) doesn't have a backend equivalent in phase 1 —
 * the marketplace surface is request-for-quote, not a parts catalog.
 * We render the user's outstanding/closed RFQs and link each to its
 * detail screen where quotes show up.
 */

import { Feather } from '@expo/vector-icons';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { useRouter } from 'expo-router';
import { useState } from 'react';
import {
  Pressable,
  ScrollView,
  StyleSheet,
  TextInput,
  View,
} from 'react-native';

import { createPartSearch, listMyPartSearches } from '../../../src/api/marketplace';
import { listMyVehicles } from '../../../src/api/vehicles';
import { Button } from '../../../src/components/Button';
import { Chip } from '../../../src/components/Chip';
import { Empty, Loading } from '../../../src/components/Empty';
import { Glass } from '../../../src/components/Glass';
import { IconButton } from '../../../src/components/IconButton';
import { Screen } from '../../../src/components/Screen';
import { ScreenHeader } from '../../../src/components/ScreenHeader';
import { Text } from '../../../src/components/Text';
import { fuelLabelMn, relativeMn } from '../../../src/lib/format';
import { useTheme } from '../../../src/theme/ThemeProvider';

export default function DriverMarketList() {
  const theme = useTheme();
  const router = useRouter();
  const qc = useQueryClient();

  const vehiclesQ = useQuery({ queryKey: ['vehicles', 'me'], queryFn: () => listMyVehicles() });
  const searchesQ = useQuery({
    queryKey: ['searches', 'mine'],
    queryFn: () => listMyPartSearches({ limit: 50 }),
  });

  const [composing, setComposing] = useState(false);
  const [desc, setDesc] = useState('');
  const [filter, setFilter] = useState<'open' | 'all'>('open');

  const create = useMutation({
    mutationFn: createPartSearch,
    onSuccess: () => {
      setComposing(false);
      setDesc('');
      void qc.invalidateQueries({ queryKey: ['searches', 'mine'] });
    },
  });

  const vehicles = vehiclesQ.data?.items ?? [];
  const primary = vehicles[0] ?? null;

  const items = (searchesQ.data?.items ?? []).filter((s) => {
    if (filter === 'all') return true;
    return s.status === 'open';
  });

  const onSubmit = () => {
    if (!primary || !desc.trim()) return;
    create.mutate({
      description: desc.trim(),
      vehicle_id: primary.id,
      media_asset_ids: [],
    });
  };

  return (
    <Screen scroll>
      <ScreenHeader
        sub="ЗАХ ЗЭЭЛ"
        title="Эд анги хайх"
        right={
          <IconButton onPress={() => setComposing((v) => !v)} active={composing}>
            <Feather name={composing ? 'x' : 'plus'} size={18} color={theme.colors.text} />
          </IconButton>
        }
      />

      <View style={{ paddingHorizontal: 18 }}>
        {primary ? (
          <ScrollView
            horizontal
            showsHorizontalScrollIndicator={false}
            contentContainerStyle={{ gap: 6, paddingBottom: 6 }}
          >
            <Chip label={`${primary.make ?? ''} ${primary.model ?? ''}`.trim() || 'Машин'} tone="accent" />
            {primary.steering_side ? <Chip label={primary.steering_side} /> : null}
            {primary.capacity_cc ? <Chip label={`${primary.capacity_cc}cc`} /> : null}
            {primary.fuel_type ? <Chip label={fuelLabelMn(primary.fuel_type)} /> : null}
          </ScrollView>
        ) : null}

        {composing ? (
          <Glass radius="md" style={{ marginTop: 12 }}>
            <Text variant="eyebrow" tone="tertiary">
              ШИНЭ ХҮСЭЛТ
            </Text>
            <TextInput
              value={desc}
              onChangeText={setDesc}
              placeholder="Тосны шүүлтүүр Prius 2018"
              placeholderTextColor={theme.colors.text3}
              multiline
              style={[styles.composer, { color: theme.colors.text }]}
            />
            {!primary ? (
              <Text variant="caption" tone="warn" style={{ marginTop: 8 }}>
                Хүсэлт явуулахад машинаа бүртгүүлсэн байх шаардлагатай.
              </Text>
            ) : null}
            <Button
              size="md"
              label={create.isPending ? 'Илгээж байна…' : 'Хүсэлт явуулах'}
              onPress={onSubmit}
              disabled={!primary || !desc.trim() || create.isPending}
              loading={create.isPending}
              leftIcon={<Feather name="send" size={16} color="#fff" />}
              style={{ marginTop: 12 }}
            />
          </Glass>
        ) : null}

        <View style={styles.filters}>
          {(
            [
              { k: 'open' as const, label: 'Хүлээгдэж байгаа' },
              { k: 'all' as const, label: 'Бүгд' },
            ]
          ).map((f) => (
            <Pressable key={f.k} onPress={() => setFilter(f.k)}>
              <Chip label={f.label} tone={filter === f.k ? 'accent' : 'neutral'} />
            </Pressable>
          ))}
          <View style={{ flex: 1 }} />
          <Text variant="caption" tone="tertiary">
            <Text variant="mono">{items.length}</Text> үр дүн
          </Text>
        </View>

        {searchesQ.isLoading ? (
          <Loading label="Хүсэлтүүд татаж байна" />
        ) : items.length === 0 ? (
          <Empty
            title="Идэвхтэй хүсэлт алга"
            sub="Эд ангийн нэр, машины модел оруулж бизнесүүдээс үнийн саналыг авна уу."
          />
        ) : (
          <View style={{ gap: 10, marginTop: 10 }}>
            {items.map((s) => (
              <Pressable
                key={s.id}
                onPress={() => router.push({ pathname: '/(driver)/market/[id]', params: { id: s.id } })}
              >
                <Glass radius="md">
                  <View style={{ flexDirection: 'row', alignItems: 'flex-start', gap: 12 }}>
                    <View style={[styles.thumb, { backgroundColor: theme.colors.surface2 }]}>
                      <Feather name="search" size={20} color={theme.colors.text2} />
                    </View>
                    <View style={{ flex: 1, minWidth: 0 }}>
                      <Text variant="body" weight="600" numberOfLines={2}>
                        {s.description}
                      </Text>
                      <Text variant="caption" tone="tertiary" style={{ marginTop: 4 }}>
                        {relativeMn(s.created_at)}
                      </Text>
                      <View style={{ flexDirection: 'row', gap: 6, marginTop: 6 }}>
                        <Chip
                          label={statusLabel(s.status)}
                          tone={s.status === 'open' ? 'success' : 'neutral'}
                        />
                      </View>
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

const styles = StyleSheet.create({
  composer: {
    minHeight: 80,
    fontSize: 14,
    marginTop: 8,
    paddingVertical: 4,
    textAlignVertical: 'top',
  },
  filters: { flexDirection: 'row', alignItems: 'center', gap: 6, marginTop: 14 },
  thumb: {
    width: 56,
    height: 56,
    borderRadius: 12,
    alignItems: 'center',
    justifyContent: 'center',
  },
});
