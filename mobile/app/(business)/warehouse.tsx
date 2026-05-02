/**
 * Business warehouse — SKU table + lightweight stock-movement sheet.
 *
 * The design's row layout (name / on_hand / sold / unit price) maps to
 * `SkuListOut.items` directly. We don't yet have a "sold-this-week"
 * counter on the SKU row; that's a phase 2 aggregate. Showing the
 * `low_stock_threshold` flag in red is real-data-driven.
 */

import { Feather } from '@expo/vector-icons';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { useState } from 'react';
import {
  Modal,
  Pressable,
  StyleSheet,
  TextInput,
  View,
} from 'react-native';

import {
  createSku,
  listSkus,
  recordMovement,
} from '../../src/api/warehouse';
import { Button } from '../../src/components/Button';
import { Chip } from '../../src/components/Chip';
import { Empty, Loading } from '../../src/components/Empty';
import { Glass } from '../../src/components/Glass';
import { IconButton } from '../../src/components/IconButton';
import { Screen } from '../../src/components/Screen';
import { ScreenHeader } from '../../src/components/ScreenHeader';
import { Text } from '../../src/components/Text';
import { fmt } from '../../src/lib/format';
import { useTheme } from '../../src/theme/ThemeProvider';
import type { components } from '../../types/api';

type SkuOut = components['schemas']['SkuOut'];

export default function WarehouseScreen() {
  const theme = useTheme();
  const qc = useQueryClient();
  const [q, setQ] = useState('');
  const [composing, setComposing] = useState(false);
  const [movingSku, setMovingSku] = useState<SkuOut | null>(null);

  const skusQ = useQuery({
    queryKey: ['skus', q],
    queryFn: () => listSkus({ q: q || null, limit: 100 }),
  });

  return (
    <Screen scroll>
      <ScreenHeader
        sub="АГУУЛАХ"
        title="Бараа материал"
        right={
          <View style={{ flexDirection: 'row', gap: 6 }}>
            <IconButton onPress={() => setComposing(true)} filled>
              <Feather name="plus" size={18} color="#fff" />
            </IconButton>
          </View>
        }
      />

      <View style={{ paddingHorizontal: 18 }}>
        <Glass radius="md">
          <View style={{ flexDirection: 'row', alignItems: 'center', gap: 8 }}>
            <Feather name="search" size={16} color={theme.colors.text2} />
            <TextInput
              value={q}
              onChangeText={setQ}
              placeholder="SKU код, нэр…"
              placeholderTextColor={theme.colors.text3}
              style={{ flex: 1, color: theme.colors.text, fontSize: 13, paddingVertical: 4 }}
            />
          </View>
        </Glass>

        {skusQ.isLoading ? (
          <Loading />
        ) : (skusQ.data?.items.length ?? 0) === 0 ? (
          <Empty title="SKU алга" sub="Шинэ бараа нэмэх товчоор эхэлнэ үү." />
        ) : (
          <Glass radius="md" style={{ marginTop: 10, paddingHorizontal: 0, paddingVertical: 0 }}>
            <View style={[styles.head, { borderBottomColor: theme.colors.stroke2 }]}>
              <Text variant="eyebrow" tone="tertiary" style={{ flex: 2.2 }}>
                Бараа
              </Text>
              <Text variant="eyebrow" tone="tertiary" style={{ flex: 0.8, textAlign: 'right' }}>
                Үлд.
              </Text>
              <Text variant="eyebrow" tone="tertiary" style={{ flex: 0.8, textAlign: 'right' }}>
                Үнэ
              </Text>
              <Text variant="eyebrow" tone="tertiary" style={{ width: 32 }} />
            </View>
            {(skusQ.data?.items ?? []).map((s, i, arr) => {
              const low =
                s.low_stock_threshold != null && s.low_stock_threshold > 0;
              return (
                <View
                  key={s.id}
                  style={[
                    styles.row,
                    i < arr.length - 1
                      ? { borderBottomWidth: StyleSheet.hairlineWidth, borderBottomColor: theme.colors.stroke2 }
                      : null,
                  ]}
                >
                  <View style={{ flex: 2.2, minWidth: 0 }}>
                    <Text variant="body" weight="600" numberOfLines={1}>
                      {s.display_name}
                    </Text>
                    <Text variant="mono" tone="tertiary" style={{ fontSize: 10 }}>
                      {s.sku_code}
                    </Text>
                  </View>
                  <Text
                    variant="num"
                    weight="700"
                    style={{
                      flex: 0.8,
                      textAlign: 'right',
                      color: low ? theme.colors.warn : theme.colors.text,
                    }}
                  >
                    {s.low_stock_threshold != null ? fmt(s.low_stock_threshold) : '—'}
                  </Text>
                  <Text variant="num" weight="600" style={{ flex: 0.8, textAlign: 'right' }}>
                    {s.unit_price_mnt != null ? `${(s.unit_price_mnt / 1000).toFixed(0)}k` : '—'}
                  </Text>
                  <Pressable onPress={() => setMovingSku(s)}>
                    <Feather name="more-vertical" size={16} color={theme.colors.text3} />
                  </Pressable>
                </View>
              );
            })}
          </Glass>
        )}
      </View>

      <NewSkuSheet open={composing} onClose={() => setComposing(false)} />
      <MoveStockSheet
        sku={movingSku}
        onClose={() => setMovingSku(null)}
        onSuccess={() => {
          setMovingSku(null);
          void qc.invalidateQueries({ queryKey: ['skus'] });
        }}
      />
    </Screen>
  );
}

function NewSkuSheet({ open, onClose }: { open: boolean; onClose: () => void }) {
  const theme = useTheme();
  const qc = useQueryClient();
  const [code, setCode] = useState('');
  const [name, setName] = useState('');
  const [price, setPrice] = useState('');

  const create = useMutation({
    mutationFn: createSku,
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: ['skus'] });
      setCode('');
      setName('');
      setPrice('');
      onClose();
    },
  });

  const onSubmit = () => {
    if (!code.trim() || !name.trim()) return;
    create.mutate({
      sku_code: code.trim(),
      display_name: name.trim(),
      unit_price_mnt: price.trim() ? Number(price) : null,
      condition: 'new',
    });
  };

  return (
    <Modal visible={open} animationType="slide" transparent>
      <View style={modalStyles.backdrop}>
        <View style={[modalStyles.sheet, { backgroundColor: theme.colors.bg1 }]}>
          <View style={modalStyles.sheetHeader}>
            <Text variant="heading">Шинэ SKU</Text>
            <Pressable onPress={onClose}>
              <Feather name="x" size={20} color={theme.colors.text} />
            </Pressable>
          </View>
          <SheetField label="SKU код" value={code} onChange={setCode} placeholder="90915-YZZF2" />
          <SheetField label="Нэр" value={name} onChange={setName} placeholder="Тосны шүүлтүүр" />
          <SheetField
            label="Нэгжийн үнэ (₮)"
            value={price}
            onChange={setPrice}
            placeholder="18500"
            numeric
          />
          <Button
            size="lg"
            label={create.isPending ? 'Хадгалж байна…' : 'Хадгалах'}
            disabled={!code.trim() || !name.trim() || create.isPending}
            loading={create.isPending}
            onPress={onSubmit}
            style={{ marginTop: 12 }}
          />
        </View>
      </View>
    </Modal>
  );
}

function MoveStockSheet({
  sku,
  onClose,
  onSuccess,
}: {
  sku: SkuOut | null;
  onClose: () => void;
  onSuccess: () => void;
}) {
  const theme = useTheme();
  const [qty, setQty] = useState('1');
  const [direction, setDirection] = useState<'up' | 'down'>('up');
  const open = !!sku;

  const move = useMutation({
    mutationFn: () => {
      if (!sku) throw new Error('no sku');
      return recordMovement(sku.id, {
        kind: direction === 'up' ? 'receive' : 'issue',
        direction,
        quantity: Number(qty) || 0,
        note: null,
      });
    },
    onSuccess,
  });

  if (!sku) return null;

  return (
    <Modal visible={open} animationType="slide" transparent>
      <View style={modalStyles.backdrop}>
        <View style={[modalStyles.sheet, { backgroundColor: theme.colors.bg1 }]}>
          <View style={modalStyles.sheetHeader}>
            <Text variant="heading">{sku.display_name}</Text>
            <Pressable onPress={onClose}>
              <Feather name="x" size={20} color={theme.colors.text} />
            </Pressable>
          </View>
          <Text variant="caption" tone="tertiary" style={{ marginBottom: 8 }}>
            Хөдөлгөөн бичих — орлого/зарлага
          </Text>

          <View style={{ flexDirection: 'row', gap: 6 }}>
            <Pressable onPress={() => setDirection('up')}>
              <Chip label="Орлого" tone={direction === 'up' ? 'accent' : 'neutral'} />
            </Pressable>
            <Pressable onPress={() => setDirection('down')}>
              <Chip label="Зарлага" tone={direction === 'down' ? 'accent' : 'neutral'} />
            </Pressable>
          </View>

          <SheetField label="Тоо ширхэг" value={qty} onChange={setQty} numeric />
          <Button
            size="lg"
            label={move.isPending ? 'Илгээж байна…' : 'Хадгалах'}
            disabled={!Number(qty) || move.isPending}
            loading={move.isPending}
            onPress={() => move.mutate()}
            style={{ marginTop: 12 }}
          />
        </View>
      </View>
    </Modal>
  );
}

function SheetField({
  label,
  value,
  onChange,
  placeholder,
  numeric,
}: {
  label: string;
  value: string;
  onChange: (s: string) => void;
  placeholder?: string;
  numeric?: boolean;
}) {
  const theme = useTheme();
  return (
    <View style={{ marginTop: 12 }}>
      <Text variant="eyebrow" tone="tertiary">
        {label}
      </Text>
      <Glass radius="md" style={{ paddingVertical: 4, marginTop: 4 }}>
        <TextInput
          value={value}
          onChangeText={onChange}
          placeholder={placeholder}
          placeholderTextColor={theme.colors.text3}
          keyboardType={numeric ? 'numeric' : 'default'}
          style={{ color: theme.colors.text, fontSize: 14, paddingVertical: 6 }}
        />
      </Glass>
    </View>
  );
}

const styles = StyleSheet.create({
  head: {
    flexDirection: 'row',
    alignItems: 'center',
    paddingHorizontal: 14,
    paddingVertical: 10,
    borderBottomWidth: StyleSheet.hairlineWidth,
  },
  row: {
    flexDirection: 'row',
    alignItems: 'center',
    paddingHorizontal: 14,
    paddingVertical: 12,
    gap: 6,
  },
});

const modalStyles = StyleSheet.create({
  backdrop: { flex: 1, backgroundColor: 'rgba(5,8,22,0.6)', justifyContent: 'flex-end' },
  sheet: { padding: 18, borderTopLeftRadius: 22, borderTopRightRadius: 22 },
  sheetHeader: {
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'space-between',
    marginBottom: 12,
  },
});
