/**
 * Business marketplace — incoming part-search feed + quote-submission
 * sheet. The sheet posts a `QuoteCreateIn` to
 * `/v1/marketplace/searches/{id}/quotes`.
 */

import { Feather } from '@expo/vector-icons';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { useState } from 'react';
import { Modal, Pressable, StyleSheet, TextInput, View } from 'react-native';

import { listIncomingPartSearches, submitQuote } from '../../src/api/marketplace';
import { Button } from '../../src/components/Button';
import { Chip } from '../../src/components/Chip';
import { Empty, Loading } from '../../src/components/Empty';
import { Glass } from '../../src/components/Glass';
import { Screen } from '../../src/components/Screen';
import { ScreenHeader } from '../../src/components/ScreenHeader';
import { Text } from '../../src/components/Text';
import { relativeMn } from '../../src/lib/format';
import { useTheme } from '../../src/theme/ThemeProvider';
import type { components } from '../../types/api';

type PartSearchOut = components['schemas']['PartSearchOut'];

export default function BusinessMarket() {
  const theme = useTheme();
  const incomingQ = useQuery({
    queryKey: ['searches', 'incoming'],
    queryFn: () => listIncomingPartSearches({ limit: 50 }),
  });
  const [active, setActive] = useState<PartSearchOut | null>(null);

  return (
    <Screen scroll>
      <ScreenHeader sub="ХҮСЭЛТҮҮД" title="Шинэ хүсэлт" />

      <View style={{ paddingHorizontal: 18 }}>
        {incomingQ.isLoading ? (
          <Loading />
        ) : (incomingQ.data?.items.length ?? 0) === 0 ? (
          <Empty
            title="Хүсэлт алга"
            sub="Таны хамрах брэндэд тохирох жолоочдын хүсэлт орж ирэхэд энд харагдана."
          />
        ) : (
          <View style={{ gap: 10 }}>
            {(incomingQ.data?.items ?? []).map((s) => (
              <Pressable key={s.id} onPress={() => setActive(s)}>
                <Glass radius="md">
                  <View style={{ flexDirection: 'row', alignItems: 'flex-start', gap: 10 }}>
                    <View style={[styles.icoBox, { backgroundColor: theme.colors.accentGlow }]}>
                      <Feather name="message-circle" size={18} color={theme.colors.accent2} />
                    </View>
                    <View style={{ flex: 1, minWidth: 0 }}>
                      <Text variant="body" weight="600" numberOfLines={2}>
                        {s.description}
                      </Text>
                      <View style={{ flexDirection: 'row', gap: 6, marginTop: 6 }}>
                        <Chip label={relativeMn(s.created_at)} />
                        <Chip
                          label={s.status === 'open' ? 'Нээлттэй' : s.status}
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

      <QuoteSheet active={active} onClose={() => setActive(null)} />
    </Screen>
  );
}

function QuoteSheet({ active, onClose }: { active: PartSearchOut | null; onClose: () => void }) {
  const theme = useTheme();
  const qc = useQueryClient();
  const [price, setPrice] = useState('');
  const [notes, setNotes] = useState('');
  const [condition, setCondition] = useState<'new' | 'used' | 'imported'>('new');
  const submit = useMutation({
    mutationFn: () => {
      if (!active) throw new Error('no search');
      return submitQuote(active.id, {
        condition,
        price_mnt: Number(price) || 0,
        notes: notes.trim() || null,
        media_asset_ids: [],
      });
    },
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: ['searches', 'incoming'] });
      void qc.invalidateQueries({ queryKey: ['quotes', 'mine'] });
      setPrice('');
      setNotes('');
      onClose();
    },
  });

  if (!active) return null;
  return (
    <Modal visible animationType="slide" transparent>
      <View style={modalStyles.backdrop}>
        <View style={[modalStyles.sheet, { backgroundColor: theme.colors.bg1 }]}>
          <View style={modalStyles.sheetHeader}>
            <Text variant="heading">Үнийн санал</Text>
            <Pressable onPress={onClose}>
              <Feather name="x" size={20} color={theme.colors.text} />
            </Pressable>
          </View>

          <Text variant="caption" tone="tertiary" style={{ marginBottom: 8 }}>
            {active.description}
          </Text>

          <View style={{ flexDirection: 'row', gap: 6 }}>
            {(['new', 'used', 'imported'] as const).map((c) => (
              <Pressable key={c} onPress={() => setCondition(c)}>
                <Chip
                  label={c === 'new' ? 'Шинэ' : c === 'used' ? 'Хуучин' : 'Орж ирсэн'}
                  tone={condition === c ? 'accent' : 'neutral'}
                />
              </Pressable>
            ))}
          </View>

          <View style={{ marginTop: 12 }}>
            <Text variant="eyebrow" tone="tertiary">
              ҮНЭ (₮)
            </Text>
            <Glass radius="md" style={{ paddingVertical: 4, marginTop: 4 }}>
              <TextInput
                value={price}
                onChangeText={setPrice}
                placeholder="18500"
                placeholderTextColor={theme.colors.text3}
                keyboardType="numeric"
                style={{ color: theme.colors.text, fontSize: 16, paddingVertical: 6 }}
              />
            </Glass>
          </View>

          <View style={{ marginTop: 12 }}>
            <Text variant="eyebrow" tone="tertiary">
              ТЭМДЭГЛЭЛ
            </Text>
            <Glass radius="md" style={{ paddingVertical: 4, marginTop: 4 }}>
              <TextInput
                value={notes}
                onChangeText={setNotes}
                placeholder="Жинхэнэ Toyota, баталгаатай"
                placeholderTextColor={theme.colors.text3}
                multiline
                style={{
                  color: theme.colors.text,
                  fontSize: 14,
                  paddingVertical: 6,
                  minHeight: 60,
                  textAlignVertical: 'top',
                }}
              />
            </Glass>
          </View>

          <Button
            size="lg"
            label={submit.isPending ? 'Илгээж байна…' : 'Санал илгээх'}
            onPress={() => submit.mutate()}
            disabled={!Number(price) || submit.isPending}
            loading={submit.isPending}
            style={{ marginTop: 14 }}
          />
        </View>
      </View>
    </Modal>
  );
}

const styles = StyleSheet.create({
  icoBox: {
    width: 36,
    height: 36,
    borderRadius: 10,
    alignItems: 'center',
    justifyContent: 'center',
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
